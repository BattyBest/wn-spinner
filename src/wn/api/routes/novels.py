"""Read-only catalog routes, plus a note that a novel was opened.

Collection itself stays a command-line job, so the UI never starts network traffic.
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ... import lang as languages
from ...analysis.store import COVER_STEPS, rare_words
from ...collector.http import REQUEST_OUTCOMES
from ...config import DAY, POLICIES
from ...db import open_catalog
from ...learner.coverage import (
    TARGET,
    NovelFit,
    domain_strengths,
    unknown_words,
    weakest_domain,
)
from ..personal import open_context

router = APIRouter()

Lang = Literal["ja", "zh"]

SORTS = {
    "popularity": "n.points DESC NULLS LAST, n.id",
    "easiest": "s.cover_3k DESC NULLS LAST, n.points DESC NULLS LAST, n.id",
    "updated": "n.last_up DESC NULLS LAST, n.id",
    "length": "n.length_chars DESC NULLS LAST, n.id",
}
CARD_COLUMNS = (
    "n.id, n.external_id AS ncode, n.title, n.author, n.genre, n.kind, n.status,"
    " n.chapter_count, n.length_chars, n.is_r15, n.is_mature, n.points, n.favourites, n.url,"
    " n.last_up, s.cover_1k, s.cover_3k, s.cover_10k, s.kanji_pct, s.idiom_rate,"
    " s.dialogue_pct, s.sample_chars"
)


def _personal(fit: NovelFit | None) -> dict | None:
    if fit is None:
        return None
    return {
        "coverage": fit.coverage,
        "band": fit.band,
        "unknown_distinct": fit.unknown_distinct,
        "unknown_repeating": fit.unknown_repeating,
        "top_domains": fit.top_domains(),
    }


def _card(row) -> dict:
    stats = None
    if row["sample_chars"] is not None:
        stats = {
            "cover_1k": row["cover_1k"],
            "cover_3k": row["cover_3k"],
            "cover_10k": row["cover_10k"],
            "kanji_pct": row["kanji_pct"],
            "idiom_rate": row["idiom_rate"],
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
        "is_mature": bool(row["is_mature"]),
        "points": row["points"],
        "favourites": row["favourites"],
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
    hide_r15: bool = Query(False, description="Hide R15 (Syosetu) and Mature (jjwxc) works."),
    lang: Lang = "ja",
    min_cover_3k: float | None = Query(None, ge=0, le=1),
    sort: Literal["popularity", "easiest", "updated", "length", "best"] = "popularity",
    band: Literal["comfortable", "stretch", "hard", "too_hard"] | None = None,
    w_fit: float | None = Query(None, ge=0, le=100, description="Closeness to your level."),
    w_ease: float | None = Query(None, ge=0, le=100, description="Top-3,000-word coverage."),
    w_popularity: float | None = Query(None, ge=0, le=100),
    w_recent: float | None = Query(None, ge=0, le=100, description="Recently updated."),
    w_length: float | None = Query(None, ge=0, le=100, description="Longer novels."),
    w_completed: float | None = Query(None, ge=0, le=100),
    w_grow: float | None = Query(
        None, ge=0, le=100, description="Percent of slots for growth picks."
    ),
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    where = ["n.source_id IN (SELECT id FROM source WHERE language = ?)"]
    args: list = [lang]
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
        where.append("n.is_r15 = 0 AND n.is_mature = 0")
    if min_cover_3k is not None:
        where.append("s.cover_3k >= ?")
        args.append(min_cover_3k)

    ctx = open_context(request, lang)
    conn = ctx.catalog
    try:
        base = " FROM novel n LEFT JOIN novel_stats s ON s.novel_id = n.id WHERE " + " AND ".join(
            where
        )
        fits = ctx.fits() if ctx.tested else {}
        given = {
            "fit": w_fit,
            "ease": w_ease,
            "popularity": w_popularity,
            "recent": w_recent,
            "length": w_length,
            "completed": w_completed,
            "grow": w_grow,
        }
        # Any slider value means a custom mix; otherwise the named sort is a preset.
        custom = {k: v for k, v in given.items() if v is not None}
        weights = custom or PRESETS[sort]
        needs_test = any(weights.get(k, 0) > 0 for k in NEEDS_TEST) or band
        if needs_test and not fits:
            raise HTTPException(409, "take the placement test first")
        if custom or sort == "best" or band:
            rows = conn.execute(
                f"SELECT {CARD_COLUMNS}{base} ORDER BY {SORTS['popularity']}", args
            ).fetchall()
            ordered = _rank_for_me(ctx, rows, fits, band, weights=weights)
            page = ordered[offset : offset + limit]
            items = []
            for row, grow in page:
                card = _card(row)
                me = _personal(fits.get(row["id"]))
                card["me"] = {**me, "grow": grow} if me else None
                items.append(card)
            return {"total": len(ordered), "limit": limit, "offset": offset, "items": items}
        total = conn.execute("SELECT COUNT(*)" + base, args).fetchone()[0]
        rows = conn.execute(
            f"SELECT {CARD_COLUMNS}{base} ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
        items = []
        for r in rows:
            card = _card(r)
            card["me"] = _personal(fits.get(r["id"]))
            items.append(card)
        return {"total": total, "limit": limit, "offset": offset, "items": items}
    finally:
        ctx.close()


# How much each thing counts when ranking, 0 to 100 each. `grow` is the share of slots (percent)
# given to words from your weakest domain; the others are summed as weight x a 0..1 factor.
WEIGHT_KEYS = ("fit", "ease", "popularity", "recent", "length", "completed", "grow")
PRESETS: dict[str, dict[str, float]] = {
    "best": {"fit": 100, "popularity": 1, "completed": 0.5, "grow": 20},
    "popularity": {"popularity": 100},
    "easiest": {"ease": 100, "popularity": 1},
    "updated": {"recent": 100},
    "length": {"length": 100},
}
NEEDS_TEST = ("fit", "grow")


def _percentiles(values: list) -> list[float]:
    """Each value's place in the sorted list, 0 (lowest) to 1 (highest); None counts lowest."""
    order = sorted(range(len(values)), key=lambda i: (values[i] is not None, values[i] or 0))
    out = [0.0] * len(values)
    for place, i in enumerate(order):
        out[i] = place / (len(values) - 1) if len(values) > 1 else 1.0
    return out


