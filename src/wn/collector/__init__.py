"""Polite page collection: robots.txt, rate limits, retries and a disk cache."""

from .cache import Cache
from .http import (
    Collector,
    DailyCapReached,
    FetchResult,
    HostSuspended,
    Plan,
    RobotsDisallowed,
)
from .robots import RobotsRules

__all__ = [
    "Cache",
    "Collector",
    "DailyCapReached",
    "FetchResult",
    "HostSuspended",
    "Plan",
    "RobotsDisallowed",
    "RobotsRules",
]
