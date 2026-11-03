"""Open a collector wired to the data folder, for the CLI and other entry points."""

from __future__ import annotations

import sqlite3
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from ..config import USER_AGENT, data_dir
from ..db import open_catalog
from .cache import Cache
from .http import Collector


@dataclass
class Session:
    collector: Collector
    cache: Cache
    conn: sqlite3.Connection


def print_request(
    url: str, status: int | None, sent_at: float, seconds: float, error: str | None
) -> None:
    """One line on stderr per request: when it was sent, what came back, how long it took."""
    stamp = (
        time.strftime("%H:%M:%S", time.localtime(sent_at)) + f".{int(sent_at * 1000) % 1000:03d}"
    )
    result = error or status
    print(f"{stamp} GET {url} -> {result} ({seconds * 1000:.0f} ms)", file=sys.stderr, flush=True)


@asynccontextmanager
async def open_session() -> AsyncIterator[Session]:
    root = data_dir()
    conn = open_catalog(root)
    try:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
            cache = Cache(conn, root / "cache")
            yield Session(Collector(conn, cache, client, on_request=print_request), cache, conn)
    finally:
        conn.close()
