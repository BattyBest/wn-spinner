"""Settings shared by the collector, the CLI and the API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROBOTS_TOKEN = "wn-spinner"
USER_AGENT = "wn-spinner/0.1 (personal reading tool; +https://github.com/BattyBest/wn-spinner)"

DAY = 24 * 60 * 60

# Seconds between requests to one host: the host's own robots.txt Crawl-delay when it
# sets one, otherwise this. There is no extra floor on top of what the site asks for.
DEFAULT_DELAY = 0.5


@dataclass(frozen=True)
class HostPolicy:
    """Per-host limits beyond the delay, which comes from robots.txt (see DEFAULT_DELAY)."""

    daily_cap: int  # network requests per UTC day
    cache_ttl: float | None  # seconds; None keeps a page until it is purged


POLICIES: dict[str, HostPolicy] = {
    "api.syosetu.com": HostPolicy(daily_cap=2000, cache_ttl=DAY),
    "ncode.syosetu.com": HostPolicy(daily_cap=3000, cache_ttl=None),
    "yomou.syosetu.com": HostPolicy(daily_cap=500, cache_ttl=DAY),
    "www.jjwxc.net": HostPolicy(daily_cap=1000, cache_ttl=DAY),
}
DEFAULT_POLICY = HostPolicy(daily_cap=100, cache_ttl=DAY)

# robots.txt files are re-fetched at most once a day.
ROBOTS_TTL = DAY


def policy_for(host: str) -> HostPolicy:
    return POLICIES.get(host.lower(), DEFAULT_POLICY)


def data_dir() -> Path:
    """Folder holding catalog.db, profile.db, the page cache and backups."""
    return Path(os.environ.get("WN_DATA_DIR", "data")).expanduser().resolve()
