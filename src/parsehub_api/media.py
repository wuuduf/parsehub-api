from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import socket
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from .errors import APIError


@dataclass(frozen=True, slots=True)
class MediaTarget:
    url: str
    filename: str
    headers: dict[str, str]


class MediaTokenStore:
    """Signed opaque tokens backed by bounded in-process state.

    Keeping the URL server-side prevents tokens from becoming arbitrary signed proxy URLs.
    A Redis implementation can replace this store without changing the HTTP contract.
    """

    def __init__(self, secret: str, ttl: int, max_items: int = 10_000) -> None:
        self.secret = secret.encode()
        self.ttl = ttl
        self.max_items = max_items
        self._targets: dict[str, tuple[float, MediaTarget]] = {}
        self._lock = asyncio.Lock()

    async def issue(self, target: MediaTarget) -> tuple[str, int]:
        expires = int(time.time()) + self.ttl
        token_id = uuid.uuid4().hex
        payload = f"{token_id}.{expires}"
        signature = hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
        token = f"{payload}.{_b64(signature)}"
        async with self._lock:
            self._purge_locked()
            if len(self._targets) >= self.max_items:
                oldest = min(self._targets, key=lambda key: self._targets[key][0])
                self._targets.pop(oldest, None)
            self._targets[token_id] = (float(expires), target)
        return token, expires

    async def resolve(self, token: str) -> MediaTarget:
        try:
            token_id, expires_text, signature = token.split(".", 2)
            expires = int(expires_text)
        except (ValueError, TypeError) as exc:
            raise APIError(404, "MEDIA_TOKEN_INVALID", "媒体链接无效") from exc
        payload = f"{token_id}.{expires}"
        expected = _b64(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected) or expires < int(time.time()):
            raise APIError(410, "MEDIA_TOKEN_EXPIRED", "媒体链接已失效")
        async with self._lock:
            item = self._targets.get(token_id)
            if item is None:
                raise APIError(404, "MEDIA_TOKEN_INVALID", "媒体链接无效")
            return item[1]

    def _purge_locked(self) -> None:
        now = time.time()
        for key, (expires, _) in list(self._targets.items()):
            if expires < now:
                self._targets.pop(key, None)


class MediaGateway:
    def __init__(self, *, timeout: int, max_bytes: int, allow_private: bool = False) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.allow_private = allow_private

    async def proxy(self, request: Request, target: MediaTarget) -> Response:
        await validate_public_url(target.url, allow_private=self.allow_private)
        headers = dict(target.headers)
        for name in ("range", "if-range", "if-none-match", "if-modified-since"):
            if value := request.headers.get(name):
                headers[name] = value
        client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=False)
        try:
            current_url = target.url
            for _ in range(6):
                await validate_public_url(current_url, allow_private=self.allow_private)
                upstream_request = client.build_request(request.method, current_url, headers=headers)
                upstream = await client.send(upstream_request, stream=True)
                if upstream.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = upstream.headers.get("location")
                await upstream.aclose()
                if not location:
                    raise APIError(502, "MEDIA_UPSTREAM_FAILED", "媒体重定向缺少目标地址")
                current_url = urljoin(current_url, location)
            else:
                raise APIError(502, "MEDIA_REDIRECT_LIMIT", "媒体重定向次数过多")
        except httpx.TimeoutException as exc:
            await client.aclose()
            raise APIError(504, "MEDIA_UPSTREAM_TIMEOUT", "媒体服务器响应超时", retryable=True) from exc
        except httpx.HTTPError as exc:
            await client.aclose()
            raise APIError(502, "MEDIA_UPSTREAM_FAILED", "媒体服务器请求失败", retryable=True) from exc
        except APIError:
            await client.aclose()
            raise

        if upstream.status_code >= 400:
            status = upstream.status_code
            await upstream.aclose()
            await client.aclose()
            raise APIError(502, "MEDIA_UPSTREAM_FAILED", f"媒体服务器返回 HTTP {status}", retryable=status >= 500)

        content_length = _integer(upstream.headers.get("content-length"))
        if content_length is not None and content_length > self.max_bytes:
            await upstream.aclose()
            await client.aclose()
            raise APIError(413, "MEDIA_TOO_LARGE", "媒体文件超过服务端限制")

        response_headers = _response_headers(upstream.headers, target.filename)
        if request.method == "HEAD":
            await upstream.aclose()
            await client.aclose()
            return Response(status_code=upstream.status_code, headers=response_headers)

        async def body() -> AsyncIterator[bytes]:
            seen = 0
            try:
                async for chunk in upstream.aiter_raw():
                    seen += len(chunk)
                    if seen > self.max_bytes:
                        break
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(body(), status_code=upstream.status_code, headers=response_headers)


async def validate_public_url(url: str, *, allow_private: bool = False) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise APIError(400, "MEDIA_URL_REJECTED", "媒体地址不符合安全策略")
    if allow_private:
        return
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise APIError(502, "MEDIA_DNS_FAILED", "媒体域名解析失败", retryable=True) from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise APIError(400, "MEDIA_URL_REJECTED", "媒体地址不符合安全策略")


def dump_target(target: MediaTarget) -> str:
    return json.dumps(asdict(target), ensure_ascii=False)


def load_target(value: str) -> MediaTarget:
    return MediaTarget(**json.loads(value))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _integer(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _response_headers(headers: httpx.Headers, filename: str) -> dict[str, str]:
    allowed = {
        "accept-ranges",
        "cache-control",
        "content-length",
        "content-range",
        "content-type",
        "etag",
        "expires",
        "last-modified",
    }
    result = {key: value for key, value in headers.items() if key.lower() in allowed}
    if "content-disposition" not in result:
        safe_name = filename.replace('"', "")
        result["Content-Disposition"] = f'inline; filename="{safe_name}"'
    return result
