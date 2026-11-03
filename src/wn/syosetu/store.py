"""Saving Syosetu metadata and rankings in catalog.db."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import date

from .api import NovelMeta, RankEntry

SOURCE = "syosetu"


def source_id(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT id FROM source WHERE name = ?", (SOURCE,)).fetchone()[0]


def upsert_novel(conn: sqlite3.Connection, meta: NovelMeta, now: float | None = None) -> int:
    """Insert or refresh one novel's metadata and return its id.

    ``sampled_up`` is left alone, so a changed ``last_up`` marks the novel for re-sampling.
    """
    conn.execute(
        "INSERT INTO novel (source_id, external_id, title, author, url, genre, synopsis,"
        " length_chars, chapter_count, status, fetched_at, keywords, kind, is_r15, points,"
        " bookmarks, site_dialogue_pct, first_up, last_up, raw)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (source_id, external_id) DO UPDATE SET"
        " title = excluded.title, author = excluded.author, url = excluded.url,"
        " genre = excluded.genre, synopsis = excluded.synopsis,"
        " length_chars = excluded.length_chars, chapter_count = excluded.chapter_count,"
        " status = excluded.status, fetched_at = excluded.fetched_at,"
        " keywords = excluded.keywords, kind = excluded.kind, is_r15 = excluded.is_r15,"
        " points = excluded.points, bookmarks = excluded.bookmarks,"
        " site_dialogue_pct = excluded.site_dialogue_pct, first_up = excluded.first_up,"
        " last_up = excluded.last_up, raw = excluded.raw",
        (
            source_id(conn),
            meta.ncode,
            meta.title,
            meta.author,
            meta.url,
            meta.genre,
            meta.synopsis,
            meta.length_chars,
            meta.chapter_count,
            meta.status,
            time.time() if now is None else now,
            meta.keywords,
            meta.kind,
            int(meta.is_r15),
            meta.points,
            meta.bookmarks,
            meta.site_dialogue_pct,
            meta.first_up,
            meta.last_up,
            json.dumps(meta.raw, ensure_ascii=False),
        ),
    )
    conn.commit()
    return novel_id(conn, meta.ncode)


def novel_id(conn: sqlite3.Connection, ncode: str) -> int:
    row = conn.execute(
        "SELECT id FROM novel WHERE source_id = ? AND external_id = ?", (source_id(conn), ncode)
    ).fetchone()
    if row is None:
        raise KeyError(ncode)
    return row[0]


def save_ranking(
    conn: sqlite3.Connection, ncode: str, kind: str, when: date, entry: RankEntry
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ranking (novel_id, list, date, rank, points)"
        " VALUES (?, ?, ?, ?, ?)",
        (novel_id(conn, ncode), kind, when.isoformat(), entry.rank, entry.points),
    )
    conn.commit()


def known_ncodes(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT external_id FROM novel WHERE source_id = ?", (source_id(conn),))
    return {r[0] for r in rows}