def _rank_for_me(
    ctx, rows, fits, band, best: bool = False, weights: dict[str, float] | None = None
) -> list[tuple]:
    """Order novels by the weights. Returns ``(row, is_grow_pick)`` pairs.

    Rows come in popularity order, which settles ties. ``best=True`` uses the "best" preset.
    """
    w = {k: 0.0 for k in WEIGHT_KEYS}
    w.update(PRESETS["best"] if best and weights is None else weights or {})
    personal = w["fit"] > 0 or w["grow"] > 0 or bool(band)
    if personal:
        rows = [r for r in rows if r["id"] in fits and (not band or fits[r["id"]].band == band)]
    if w["fit"] > 0 and not band:
        rows = [r for r in rows if fits[r["id"]].band != "too_hard"]
    top = max((r["points"] or 0 for r in rows), default=0) or 1
    recent = _percentiles([r["last_up"] for r in rows]) if w["recent"] else []
    longest = _percentiles([r["length_chars"] for r in rows]) if w["length"] else []

    def score(i: int, row) -> float:
        total = 0.0
        if w["fit"]:
            total += w["fit"] * (1 - min(1.0, abs(fits[row["id"]].coverage - TARGET)))
        if w["ease"]:
            total += w["ease"] * (row["cover_3k"] or 0)
        if w["popularity"]:
            total += w["popularity"] * (row["points"] or 0) / top
        if w["recent"]:
            total += w["recent"] * recent[i]
        if w["length"]:
            total += w["length"] * longest[i]
        if w["completed"] and row["status"] == "completed":
            total += w["completed"]
        return total

    scored = sorted(enumerate(rows), key=lambda p: -score(*p))  # stable: ties keep popularity order
    ordered = [row for _i, row in scored]
    if w["grow"] <= 0 or not fits:
        return [(r, False) for r in ordered]
    weak = weakest_domain(domain_strengths(ctx.catalog, ctx.learner))
    if weak is None:
        return [(r, False) for r in ordered]
    pool = sorted(
        (
            r
            for r in ordered
            if fits[r["id"]].band == "comfortable" and fits[r["id"]].domain_unknown.get(weak, 0) > 0
        ),
        key=lambda r: -fits[r["id"]].domain_unknown[weak] / fits[r["id"]].tokens,
    )
    grown = {r["id"] for r in pool}
    main = [r for r in ordered if r["id"] not in grown or len(pool) == 0]
    share = min(w["grow"], 100) / 100
    result: list[tuple] = []
    queue = list(pool)
    main_iter = iter(main)
    for position in range(len(ordered)):
        if int((position + 1) * share + 1e-9) > int(position * share + 1e-9) and queue:
            result.append((queue.pop(0), True))
            continue
        nxt = next(main_iter, None)
        if nxt is None:
            break
        result.append((nxt, False))
    result.extend((r, False) for r in queue)
    return result


