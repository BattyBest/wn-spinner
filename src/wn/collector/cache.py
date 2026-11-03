"""Gzip files on disk, with an index in the catalog database."""

from __future__ import annotations

import gzip
import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass
class CachedPage:
    url: str
    kind: str
    status: int
    fetched_at: float
    body: bytes


class Cache:
    def __init__(self, conn: sqlite3.Connection, root: Path):
        self._conn = conn
        self._root = root

    def get(self, url: str, max_age: float | None, now: float | None = None) -> CachedPage | None:
        """Return a stored page, or None if absent or older than ``max_age`` seconds."""
        row = self._conn.execute("SELECT * FROM cache_entry WHERE url = ?", (url,)).fetchone()
        if row is None:
            return None
        now = time.time() if now is None else now
        if max_age is not None and now - row["fetched_at"] > max_age:
            return None
        path = self._root / row["path"]
        try:
            body = gzip.decompress(path.read_bytes())
        except OSError:
            return None
        return CachedPage(url, row["kind"], row["status"], row["fetched_at"], body)

    def put(self, url: str, kind: str, status: int, body: bytes, now: float | None = None) -> None:
        host = urlsplit(url).hostname or "unknown"
        digest = hashlib.sha256(url.encode()).hexdigest()
        relative = f"{host}/{digest[:2]}/{digest}.gz"
        path = self._root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(body))
        self._conn.execute(
            "INSERT OR REPLACE INTO cache_entry"
            " (url, host, kind, status, fetched_at, path, sha256, bytes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                url,
                host,
                kind,
                status,
                time.time() if now is None else now,
                relative,
                hashlib.sha256(body).hexdigest(),
                len(body),
            ),
        )
        self._conn.commit()

    def delete(self, url: str) -> bool:
        """Delete one cached page. Returns whether there was one."""
        row = self._conn.execute("SELECT path FROM cache_entry WHERE url = ?", (url,)).fetchone()
        if row is None:
            return False
        (self._root / row["path"]).unlink(missing_ok=True)
        self._conn.execute("DELETE FROM cache_entry WHERE url = ?", (url,))
        self._conn.commit()
        return True

    def stats(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT host, kind, COUNT(*) AS pages, SUM(bytes) AS bytes"
            " FROM cache_entry GROUP BY host, kind ORDER BY host, kind"
        ).fetchall()
        return [dict(r) for r in rows]

    def purge(self, kind: str | None = None) -> int:
        """Delete cached pages (all, or just one kind) and return how many."""
        query = "SELECT url, path FROM cache_entry"
        args: tuple = ()
        if kind is not None:
            query += " WHERE kind = ?"
            args = (kind,)
        rows = self._conn.execute(query, args).fetchall()
        for row in rows:
            (self._root / row["path"]).unlink(missing_ok=True)
            self._conn.execute("DELETE FROM cache_entry WHERE url = ?", (row["url"],))
        self._conn.commit()
        return len(rows)
