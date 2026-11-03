"""Open a collector wired to the data folder, for the CLI and other entry points."""

from __future__ import annotations

import sqlite3
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


@asynccontextmanager
async def open_session() -> AsyncIterator[Session]:
    root = data_dir()
    conn = open_catalog(root)
    try:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
            cache = Cache(conn, root / "cache")
            yield Session(Collector(conn, cache, client), cache, conn)
    finally:
        conn.close()
