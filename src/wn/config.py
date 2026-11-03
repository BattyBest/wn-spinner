"""Settings shared by the collector, the CLI and the API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROBOTS_TOKEN = "wn-spinner"
USER_AGENT = "wn-spinner/0.1 (personal reading tool; +https://github.com/BattyBest/wn-spinner)"

DAY = 24 * 60 * 60


@dataclass(frozen=True)
class HostPolicy:
    """How politely to treat one host."""

    min_delay: float  # seconds between requests
    daily_cap: int  # network requests per UTC day
    cache_ttl: float | None  # seconds; None keeps a page until it is purged


POLICIES: dict[str, HostPolicy] = {
    "api.syosetu.com": HostPolicy(min_delay=1.0, daily_cap=2000, cache_ttl=DAY),
    "ncode.syosetu.com": HostPolicy(min_delay=2.5, daily_cap=3000, cache_ttl=None),
    "yomou.syosetu.com": HostPolicy(min_delay=2.5, daily_cap=500, cache_ttl=DAY),
    "www.jjwxc.net": HostPolicy(min_delay=2.5, daily_cap=1000, cache_ttl=DAY),
}
DEFAULT_POLICY = HostPolicy(min_delay=5.0, daily_cap=100, cache_ttl=DAY)

# robots.txt files are re-fetched at most once a day.
ROBOTS_TTL = DAY


def policy_for(host: str) -> HostPolicy:
    return POLICIES.get(host.lower(), DEFAULT_POLICY)


def data_dir() -> Path:
    """Folder holding catalog.db, profile.db, the page cache and backups."""
    return Path(os.environ.get("WN_DATA_DIR", "data")).expanduser().resolve()
