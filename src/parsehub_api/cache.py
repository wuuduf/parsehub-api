from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol


class CacheProtocol(Protocol):
    ttl: int

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any) -> None: ...

    async def clear(self) -> None: ...


@dataclass(slots=True)
class CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, ttl: int) -> None:
        self.ttl = ttl
        self._items: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        now = time.monotonic()
        async with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._items.pop(key, None)
                return None
            return entry.value

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._items[key] = CacheEntry(value=value, expires_at=time.monotonic() + self.ttl)

    async def clear(self) -> None:
        async with self._lock:
            self._items.clear()
