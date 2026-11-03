"""The one gate every request passes through.

Order of checks for ``Collector.fetch``: disk cache, host suspension, robots.txt,
then the per-host delay, followed by the suspension and daily-cap checks again just
before the request is sent. Requests to one host may overlap (at most ``MAX_CONNECTIONS``)
but start no closer together than the host's delay. Failures are retried with back-off; repeated
failures, or a CAPTCHA/challenge page, shut the host off until the next UTC day.
There is deliberately no way around a challenge: the collector just stops.
"""

from __future__ import annotations

import asyncio
import random
import re
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from ..config import DEFAULT_DELAY, ROBOTS_TOKEN, ROBOTS_TTL, USER_AGENT, policy_for
from .cache import Cache
from .ratelimit import RateLimiter
from .robots import RobotsRules

MAX_RETRIES = 3
MAX_REDIRECTS = 3
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
BREAKER_FAILURES = 3
RETRY_AFTER_CAP = 120.0
DAY_SECONDS = 24 * 60 * 60

# Outcomes that are real requests to the host (they count toward the daily cap).
REQUEST_OUTCOMES = ("ok", "client_error", "retry", "server_error", "network_error", "challenge")
# Outcomes of a whole fetch that mean the host is in trouble (they feed the breaker).
_FAILURE_OUTCOMES = ("server_error", "network_error")
_FETCH_OUTCOMES = ("ok", "client_error", "server_error", "network_error", "challenge")

_CHALLENGE = re.compile(
    r"captcha|cf-chl|challenge-platform|just a moment|verify you are human", re.IGNORECASE
)


# Called once per real request (each redirect hop and retry too, never for cache hits):
# url, HTTP status (None if no response came), wall-clock send time, seconds taken, error.
RequestHook = Callable[[str, int | None, float, float, str | None], None]


class CollectorError(Exception):
    pass


class RobotsDisallowed(CollectorError):
    pass


class HostSuspended(CollectorError):
    pass


class DailyCapReached(CollectorError):
    pass


class FetchFailed(CollectorError):
    pass


@dataclass
class FetchResult:
    url: str
    status: int
    body: bytes
    from_cache: bool


@dataclass
class Plan:
    """What ``fetch`` would do, worked out without sending anything."""

    url: str
    host: str
    cached: bool
    robots_known: bool
    allowed: bool | None  # None until robots.txt is known
    delay: float
    wait: float
    cap_remaining: int
    suspended: bool


def looks_like_challenge(status: int, body: bytes) -> bool:
    """Heuristic for CAPTCHA and bot-check pages: only error or small pages are checked."""
    if status < 400 and len(body) >= 5000:
        return False
    return bool(_CHALLENGE.search(body[:20000].decode("utf-8", errors="ignore")))


def _retry_after(response: httpx.Response) -> float:
    try:
        return min(float(response.headers.get("Retry-After", "")), RETRY_AFTER_CAP)
    except ValueError:
        return 0.0


