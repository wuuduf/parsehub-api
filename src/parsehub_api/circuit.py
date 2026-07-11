from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(slots=True)
class CircuitState:
    failures: int = 0
    opened_at: float | None = None


class CircuitBreaker:
    def __init__(self, threshold: int, cooldown: int) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self._states: dict[str, CircuitState] = {}
        self._lock = asyncio.Lock()

    async def allow(self, platform: str) -> bool:
        async with self._lock:
            state = self._states.get(platform)
            if state is None or state.opened_at is None:
                return True
            if time.monotonic() - state.opened_at >= self.cooldown:
                state.opened_at = None
                state.failures = max(0, self.threshold - 1)
                return True
            return False

    async def success(self, platform: str) -> None:
        async with self._lock:
            self._states[platform] = CircuitState()

    async def failure(self, platform: str) -> None:
        async with self._lock:
            state = self._states.setdefault(platform, CircuitState())
            state.failures += 1
            if state.failures >= self.threshold:
                state.opened_at = time.monotonic()

    async def snapshot(self) -> dict[str, str]:
        async with self._lock:
            return {
                platform: "open" if state.opened_at is not None else "closed"
                for platform, state in self._states.items()
            }
