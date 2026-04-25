from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import TypeVar

T = TypeVar("T")


class SerialRateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval_seconds = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_started_at = 0.0

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            now = monotonic()
            elapsed = now - self._last_started_at
            if self._last_started_at and elapsed < self._min_interval_seconds:
                await asyncio.sleep(self._min_interval_seconds - elapsed)
            self._last_started_at = monotonic()
            return await operation()