class Collector:
    def __init__(
        self,
        conn: sqlite3.Connection,
        cache: Cache,
        client: httpx.AsyncClient,
        *,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wall: Callable[[], float] = time.time,
        jitter: Callable[[], float] = random.random,
        on_request: RequestHook | None = None,
    ):
        self._conn = conn
        self._cache = cache
        self._client = client
        self._limiter = limiter or RateLimiter(sleep=sleep)
        self._sleep = sleep
        self._wall = wall
        self._jitter = jitter
        self._on_request = on_request
        self._robots: dict[str, RobotsRules] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}
        self._pending: dict[str, int] = {}  # requests sent but not yet logged, per host

    # --- bookkeeping in fetch_log -------------------------------------------------

    def _day_start(self) -> float:
        now = self._wall()
        return now - now % DAY_SECONDS

    def _log(self, host: str, url: str, status: int | None, started: float | None, outcome: str):
        ms = None if started is None else int((time.monotonic() - started) * 1000)
        self._conn.execute(
            "INSERT INTO fetch_log (ts, host, url, status, ms, outcome) VALUES (?, ?, ?, ?, ?, ?)",
            (self._wall(), host, url, status, ms, outcome),
        )
        self._conn.commit()

    def requests_today(self, host: str) -> int:
        marks = ",".join("?" * len(REQUEST_OUTCOMES))
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM fetch_log WHERE host = ? AND ts >= ? AND outcome IN ({marks})",
            (host, self._day_start(), *REQUEST_OUTCOMES),
        ).fetchone()
        return row[0]

    def is_suspended(self, host: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM fetch_log WHERE host = ? AND ts >= ? AND outcome = 'tripped' LIMIT 1",
            (host, self._day_start()),
        ).fetchone()
        return row is not None

    def _trip(self, host: str, url: str) -> None:
        self._log(host, url, None, None, "tripped")

    def _breaker_open(self, host: str) -> bool:
        marks = ",".join("?" * len(_FETCH_OUTCOMES))
        rows = self._conn.execute(
            f"SELECT outcome FROM fetch_log WHERE host = ? AND ts >= ? AND outcome IN ({marks})"
            " ORDER BY id DESC LIMIT ?",
            (host, self._day_start(), *_FETCH_OUTCOMES, BREAKER_FAILURES),
        ).fetchall()
        return len(rows) == BREAKER_FAILURES and all(r[0] in _FAILURE_OUTCOMES for r in rows)

    # --- robots.txt ---------------------------------------------------------------

    def _cached_rules(self, host: str, scheme: str) -> RobotsRules | None:
        if host in self._robots:
            return self._robots[host]
        page = self._cache.get(f"{scheme}://{host}/robots.txt", ROBOTS_TTL, self._wall())
        if page is None:
            return None
        rules = (
            RobotsRules.parse(page.body.decode("utf-8", errors="replace"))
            if page.status == 200
            else RobotsRules.from_status(page.status)
        )
        self._robots[host] = rules
        return rules

    async def rules(self, host: str, scheme: str = "https") -> RobotsRules:
        """The host's robots.txt rules, fetched at most once a day."""
        known = self._cached_rules(host, scheme)
        if known is not None:
            return known
        async with self._robots_locks.setdefault(host, asyncio.Lock()):
            known = self._cached_rules(host, scheme)  # another task may have fetched it
            if known is not None:
                return known
            return await self._fetch_rules(host, scheme)

    async def _fetch_rules(self, host: str, scheme: str) -> RobotsRules:
        url = f"{scheme}://{host}/robots.txt"
        status, body = await self._network(url, "robots", host)
        if status == 200:
            rules = RobotsRules.parse(body.decode("utf-8", errors="replace"))
        else:
            try:
                rules = RobotsRules.from_status(status)
            except ValueError:
                raise RobotsDisallowed(f"{host}: robots.txt unavailable (HTTP {status})") from None
        self._cache.put(url, "robots", status, body, self._wall())
        self._robots[host] = rules
        return rules

    def _effective_delay(self, host: str, rules: RobotsRules | None) -> float:
        theirs = None if rules is None else rules.crawl_delay(ROBOTS_TOKEN)
        return DEFAULT_DELAY if theirs is None else theirs

    # --- public API ---------------------------------------------------------------

    def plan(self, url: str) -> Plan:
        parts = _split(url)
        host, policy = parts.hostname, policy_for(parts.hostname)
        rules = self._cached_rules(host, parts.scheme)
        delay = self._effective_delay(host, rules)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return Plan(
            url=url,
            host=host,
            cached=self._cache.get(url, policy.cache_ttl, self._wall()) is not None,
            robots_known=rules is not None,
            allowed=None if rules is None else rules.allowed(ROBOTS_TOKEN, path),
            delay=delay,
            wait=self._limiter.remaining(host, delay),
            cap_remaining=max(0, policy.daily_cap - self.requests_today(host)),
            suspended=self.is_suspended(host),
        )

    async def fetch(self, url: str, *, refresh: bool = False, kind: str = "page") -> FetchResult:
        parts = _split(url)
        host, policy = parts.hostname, policy_for(parts.hostname)
        if not refresh:
            page = self._cache.get(url, policy.cache_ttl, self._wall())
            if page is not None:
                return FetchResult(url, page.status, page.body, from_cache=True)
        if self.is_suspended(host):
            raise HostSuspended(f"{host} is switched off until tomorrow (UTC)")
        rules = await self.rules(host, parts.scheme)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        if not rules.allowed(ROBOTS_TOKEN, path):
            self._log(host, url, None, None, "robots_blocked")
            raise RobotsDisallowed(f"robots.txt on {host} disallows {path}")
        status, body = await self._network(url, "page", host, rules)
        if status == 200:
            self._cache.put(url, kind, status, body, self._wall())
        return FetchResult(url, status, body, from_cache=False)

    # --- the request loop ---------------------------------------------------------

    async def _network(
        self, url: str, kind: str, host: str, rules: RobotsRules | None = None
    ) -> tuple[int, bytes]:
        policy = policy_for(host)
        if rules is None:
            rules = self._robots.get(host)
        delay = self._effective_delay(host, rules)
        async with self._limiter.slot(host):
            for attempt in range(MAX_RETRIES + 1):
                await self._pace(host, delay, policy)
                started = time.monotonic()
                try:
                    try:
                        response, final_url = await self._get(url, host, delay, policy)
                    finally:
                        self._pending[host] -= 1
                except httpx.HTTPError as exc:
                    failure: str | None = f"network error: {type(exc).__name__}"
                    status, body, wait_more = None, b"", 0.0
                else:
                    status, body = response.status_code, response.content
                    failure, wait_more = None, 0.0
                    if looks_like_challenge(status, body):
                        self._log(host, final_url, status, started, "challenge")
                        self._trip(host, final_url)
                        raise HostSuspended(f"{host} served a bot-check page; stopping for today")
                    if status in RETRY_STATUSES:
                        failure = f"HTTP {status}"
                        wait_more = _retry_after(response)
                if failure is None:
                    outcome = "ok" if status < 400 else "client_error"
                    self._log(host, url, status, started, outcome)
                    return status, body
                if attempt < MAX_RETRIES:
                    self._log(host, url, status, started, "retry")
                    backoff = 2.0 * 2**attempt + self._jitter()
                    # Hold the whole host, not just this request: it is in trouble.
                    self._limiter.hold(host, max(backoff, wait_more))
                    continue
                self._log(
                    host,
                    url,
                    status,
                    started,
                    "network_error" if status is None else "server_error",
                )
                if self._breaker_open(host):
                    self._trip(host, url)
                raise FetchFailed(f"{host}: {failure} after {MAX_RETRIES + 1} attempts")
        raise AssertionError("unreachable")  # pragma: no cover

    async def _pace(self, host: str, delay: float, policy, *, count: bool = True) -> None:
        """Wait for this host's next start time, then claim it. Raises if the host is off.

        Requests queue here one at a time, so starts are spaced by ``delay`` however many
        are in flight. The suspension and daily-cap checks run after the wait, when
        earlier requests have finished and been logged; requests still in flight count
        toward the cap so overlapping requests cannot overshoot it.
        """
        async with self._limiter.gate(host):
            await self._limiter.wait(host, delay)
            if self.is_suspended(host):
                raise HostSuspended(f"{host} is switched off until tomorrow (UTC)")
            if self.requests_today(host) + self._pending.get(host, 0) >= policy.daily_cap:
                raise DailyCapReached(f"{host}: daily cap of {policy.daily_cap} requests reached")
            self._limiter.mark(host)
            if count:
                self._pending[host] = self._pending.get(host, 0) + 1

    def _report(
        self, url: str, status: int | None, sent_at: float, began: float, error: str | None
    ) -> None:
        if self._on_request is not None:
            self._on_request(url, status, sent_at, time.monotonic() - began, error)

    async def _get(self, url: str, host: str, delay: float, policy) -> tuple[httpx.Response, str]:
        """GET with the honest User-Agent, following redirects that stay on the same host.

        The first request goes out at once: the caller has already paced it with ``_pace``.
        Every later hop is a real request too, so it waits out the host delay first.
        """
        for hop in range(MAX_REDIRECTS + 1):
            if hop:
                await self._pace(host, delay, policy, count=False)
            sent_at, began = self._wall(), time.monotonic()
            try:
                response = await self._client.get(
                    url, headers={"User-Agent": USER_AGENT}, follow_redirects=False
                )
            except httpx.HTTPError as exc:
                self._report(url, None, sent_at, began, f"{type(exc).__name__}")
                raise
            self._report(url, response.status_code, sent_at, began, None)
            location = response.headers.get("Location")
            if response.status_code in (301, 302, 303, 307, 308) and location:
                target = urljoin(url, location)
                if urlsplit(target).hostname == host:
                    url = target
                    continue
            break
        return response, url


def _split(url: str):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an http(s) URL: {url}")
    return parts
