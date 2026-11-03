"""Per-host pacing: at most one request at a time, with a minimum gap between them."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class RateLimiter:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._clock = clock
        self._sleep = sleep
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    def lock(self, host: str) -> asyncio.Lock:
        return self._locks.setdefault(host, asyncio.Lock())

    def remaining(self, host: str, delay: float) -> float:
        """Seconds a request to ``host`` would have to wait right now."""
        last = self._last.get(host)
        if last is None:
            return 0.0
        return max(0.0, last + delay - self._clock())

    async def wait(self, host: str, delay: float) -> None:
        """Wait out the gap since this host's last request. Call with the lock held."""
        pause = self.remaining(host, delay)
        if pause > 0:
            await self._sleep(pause)

    def mark(self, host: str) -> None:
        """Record that a request to ``host`` has just finished."""
        self._last[host] = self._clock()
