import httpx
import pytest
import respx

from wn import config
from wn.collector import DailyCapReached, HostSuspended, RobotsDisallowed
from wn.collector.http import FetchFailed
from wn.config import USER_AGENT, HostPolicy

from .conftest import outcomes

HOST = "example.test"
ROBOTS = f"https://{HOST}/robots.txt"


def page(n: int = 1) -> str:
    return f"https://{HOST}/novel/{n}"


@pytest.fixture
def mock():
    with respx.mock(assert_all_called=False) as router:
        yield router


async def test_sends_the_honest_user_agent(collector, mock):
    mock.get(ROBOTS).respond(404)
    route = mock.get(page()).respond(200, text="hi")
    await collector.fetch(page())
    assert route.calls.last.request.headers["User-Agent"] == USER_AGENT


async def test_disallowed_path_is_never_requested(collector, conn, mock):
    mock.get(ROBOTS).respond(200, text="User-agent: *\nDisallow: /novel/")
    route = mock.get(page()).respond(200)
    with pytest.raises(RobotsDisallowed):
        await collector.fetch(page())
    assert route.call_count == 0
    assert outcomes(conn, HOST) == ["ok", "robots_blocked"]


async def test_robots_404_allows_and_403_blocks(collector, mock):
    mock.get(ROBOTS).respond(404)
    mock.get(page()).respond(200, text="ok")
    assert (await collector.fetch(page())).status == 200

    mock.get("https://closed.test/robots.txt").respond(403)
    closed = mock.get("https://closed.test/x").respond(200)
    with pytest.raises(RobotsDisallowed):
        await collector.fetch("https://closed.test/x")
    assert closed.call_count == 0


async def test_unreachable_robots_means_no_crawling(collector, mock):
    mock.get(ROBOTS).respond(500)
    route = mock.get(page()).respond(200)
    with pytest.raises(FetchFailed):
        await collector.fetch(page())
    assert route.call_count == 0


async def test_crawl_delay_from_robots_is_used(collector, clock, mock):
    mock.get(ROBOTS).respond(200, text="User-agent: *\nCrawl-delay: 10")
    mock.get(page(1)).respond(200, text="a")
    mock.get(page(2)).respond(200, text="b")
    await collector.fetch(page(1))
    await collector.fetch(page(2))
    assert clock.sleeps[-1] == 10


async def test_short_crawl_delay_is_not_padded(collector, clock, mock):
    mock.get(ROBOTS).respond(200, text="User-agent: *\nCrawl-delay: 1")
    mock.get(page(1)).respond(200, text="a")
    mock.get(page(2)).respond(200, text="b")
    await collector.fetch(page(1))
    await collector.fetch(page(2))
    assert clock.sleeps[-1] == 1  # no extra floor on top of what the site asks


async def test_default_delay_applies_when_robots_sets_none(collector, clock, mock):
    mock.get(ROBOTS).respond(404)
    mock.get(page(1)).respond(200, text="a")
    mock.get(page(2)).respond(200, text="b")
    await collector.fetch(page(1))
    await collector.fetch(page(2))
    assert clock.sleeps[-1] == 0.5


async def test_second_fetch_comes_from_the_cache(collector, mock):
    mock.get(ROBOTS).respond(404)
    route = mock.get(page()).respond(200, text="本文")
    first = await collector.fetch(page())
    second = await collector.fetch(page())
    assert (first.from_cache, second.from_cache) == (False, True)
    assert second.body.decode() == "本文"
    assert route.call_count == 1
    await collector.fetch(page(), refresh=True)
    assert route.call_count == 2


async def test_429_is_retried_after_retry_after(collector, clock, conn, mock):
    mock.get(ROBOTS).respond(404)
    route = mock.get(page()).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "30"}),
            httpx.Response(200, text="ok"),
        ]
    )
    result = await collector.fetch(page())
    assert result.status == 200 and route.call_count == 2
    assert 30 in clock.sleeps
    assert outcomes(conn, HOST) == ["client_error", "retry", "ok"]  # robots 404 first


