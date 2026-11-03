from __future__ import annotations

import httpx
import pytest

from wn.collector import Cache, Collector
from wn.collector.ratelimit import RateLimiter
from wn.db import open_catalog

# Midnight UTC plus one hour, so tests never straddle a day boundary by accident.
WALL_START = 1_700_006_400.0 + 3600


class FakeClock:
    """A clock whose sleep just moves time forward, so tests run instantly."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def wall(self) -> float:
        return WALL_START + self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def conn(tmp_path):
    connection = open_catalog(tmp_path)
    yield connection
    connection.close()


@pytest.fixture
async def collector(conn, tmp_path, clock):
    limiter = RateLimiter(clock=clock.monotonic, sleep=clock.sleep)
    async with httpx.AsyncClient() as client:
        yield Collector(
            conn,
            Cache(conn, tmp_path / "cache"),
            client,
            limiter=limiter,
            sleep=clock.sleep,
            wall=clock.wall,
            jitter=lambda: 0.0,
        )


def outcomes(conn, host: str) -> list[str]:
    rows = conn.execute("SELECT outcome FROM fetch_log WHERE host = ? ORDER BY id", (host,))
    return [r[0] for r in rows]
