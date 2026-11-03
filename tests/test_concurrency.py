"""Overlapping requests to one host: starts stay spaced by the delay, connections are capped."""

import asyncio
import time

import httpx
import pytest
import respx

from wn import config
from wn.collector import Cache, Collector, DailyCapReached
from wn.collector.ratelimit import RateLimiter
from wn.config import HostPolicy

HOST = "slow.test"
ROBOTS = f"https://{HOST}/robots.txt"


def page(n: int) -> str:
    return f"https://{HOST}/novel/{n}"


class Site:
    """Responses that take real time, recording when each started and how many overlapped."""

    def __init__(self, latency: float):
        self.latency = latency
        self.starts: list[float] = []
        self.inflight = 0
        self.peak = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.starts.append(time.monotonic())
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        await asyncio.sleep(self.latency)
        self.inflight -= 1
        return httpx.Response(200, text="x")


@pytest.fixture
def mock():
    with respx.mock(assert_all_called=False) as router:
        yield router


async def make(conn, tmp_path, *, connections: int) -> Collector:
    client = httpx.AsyncClient()
    collector = Collector(
        conn, Cache(conn, tmp_path / "cache"), client, limiter=RateLimiter(connections=connections)
    )
    return collector


async def test_requests_overlap_but_starts_keep_the_crawl_delay(conn, tmp_path, mock):
    mock.get(ROBOTS).respond(200, text="User-agent: *\nCrawl-delay: 0.05")
    site = Site(latency=0.3)
    for n in range(6):
        mock.get(page(n)).mock(side_effect=site)
    collector = await make(conn, tmp_path, connections=10)
    began = time.monotonic()
    async with collector._client:
        results = await asyncio.gather(*(collector.fetch(page(n)) for n in range(6)))
    elapsed = time.monotonic() - began
    assert [r.status for r in results] == [200] * 6
    assert site.peak > 1  # they really did overlap
    gaps = [b - a for a, b in zip(sorted(site.starts), sorted(site.starts)[1:], strict=False)]
    assert min(gaps) >= 0.045  # request start to request start, whatever the latency
    assert elapsed < 6 * 0.3  # one at a time would take 1.8 s plus the delays


async def test_connections_are_capped(conn, tmp_path, mock):
    mock.get(ROBOTS).respond(200, text="User-agent: *\nCrawl-delay: 0")
    site = Site(latency=0.1)
    for n in range(8):
        mock.get(page(n)).mock(side_effect=site)
    collector = await make(conn, tmp_path, connections=2)
    async with collector._client:
        await asyncio.gather(*(collector.fetch(page(n)) for n in range(8)))
    assert site.peak == 2


async def test_robots_txt_is_fetched_once_for_overlapping_fetches(conn, tmp_path, mock):
    robots = mock.get(ROBOTS).respond(200, text="User-agent: *\nCrawl-delay: 0")
    site = Site(latency=0.01)
    for n in range(5):
        mock.get(page(n)).mock(side_effect=site)
    collector = await make(conn, tmp_path, connections=5)
    async with collector._client:
        await asyncio.gather(*(collector.fetch(page(n)) for n in range(5)))
    assert robots.call_count == 1


async def test_daily_cap_holds_with_requests_in_flight(conn, tmp_path, mock, monkeypatch):
    monkeypatch.setitem(config.POLICIES, HOST, HostPolicy(daily_cap=4, cache_ttl=None))
    mock.get(ROBOTS).respond(200, text="User-agent: *\nCrawl-delay: 0")
    site = Site(latency=0.1)
    for n in range(8):
        mock.get(page(n)).mock(side_effect=site)
    collector = await make(conn, tmp_path, connections=8)
    async with collector._client:
        results = await asyncio.gather(
            *(collector.fetch(page(n)) for n in range(8)), return_exceptions=True
        )
    sent = sum(1 for r in results if not isinstance(r, Exception))
    assert sent == 3  # robots.txt took one of the four
    assert all(isinstance(r, DailyCapReached) for r in results if isinstance(r, Exception))
    assert len(site.starts) == 3


def test_a_hold_delays_every_request_to_the_host():
    now = [100.0]
    limiter = RateLimiter(clock=lambda: now[0])
    limiter.hold("h", 30)
    assert limiter.remaining("h", 1.0) == 30
    now[0] += 12
    assert limiter.remaining("h", 1.0) == 18
    limiter.hold("h", 5)  # a shorter hold never shortens a longer one
    assert limiter.remaining("h", 1.0) == 18
    assert limiter.remaining("other", 1.0) == 0
