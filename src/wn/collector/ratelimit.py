"""Per-host pacing: requests may overlap, but their starts are spaced by the host's delay.

The gap is measured from the start of one request to the start of the next, the way
Crawl-delay is usually read: a request that takes longer than the delay is followed by
the next one straight away, and a fast one waits out only what is left. Several requests
to one host may be in flight at once (up to ``connections``), but the *starts* still go
through a single gate, so the request rate never exceeds one per delay.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from ..config import MAX_CONNECTIONS


class RateLimiter:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        connections: int = MAX_CONNECTIONS,
    ):
        if connections < 1:
            raise ValueError("connections must be at least 1")
        self._clock = clock
        self._sleep = sleep
        self._connections = connections
        self._gates: dict[str, asyncio.Lock] = {}
        self._slots: dict[str, asyncio.Semaphore] = {}
        self._last: dict[str, float] = {}
        self._hold: dict[str, float] = {}

    def gate(self, host: str) -> asyncio.Lock:
        """Held while a request waits for its start time and is marked as started."""
        return self._gates.setdefault(host, asyncio.Lock())

    def slot(self, host: str) -> asyncio.Semaphore:
        """Held for the life of a request: at most ``connections`` per host."""
        return self._slots.setdefault(host, asyncio.Semaphore(self._connections))

    def remaining(self, host: str, delay: float) -> float:
        """Seconds a request to ``host`` would have to wait right now."""
        now = self._clock()
        until = self._hold.get(host, 0.0)
        last = self._last.get(host)
        if last is not None:
            until = max(until, last + delay)
        return max(0.0, until - now)

    async def wait(self, host: str, delay: float) -> None:
        """Wait out what is left of the gap since this host's last request started.

        Call with the gate held.
        """
        pause = self.remaining(host, delay)
        if pause > 0:
            await self._sleep(pause)

    def mark(self, host: str) -> None:
        """Record that a request to ``host`` is starting now. Call just before sending."""
        self._last[host] = self._clock()

    def hold(self, host: str, seconds: float) -> None:
        """Keep every request to ``host`` from starting for ``seconds`` (back-off, Retry-After)."""
        self._hold[host] = max(self._hold.get(host, 0.0), self._clock() + seconds)
