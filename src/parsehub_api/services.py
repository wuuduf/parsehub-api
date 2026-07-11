from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Sequence
from typing import Any

from parsehub import ParseHub
from parsehub.errors import ParseError, UnknownPlatform
from parsehub.types import AniRef, ImageRef, LivePhotoRef, VideoRef

from .admin_store import AdminStore, PlatformCredential
from .cache import CacheProtocol
from .circuit import CircuitBreaker
from .errors import APIError
from .metrics import Metrics


class ResolverService:
    def __init__(
        self,
        parser: ParseHub,
        *,
        cache: CacheProtocol,
        timeout: int,
        max_concurrent: int,
        circuit: CircuitBreaker,
        metrics: Metrics,
        admin_store: AdminStore,
    ) -> None:
        self.parser = parser
        self.cache = cache
        self.timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self.circuit = circuit
        self.metrics = metrics
        self.admin_store = admin_store
        self._flights: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self._flights_lock = asyncio.Lock()

    async def resolve(self, text: str, *, include_content: bool) -> tuple[dict[str, Any], bool]:
        detected = self.parser.get_platform(text)
        platform_id = detected.id if detected else "unknown"
        credential = self.admin_store.get_credential(platform_id)
        credential_fingerprint = hashlib.sha256(
            f"{credential.cookie or ''}\0{credential.proxy or ''}".encode()
        ).hexdigest()
        cache_material = f"{platform_id}:{credential_fingerprint}:{text.strip()}"
        key = hashlib.sha256(cache_material.encode()).hexdigest()
        if cached := await self.cache.get(key):
            return self._with_content(cached, include_content), True

        async with self._flights_lock:
            task = self._flights.get(key)
            if task is None:
                task = asyncio.create_task(self._parse(text, key, platform_id, credential))
                self._flights[key] = task

        try:
            value = await asyncio.shield(task)
        finally:
            if task.done():
                async with self._flights_lock:
                    if self._flights.get(key) is task:
                        self._flights.pop(key, None)

        return self._with_content(value, include_content), False

    async def _parse(
        self, text: str, key: str, platform_id: str, credential: PlatformCredential
    ) -> dict[str, Any]:
        if not await self.circuit.allow(platform_id):
            raise APIError(503, "PLATFORM_CIRCUIT_OPEN", "该平台暂时不可用，请稍后重试", retryable=True)
        try:
            async with self._semaphore:
                result = await asyncio.wait_for(
                    self.parser.parse(text, proxy=credential.proxy, cookie=credential.cookie),
                    timeout=self.timeout,
                )
        except TimeoutError as exc:
            await self.circuit.failure(platform_id)
            await self.metrics.increment("resolve_total", platform=platform_id, result="timeout")
            raise APIError(504, "UPSTREAM_TIMEOUT", "上游解析超时", retryable=True) from exc
        except UnknownPlatform as exc:
            await self.metrics.increment("resolve_total", platform="unknown", result="unsupported")
            raise APIError(422, "PLATFORM_UNSUPPORTED", "暂不支持该链接") from exc
        except ParseError as exc:
            await self.circuit.failure(platform_id)
            await self.metrics.increment("resolve_total", platform=platform_id, result="failed")
            message = _safe_parse_message(str(exc))
            raise APIError(502, "UPSTREAM_PARSE_FAILED", message, retryable=True) from exc

        normalized = self._normalize(result)
        for media in normalized["media"]:
            media["_proxy"] = credential.proxy
        await self.circuit.success(platform_id)
        await self.metrics.increment("resolve_total", platform=platform_id, result="success")
        await self.cache.set(key, normalized)
        return normalized

    @staticmethod
    def _with_content(value: dict[str, Any], include_content: bool) -> dict[str, Any]:
        if include_content:
            return value
        copied = {**value, "post": {**value["post"], "content": ""}}
        return copied

    @staticmethod
    def _normalize(result: Any) -> dict[str, Any]:
        media = result.media
        media_items = list(media) if isinstance(media, Sequence) else ([media] if media else [])
        normalized_media: list[dict[str, Any]] = []
        for index, item in enumerate(media_items, 1):
            kind = "unknown"
            if isinstance(item, LivePhotoRef):
                kind = "live_photo"
            elif isinstance(item, VideoRef):
                kind = "video"
            elif isinstance(item, AniRef):
                kind = "animation"
            elif isinstance(item, ImageRef):
                kind = "image"
            qualities = ResolverService._video_qualities(result, item) if kind == "video" else []
            normalized_media.append(
                {
                    "id": f"m_{index}",
                    "kind": kind,
                    "url": qualities[0]["url"] if qualities else item.url,
                    "thumbnail_url": item.thumb_url,
                    "extension": item.ext,
                    "width": item.width,
                    "height": item.height,
                    "duration": getattr(item, "duration", 0),
                    "paired_video_url": getattr(item, "video_url", None),
                    "qualities": qualities,
                    "_headers": ResolverService._media_headers(result),
                }
            )

        platform = result.platform
        return {
            "platform": {"id": platform.id, "name": platform.display_name},
            "post": {
                "type": result.type.value,
                "title": result.title,
                "content": result.content,
                "canonical_url": result.raw_url,
            },
            "media": normalized_media,
        }

    @staticmethod
    def _video_qualities(result: Any, item: Any) -> list[dict[str, Any]]:
        qualities: list[dict[str, Any]] = []
        info = getattr(getattr(result, "dl", None), "info_json", None)
        info_dict = info if isinstance(info, dict) else {}
        formats = info_dict.get("formats", [])
        seen: set[tuple[str, int]] = set()
        for fmt in formats:
            if not isinstance(fmt, dict) or not fmt.get("url"):
                continue
            if fmt.get("vcodec") in {None, "none"}:
                continue
            # Browser preview/download should contain audio; video-only DASH formats need server-side merging.
            if fmt.get("acodec") in {None, "none"}:
                continue
            height = _integer(fmt.get("height"))
            url = str(fmt["url"])
            marker = (url, height)
            if marker in seen:
                continue
            seen.add(marker)
            label = f"{height}p" if height else str(fmt.get("format_note") or fmt.get("format_id") or "可播放")
            qualities.append(
                {
                    "id": str(fmt.get("format_id") or len(qualities) + 1),
                    "label": label,
                    "url": url,
                    "width": _integer(fmt.get("width")),
                    "height": height,
                    "extension": fmt.get("ext") or "mp4",
                    "filesize": _integer(fmt.get("filesize") or fmt.get("filesize_approx")),
                    "bitrate": _integer(fmt.get("tbr")),
                    "_headers": fmt.get("http_headers") or info_dict.get("http_headers") or {},
                }
            )
        best_by_label: dict[str, dict[str, Any]] = {}
        for quality in qualities:
            current = best_by_label.get(quality["label"])
            if current is None or (quality["bitrate"], quality["filesize"] or 0) > (
                current["bitrate"],
                current["filesize"] or 0,
            ):
                best_by_label[quality["label"]] = quality
        qualities = list(best_by_label.values())
        qualities.sort(key=lambda value: (value["height"], value["bitrate"]), reverse=True)
        if not qualities:
            qualities.append(
                {
                    "id": "default",
                    "label": f'{getattr(item, "height", 0)}p' if getattr(item, "height", 0) else "默认",
                    "url": item.url,
                    "width": getattr(item, "width", 0),
                    "height": getattr(item, "height", 0),
                    "extension": getattr(item, "ext", None) or "mp4",
                    "filesize": None,
                    "bitrate": 0,
                    "_headers": ResolverService._media_headers(result),
                }
            )
        return qualities

    @staticmethod
    def _media_headers(result: Any) -> dict[str, str]:
        platform = getattr(getattr(result, "platform", None), "id", "")
        if platform == "bilibili":
            return {"Referer": "https://www.bilibili.com/"}
        if platform == "douyin":
            return {"Referer": "https://www.douyin.com/"}
        if platform == "tiktok":
            return {"Referer": "https://www.tiktok.com/"}
        return {}


def _safe_parse_message(message: str) -> str:
    """Keep useful provider context without leaking credentials embedded by legacy parsers."""
    message = re.split(r"(?:使用的)?cookie\s*[:：]", message, maxsplit=1, flags=re.IGNORECASE)[0]
    message = message.strip().rstrip(":：")
    return message or "上游解析失败"


def _integer(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
