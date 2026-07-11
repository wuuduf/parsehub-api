from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class InMemoryRateLimiter:
    def __init__(self, requests: int, window: int) -> None:
        self.requests = requests
        self.window = window
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, identity: str) -> tuple[bool, int]:
        now = time.monotonic()
        threshold = now - self.window
        async with self._lock:
            events = self._events[identity]
            while events and events[0] <= threshold:
                events.popleft()
            if len(events) >= self.requests:
                retry_after = max(1, int(self.window - (now - events[0])))
                return False, retry_after
            events.append(now)
            return True, 0
