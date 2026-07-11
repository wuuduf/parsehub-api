from __future__ import annotations

import asyncio
import time
from collections import Counter, defaultdict


class Metrics:
    def __init__(self) -> None:
        self.started_at = time.time()
        self._counters: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
        self._lock = asyncio.Lock()

    async def increment(self, name: str, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        async with self._lock:
            self._counters[key] += 1

    async def render(self) -> str:
        lines = [f"parsehub_uptime_seconds {int(time.time() - self.started_at)}"]
        async with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                label_text = ",".join(f'{key}="{_escape(item)}"' for key, item in labels)
                suffix = f"{{{label_text}}}" if label_text else ""
                lines.append(f"parsehub_{name}{suffix} {value}")
        return "\n".join(lines) + "\n"


class DailyQuota:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._usage: dict[str, dict[str, int]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def consume(self, identity: str, limit: int | None = None) -> tuple[bool, int]:
        effective_limit = limit or self.limit
        day = time.strftime("%Y-%m-%d", time.gmtime())
        async with self._lock:
            usage = self._usage[identity]
            current = usage.get(day, 0)
            if current >= effective_limit:
                return False, 0
            current += 1
            usage.clear()
            usage[day] = current
            return True, effective_limit - current


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
