from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from redis.asyncio import Redis

from .errors import APIError
from .media import MediaTarget, dump_target, load_target


class RedisTTLCache:
    def __init__(self, redis: Redis, ttl: int) -> None:
        self.redis = redis
        self.ttl = ttl

    async def get(self, key: str) -> Any | None:
        value = await self.redis.get(f"parsehub:cache:{key}")
        return json.loads(value) if value else None

    async def set(self, key: str, value: Any) -> None:
        await self.redis.setex(f"parsehub:cache:{key}", self.ttl, json.dumps(value, ensure_ascii=False))

    async def clear(self) -> None:
        keys = [key async for key in self.redis.scan_iter("parsehub:cache:*")]
        if keys:
            await self.redis.delete(*keys)


class RedisMediaTokenStore:
    def __init__(self, redis: Redis, secret: str, ttl: int) -> None:
        self.redis = redis
        self.secret = secret.encode()
        self.ttl = ttl

    async def issue(self, target: MediaTarget) -> tuple[str, int]:
        expires = int(time.time()) + self.ttl
        token_id = uuid.uuid4().hex
        payload = f"{token_id}.{expires}"
        signature = _b64(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())
        await self.redis.setex(f"parsehub:media:{token_id}", self.ttl, dump_target(target))
        return f"{payload}.{signature}", expires

    async def resolve(self, token: str) -> MediaTarget:
        try:
            token_id, expires_text, signature = token.split(".", 2)
            expires = int(expires_text)
        except (TypeError, ValueError) as exc:
            raise APIError(404, "MEDIA_TOKEN_INVALID", "媒体链接无效") from exc
        payload = f"{token_id}.{expires}"
        expected = _b64(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())
        if expires < int(time.time()) or not hmac.compare_digest(signature, expected):
            raise APIError(410, "MEDIA_TOKEN_EXPIRED", "媒体链接已失效")
        value = await self.redis.get(f"parsehub:media:{token_id}")
        if not value:
            raise APIError(404, "MEDIA_TOKEN_INVALID", "媒体链接无效")
        if isinstance(value, bytes):
            value = value.decode()
        return load_target(value)


class RedisRateLimiter:
    def __init__(self, redis: Redis, requests: int, window: int) -> None:
        self.redis = redis
        self.requests = requests
        self.window = window

    async def allow(self, identity: str) -> tuple[bool, int]:
        bucket = int(time.time()) // self.window
        key = f"parsehub:rate:{hashlib.sha256(identity.encode()).hexdigest()}:{bucket}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, self.window + 1)
        return count <= self.requests, self.window if count > self.requests else 0


class RedisDailyQuota:
    def __init__(self, redis: Redis, limit: int) -> None:
        self.redis = redis
        self.limit = limit

    async def consume(self, identity: str, limit: int | None = None) -> tuple[bool, int]:
        effective_limit = limit or self.limit
        day = time.strftime("%Y-%m-%d", time.gmtime())
        key = f"parsehub:quota:{identity}:{day}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 172800)
        return count <= effective_limit, max(0, effective_limit - count)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