async def test_backoff_doubles_between_attempts(collector, clock, mock):
    mock.get(ROBOTS).respond(404)
    times: list[float] = []

    def refuse(request):
        times.append(clock.monotonic())
        return httpx.Response(503)

    mock.get(page()).mock(side_effect=refuse)
    with pytest.raises(FetchFailed):
        await collector.fetch(page())
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert gaps == [2.0, 4.0, 8.0]


async def test_network_errors_are_retried(collector, mock):
    mock.get(ROBOTS).respond(404)
    route = mock.get(page()).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, text="ok")]
    )
    assert (await collector.fetch(page())).status == 200
    assert route.call_count == 2


async def test_three_failed_fetches_switch_the_host_off(collector, conn, mock):
    mock.get(ROBOTS).respond(404)
    route = mock.get(url__regex=rf"https://{HOST}/novel/\d+").respond(500)
    for n in (1, 2, 3):
        with pytest.raises(FetchFailed):
            await collector.fetch(page(n))
    assert route.call_count == 12  # three fetches, four attempts each
    with pytest.raises(HostSuspended):
        await collector.fetch(page(4))
    assert route.call_count == 12
    assert outcomes(conn, HOST)[-1] == "tripped"


async def test_a_404_does_not_count_as_host_trouble(collector, mock):
    mock.get(ROBOTS).respond(404)
    mock.get(url__regex=rf"https://{HOST}/novel/\d+").respond(404)
    for n in range(1, 6):
        assert (await collector.fetch(page(n))).status == 404
    assert not collector.is_suspended(HOST)


async def test_bot_check_page_stops_the_host_for_the_day(collector, clock, mock):
    mock.get(ROBOTS).respond(404)
    route = mock.get(page(1)).respond(403, text="<html>Please solve this CAPTCHA</html>")
    mock.get(page(2)).respond(200, text="fine")
    with pytest.raises(HostSuspended):
        await collector.fetch(page(1))
    with pytest.raises(HostSuspended):
        await collector.fetch(page(2))
    assert route.call_count == 1  # no retry, no workaround

    clock.now += 24 * 60 * 60  # next UTC day
    assert (await collector.fetch(page(2))).status == 200


async def test_daily_cap_stops_requests_and_resets_next_day(collector, clock, monkeypatch, mock):
    monkeypatch.setitem(config.POLICIES, HOST, HostPolicy(daily_cap=2, cache_ttl=None))
    mock.get(ROBOTS).respond(404)
    mock.get(page(1)).respond(200, text="a")
    mock.get(page(2)).respond(200, text="b")
    await collector.fetch(page(1))  # robots.txt was request 1, this is 2
    with pytest.raises(DailyCapReached):
        await collector.fetch(page(2))
    clock.now += 24 * 60 * 60
    assert (await collector.fetch(page(2))).status == 200


async def test_same_host_redirect_is_followed_but_cross_host_is_not(collector, mock):
    mock.get(ROBOTS).respond(404)
    mock.get(page(1)).respond(301, headers={"Location": "/novel/moved"})
    mock.get(f"https://{HOST}/novel/moved").respond(200, text="here")
    assert (await collector.fetch(page(1))).body == b"here"

    mock.get(page(2)).respond(302, headers={"Location": "https://elsewhere.test/x"})
    elsewhere = mock.get("https://elsewhere.test/x").respond(200)
    assert (await collector.fetch(page(2))).status == 302
    assert elsewhere.call_count == 0


async def test_plan_reports_without_sending(collector, mock):
    robots = mock.get(ROBOTS).respond(200, text="User-agent: *\nDisallow: /secret")
    before = collector.plan(page())
    assert not before.robots_known and before.allowed is None and not before.cached
    assert robots.call_count == 0

    mock.get(page()).respond(200, text="x")
    await collector.fetch(page())
    after = collector.plan(page())
    assert after.robots_known and after.allowed and after.cached
    assert collector.plan(f"https://{HOST}/secret").allowed is False
    assert after.cap_remaining == 100 - 2


async def test_non_http_urls_are_rejected(collector):
    with pytest.raises(ValueError):
        await collector.fetch("file:///etc/passwd")