@router.get("/novels/{novel_id}")
def get_novel(novel_id: int, request: Request) -> dict:
    peek = open_catalog(request.app.state.data_dir)
    try:
        found = peek.execute(
            "SELECT s.language, s.name FROM novel n JOIN source s ON s.id = n.source_id"
            " WHERE n.id = ?",
            (novel_id,),
        ).fetchone()
    finally:
        peek.close()
    if found is None:
        raise HTTPException(404, "no such novel")
    ctx = open_context(request, found["language"])
    conn = ctx.catalog
    try:
        row = conn.execute(
            f"SELECT {CARD_COLUMNS}, n.synopsis, n.keywords, n.first_up FROM novel n"
            " LEFT JOIN novel_stats s ON s.novel_id = n.id WHERE n.id = ?",
            (novel_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "no such novel")
        detail = _card(row)
        detail.update(
            synopsis=row["synopsis"],
            keywords=row["keywords"],
            first_up=row["first_up"],
            language=found["language"],
            source=found["name"],
        )

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
                    "idiom_rate",
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
        fit = ctx.fits().get(novel_id) if ctx.tested else None
        detail["me"] = _personal(fit)
        detail["unknown_words"] = unknown_words(conn, ctx.learner, novel_id) if fit else []
        return detail
    finally:
        ctx.close()


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
def list_genres(request: Request, lang: Lang = "ja") -> list[dict]:
    conn = open_catalog(request.app.state.data_dir)
    try:
        rows = conn.execute(
            "SELECT genre, COUNT(*) AS novels FROM novel"
            " WHERE genre IS NOT NULL AND source_id IN (SELECT id FROM source WHERE language = ?)"
            " GROUP BY genre ORDER BY novels DESC, genre",
            (lang,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/collect/status")
def collect_status(request: Request, lang: Lang = "ja") -> dict:
    conn = open_catalog(request.app.state.data_dir)
    try:
        mine = (
            "(SELECT id FROM novel WHERE source_id IN (SELECT id FROM source WHERE language = ?))"
        )
        counts = conn.execute(
            "SELECT COUNT(*) AS novels,"
            f" (SELECT COUNT(DISTINCT novel_id) FROM sample WHERE novel_id IN {mine}) AS sampled,"
            f" (SELECT COUNT(*) FROM novel_stats WHERE novel_id IN {mine}) AS analysed,"
            f" (SELECT MAX(fetched_at) FROM sample WHERE novel_id IN {mine}) AS last_sample"
            " FROM novel WHERE source_id IN (SELECT id FROM source WHERE language = ?)",
            (lang, lang, lang, lang),
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
            "hosts": [
                h for h in hosts if h["requests_today"] or h["host"] in languages.get(lang).hosts
            ],
        }
    finally:
        conn.close()
