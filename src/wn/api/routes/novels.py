"""Read-only catalog routes, plus a note that a novel was opened.

Collection itself stays a command-line job, so the UI never starts network traffic.
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ...analysis.store import COVER_STEPS, rare_words
from ...collector.http import REQUEST_OUTCOMES
from ...config import DAY, POLICIES
from ...db import open_catalog
from ...syosetu.store import source_id

router = APIRouter()

SORTS = {
    "popularity": "n.points DESC NULLS LAST, n.id",
    "easiest": "s.cover_3k DESC NULLS LAST, n.points DESC NULLS LAST, n.id",
    "updated": "n.last_up DESC NULLS LAST, n.id",
    "length": "n.length_chars DESC NULLS LAST, n.id",
}
CARD_COLUMNS = (
    "n.id, n.external_id AS ncode, n.title, n.author, n.genre, n.kind, n.status,"
    " n.chapter_count, n.length_chars, n.is_r15, n.points, n.url, n.last_up,"
    " s.cover_1k, s.cover_3k, s.cover_10k, s.kanji_pct, s.dialogue_pct, s.sample_chars"
)


def _card(row) -> dict:
    stats = None
    if row["sample_chars"] is not None:
        stats = {
            "cover_1k": row["cover_1k"],
            "cover_3k": row["cover_3k"],
            "cover_10k": row["cover_10k"],
            "kanji_pct": row["kanji_pct"],
            "dialogue_pct": row["dialogue_pct"],
            "sample_chars": row["sample_chars"],
        }
    return {
        "id": row["id"],
        "ncode": row["ncode"],
        "title": row["title"],
        "author": row["author"],
        "genre": row["genre"],
        "kind": row["kind"],
        "status": row["status"],
        "chapter_count": row["chapter_count"],
        "length_chars": row["length_chars"],
        "is_r15": bool(row["is_r15"]),
        "points": row["points"],
        "url": row["url"],
        "last_up": row["last_up"],
        "stats": stats,
    }


@router.get("/novels")
def list_novels(
    request: Request,
    q: str | None = Query(None, description="Words in the title or author."),
    genre: str | None = None,
    min_length: int | None = Query(None, ge=0),
    max_length: int | None = Query(None, ge=0),
    completed: bool = False,
    hide_r15: bool = False,
    min_cover_3k: float | None = Query(None, ge=0, le=1),
    sort: Literal["popularity", "easiest", "updated", "length"] = "popularity",
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    where, args = ["n.source_id = ?"], [None]
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        where.append("(n.title LIKE ? OR n.author LIKE ?)")
        args += [like, like]
    if genre:
        where.append("n.genre = ?")
        args.append(genre)
    if min_length is not None:
        where.append("n.length_chars >= ?")
        args.append(min_length)
    if max_length is not None:
        where.append("n.length_chars <= ?")
        args.append(max_length)
    if completed:
        where.append("n.status = 'completed'")
    if hide_r15:
        where.append("n.is_r15 = 0")
    if min_cover_3k is not None:
        where.append("s.cover_3k >= ?")
        args.append(min_cover_3k)

    conn = open_catalog(request.app.state.data_dir)
    try:
        args[0] = source_id(conn)
        base = " FROM novel n LEFT JOIN novel_stats s ON s.novel_id = n.id WHERE " + " AND ".join(
            where
        )
        total = conn.execute("SELECT COUNT(*)" + base, args).fetchone()[0]
        rows = conn.execute(
            f"SELECT {CARD_COLUMNS}{base} ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
        return {"total": total, "limit": limit, "offset": offset, "items": [_card(r) for r in rows]}
    finally:
        conn.close()


@router.get("/novels/{novel_id}")
def get_novel(novel_id: int, request: Request) -> dict:
    conn = open_catalog(request.app.state.data_dir)
    try:
        row = conn.execute(
            f"SELECT {CARD_COLUMNS}, n.synopsis, n.keywords, n.first_up FROM novel n"
            " LEFT JOIN novel_stats s ON s.novel_id = n.id WHERE n.id = ?",
            (novel_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "no such novel")
        detail = _card(row)
        detail.update(synopsis=row["synopsis"], keywords=row["keywords"], first_up=row["first_up"])

        stats = conn.execute("SELECT * FROM novel_stats WHERE novel_id = ?", (novel_id,)).fetchone()
        if stats is None:
            detail.update(stats=None, curve=[], rare_words=[])
        else:
            detail["stats"] = {
                key: stats[key]
                for key in (
                    "sample_chars",
                    "tokens",
                    "unique_lemmas",
                    "cover_1k",
                    "cover_2k",
                    "cover_3k",
                    "cover_5k",
                    "cover_10k",
                    "sentence_len",
                    "kanji_pct",
                    "dialogue_pct",
                    "rare_load",
                )
            }
            detail["curve"] = [
                {"words": 0, "cover": 0.0},
                *({"words": n, "cover": stats[f"cover_{n // 1000}k"]} for n in COVER_STEPS),
            ]
            detail["rare_words"] = rare_words(conn, novel_id)

        ranks = conn.execute(
            "SELECT list, date, rank, points FROM ranking WHERE novel_id = ? ORDER BY date DESC",
            (novel_id,),
        ).fetchall()
        newest: dict[str, dict] = {}
        for r in ranks:
            newest.setdefault(r["list"], dict(r))
        detail["rankings"] = list(newest.values())
        detail["site_dialogue_pct"] = conn.execute(
            "SELECT site_dialogue_pct FROM novel WHERE id = ?", (novel_id,)
        ).fetchone()[0]
        return detail
    finally:
        conn.close()


@router.post("/novels/{novel_id}/open", status_code=204)
def note_opened(novel_id: int, request: Request) -> None:
    """Remember that a novel was opened, so ``wn syosetu deepen`` reads it first."""
    conn = open_catalog(request.app.state.data_dir)
    try:
        with conn:
            changed = conn.execute(
                "UPDATE novel SET opened_at = ? WHERE id = ?", (time.time(), novel_id)
            ).rowcount
        if not changed:
            raise HTTPException(404, "no such novel")
    finally:
        conn.close()


@router.get("/genres")
def list_genres(request: Request) -> list[dict]:
    conn = open_catalog(request.app.state.data_dir)
    try:
        rows = conn.execute(
            "SELECT genre, COUNT(*) AS novels FROM novel WHERE genre IS NOT NULL"
            " GROUP BY genre ORDER BY novels DESC, genre"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/collect/status")
def collect_status(request: Request) -> dict:
    conn = open_catalog(request.app.state.data_dir)
    try:
        counts = conn.execute(
            "SELECT COUNT(*) AS novels,"
            " (SELECT COUNT(DISTINCT novel_id) FROM sample) AS sampled,"
            " (SELECT COUNT(*) FROM novel_stats) AS analysed,"
            " (SELECT MAX(fetched_at) FROM sample) AS last_sample FROM novel"
        ).fetchone()
        now = time.time()
        day_start = now - now % DAY
        marks = ",".join("?" * len(REQUEST_OUTCOMES))
        hosts = []
        for host, policy in POLICIES.items():
            used = conn.execute(
                "SELECT COUNT(*) FROM fetch_log"
                f" WHERE host = ? AND ts >= ? AND outcome IN ({marks})",
                (host, day_start, *REQUEST_OUTCOMES),
            ).fetchone()[0]
            stopped = conn.execute(
                "SELECT 1 FROM fetch_log"
                " WHERE host = ? AND ts >= ? AND outcome = 'tripped' LIMIT 1",
                (host, day_start),
            ).fetchone()
            hosts.append(
                {
                    "host": host,
                    "requests_today": used,
                    "requests_left": max(0, policy.daily_cap - used),
                    "switched_off": stopped is not None,
                }
            )
        return {
            "novels": counts["novels"],
            "sampled": counts["sampled"],
            "analysed": counts["analysed"],
            "last_sample_at": counts["last_sample"],
            "hosts": [h for h in hosts if h["requests_today"] or h["host"].endswith("syosetu.com")],
        }
    finally:
        conn.close()
