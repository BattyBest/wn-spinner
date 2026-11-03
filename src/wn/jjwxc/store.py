"""Saving jjwxc metadata and rankings in catalog.db."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import date

from .pages import BookMeta, RankEntry

SOURCE = "jjwxc"


def source_id(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT id FROM source WHERE name = ?", (SOURCE,)).fetchone()[0]


def upsert_book(conn: sqlite3.Connection, meta: BookMeta, now: float | None = None) -> int:
    """Insert or refresh one book's metadata and return its id.

    ``sampled_up`` is left alone, so a changed ``last_up`` marks the book for re-sampling.
    ``raw`` keeps the free chapters (chapter id and length), so sampling needs no second
    look at the book page.
    """
    raw = {"free": [[c.chapter_id, c.words] for c in meta.free]}
    conn.execute(
        "INSERT INTO novel (source_id, external_id, title, author, url, genre, synopsis,"
        " length_chars, chapter_count, status, fetched_at, keywords, kind, is_mature, points,"
        " favourites, last_up, raw)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'serial', ?, ?, ?, ?, ?)"
        " ON CONFLICT (source_id, external_id) DO UPDATE SET"
        " title = excluded.title, author = excluded.author, url = excluded.url,"
        " genre = excluded.genre, synopsis = excluded.synopsis,"
        " length_chars = excluded.length_chars, chapter_count = excluded.chapter_count,"
        " status = excluded.status, fetched_at = excluded.fetched_at,"
        " keywords = excluded.keywords, is_mature = excluded.is_mature,"
        " points = excluded.points, favourites = excluded.favourites,"
        " last_up = excluded.last_up, raw = excluded.raw",
        (
            source_id(conn),
            meta.novel_id,
            meta.title,
            meta.author,
            meta.url,
            meta.genre,
            meta.synopsis,
            meta.length_chars,
            len(meta.chapters),
            meta.status,
            time.time() if now is None else now,
            meta.keywords,
            int(meta.is_mature),
            meta.points,
            meta.favourites,
            meta.last_up,
            json.dumps(raw),
        ),
    )
    conn.commit()
    return novel_id(conn, meta.novel_id)


def novel_id(conn: sqlite3.Connection, external_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM novel WHERE source_id = ? AND external_id = ?",
        (source_id(conn), external_id),
    ).fetchone()
    if row is None:
        raise KeyError(external_id)
    return row[0]


def save_ranking(conn: sqlite3.Connection, kind: str, when: date, entry: RankEntry) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ranking (novel_id, list, date, rank, points)"
        " VALUES (?, ?, ?, ?, ?)",
        (novel_id(conn, entry.novel_id), kind, when.isoformat(), entry.rank, entry.points),
    )
    conn.commit()


def free_chapters(conn: sqlite3.Connection, novel: int) -> list[tuple[int, int | None]]:
    """``(chapter id, characters)`` for the free chapters stored with a book, in order."""
    row = conn.execute("SELECT raw FROM novel WHERE id = ?", (novel,)).fetchone()
    try:
        return [(int(c), w) for c, w in json.loads(row[0] or "{}").get("free", [])]
    except (ValueError, TypeError):
        return []
