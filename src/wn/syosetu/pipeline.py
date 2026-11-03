"""Collect Syosetu novels: rankings, metadata, then sampled and analysed chapters.

Every request goes through the shared ``Collector``, so robots.txt, the per-host delay,
daily caps and the circuit breaker apply as for any other fetch. State lives in
``catalog.db``, so a run can be stopped at any point and resumed.
"""

from __future__ import annotations

import contextlib
import math
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from ..analysis.japanese import analyse_text
from ..analysis.store import compute_stats, rebuild_all, sampled_chapters, save_sample
from ..collector import Cache, Collector
from ..collector.http import CollectorError, FetchFailed
from ..config import DEFAULT_DELAY
from ..learner.excerpts import PER_NOVEL, save_excerpts
from .api import (
    NOVEL_BATCH,
    RANK_LISTS,
    ApiError,
    RankEntry,
    merge_rankings,
    novel_url,
    parse_novels,
    parse_ranking,
    rank_dates,
    rank_url,
)
from .chapter import MAX_PAGES, ParseError, chapter_url, next_chapter, parse_chapter
from .store import novel_id, save_ranking, source_id, upsert_novel

CHAPTER_HOST = "ncode.syosetu.com"
GUESS_CHAPTER_CHARS = 4000  # when the API gave no length, assume this per chapter
PARSE_FAILURES_BEFORE_STOP = 3

Progress = Callable[[str], None]


def _quiet(_: str) -> None:
    pass


@dataclass
class Pending:
    id: int
    ncode: str
    kind: str
    chapter_count: int | None
    length_chars: int | None
    have: dict[int, int]

    def pages_needed(self, target: int) -> int:
        """A rough count of the pages still to fetch to reach ``target`` characters."""
        missing = target - sum(self.have.values())
        if missing <= 0 or (self.kind == "short" and self.have):
            return 0
        if self.kind == "short":
            return 1
        average = GUESS_CHAPTER_CHARS
        if self.length_chars and self.chapter_count:
            average = max(500, self.length_chars // self.chapter_count)
        left = (self.chapter_count or 1) - len(self.have)
        return max(0, min(math.ceil(missing / average), MAX_PAGES - len(self.have), left))


@dataclass
class Estimate:
    novels: int
    pages: int
    seconds: float
    requests_left: int


def pending_novels(
    conn: sqlite3.Connection, target: int, *, deepen: bool, limit: int | None = None
) -> list[Pending]:
    """Novels that still need chapters, opened ones first, then the most popular.

    A first pass skips novels already sampled at their current update stamp, because
    nothing new can have appeared; a deepen pass only needs novels below the new target.
    """
    query = (
        "SELECT id, external_id, kind, chapter_count, length_chars FROM novel"
        " WHERE source_id = ?"
        + (
            " AND id IN (SELECT novel_id FROM sample)"
            if deepen
            else " AND (sampled_up IS NULL OR sampled_up != last_up)"
        )
        + " ORDER BY opened_at IS NULL, opened_at DESC, points DESC, id"
    )
    found = []
    for row in conn.execute(query, (source_id(conn),)).fetchall():
        have = sampled_chapters(conn, row["id"])
        pending = Pending(
            row["id"],
            row["external_id"],
            row["kind"] or "serial",
            row["chapter_count"],
            row["length_chars"],
            have,
        )
        if sum(have.values()) < target and pending.pages_needed(target) > 0:
            found.append(pending)
        if limit and len(found) == limit:
            break
    return found


def estimate(collector: Collector, conn: sqlite3.Connection, novels: list[Pending], target: int):
    pages = sum(n.pages_needed(target) for n in novels)
    plan = collector.plan(f"https://{CHAPTER_HOST}/")
    delay = plan.delay if plan.robots_known else DEFAULT_DELAY
    return Estimate(len(novels), pages, pages * delay, plan.cap_remaining)


# --- discovery -----------------------------------------------------------------------


async def _json_body(collector: Collector, url: str) -> bytes | None:
    result = await collector.fetch(url)
    return result.body if result.status == 200 else None


async def fetch_rankings(
    collector: Collector, today: date | None = None, progress: Progress = _quiet
) -> dict[str, tuple[date, list[RankEntry]]]:
    """The newest published list of each kind. An unpublished list falls back to the last."""
    today = today or datetime.now(UTC).date()
    found: dict[str, tuple[date, list[RankEntry]]] = {}
    for kind in RANK_LISTS:
        for when in rank_dates(kind, today):
            body = await _json_body(collector, rank_url(kind, when))
            entries = parse_ranking(body) if body else []
            if entries:
                found[kind] = (when, entries)
                progress(f"{kind}: {len(entries)} entries from {when}")
                break
        else:
            progress(f"{kind}: no published list found")
    return found


async def fetch_metadata(
    collector: Collector, conn: sqlite3.Connection, ncodes: list[str], progress: Progress = _quiet
) -> int:
    """Save Novel API metadata for ``ncodes``, 100 at a time. Returns how many were saved."""
    saved = 0
    for start in range(0, len(ncodes), NOVEL_BATCH):
        batch = ncodes[start : start + NOVEL_BATCH]
        body = await _json_body(collector, novel_url(batch))
        if body is None:
            raise FetchFailed("the Novel API did not answer with HTTP 200")
        for meta in parse_novels(body):
            upsert_novel(conn, meta)
            saved += 1
        progress(f"metadata: {saved} of {len(ncodes)} novels")
    return saved


async def discover(
    collector: Collector,
    conn: sqlite3.Connection,
    limit: int,
    today: date | None = None,
    progress: Progress = _quiet,
) -> list[str]:
    """Pull rankings, keep the best ``limit`` novels and save their metadata."""
    lists = await fetch_rankings(collector, today, progress)
    if not lists:
        raise ApiError("no ranking list could be fetched")
    chosen = merge_rankings({k: v[1] for k, v in lists.items()}, limit)
    await fetch_metadata(collector, conn, chosen, progress)
    wanted = set(chosen)
    for kind, (when, entries) in lists.items():
        for entry in entries:
            if entry.ncode in wanted:
                with contextlib.suppress(KeyError):  # not returned by the Novel API
                    save_ranking(conn, entry.ncode, kind, when, entry)
    return chosen


# --- sampling --------------------------------------------------------------------------


async def sample_novel(
    collector: Collector, cache: Cache, conn: sqlite3.Connection, novel: Pending, target: int
) -> int:
    """Fetch, analyse and forget chapters until the character target is met.

    Returns the number of pages fetched. A chapter's text exists only in memory and in the
    cache until it has been analysed, then the cached copy is deleted.
    """
    pages = 0
    while True:
        number = next_chapter(novel.kind, novel.chapter_count, novel.have, target)
        if number is None:
            break
        url = chapter_url(novel.ncode, number, novel.kind)
        result = await collector.fetch(url, kind="chapter")
        pages += 1
        if result.status != 200:
            break  # a missing or withdrawn chapter ends this novel's sample
        text = parse_chapter(result.body).text
        analysis = analyse_text(text)
        save_sample(conn, novel.id, number, analysis)
        save_excerpts(conn, novel.id, number, text)
        cache.delete(url)
        novel.have[number] = analysis.chars
    with conn:
        conn.execute("UPDATE novel SET sampled_up = last_up WHERE id = ?", (novel.id,))
    compute_stats(conn, novel.id)
    return pages


@dataclass
class RunResult:
    novels_done: int = 0
    pages: int = 0
    skipped: int = 0
    stopped: str | None = None


async def sample_all(
    collector: Collector,
    cache: Cache,
    conn: sqlite3.Connection,
    novels: list[Pending],
    target: int,
    progress: Progress = _quiet,
) -> RunResult:
    """Sample each novel in turn. Stops cleanly when the host says stop; resume later."""
    result = RunResult()
    parse_failures = 0
    started = time.monotonic()
    for index, novel in enumerate(novels, start=1):
        try:
            result.pages += await sample_novel(collector, cache, conn, novel, target)
        except ParseError as exc:
            parse_failures += 1
            result.skipped += 1
            progress(f"{novel.ncode}: skipped ({exc})")
            if parse_failures >= PARSE_FAILURES_BEFORE_STOP:
                result.stopped = "chapter pages no longer parse; the site layout may have changed"
                break
            continue
        except FetchFailed as exc:
            result.skipped += 1
            progress(f"{novel.ncode}: skipped ({exc})")
            continue
        except CollectorError as exc:  # robots disallow, suspended host, daily cap
            result.stopped = str(exc)
            break
        parse_failures = 0
        result.novels_done += 1
        progress(
            f"[{index}/{len(novels)}] {novel.ncode}: "
            f"{sum(novel.have.values())} chars from {len(novel.have)} chapters "
            f"({time.monotonic() - started:.0f} s elapsed)"
        )
    return result


def novels_without_excerpts(
    conn: sqlite3.Connection, limit: int | None = None
) -> list[sqlite3.Row]:
    """Sampled novels that have no test excerpts yet, opened ones first, then popular."""
    rows = conn.execute(
        "SELECT n.id, n.external_id, n.kind, MIN(s.chapter_no) AS chapter_no FROM novel n"
        " JOIN sample s ON s.novel_id = n.id"
        " WHERE n.source_id = ? AND NOT EXISTS (SELECT 1 FROM excerpt e WHERE e.novel_id = n.id)"
        " GROUP BY n.id ORDER BY n.opened_at IS NULL, n.opened_at DESC, n.points DESC, n.id",
        (source_id(conn),),
    ).fetchall()
    return rows[:limit] if limit else rows


async def fill_excerpts(
    collector: Collector,
    cache: Cache,
    conn: sqlite3.Connection,
    novels: list[sqlite3.Row],
    progress: Progress = _quiet,
) -> tuple[int, int]:
    """Fetch one chapter per novel and keep up to PER_NOVEL excerpts from it.

    Returns ``(novels filled, pages fetched)``. Stops quietly when the host says stop.
    """
    filled = pages = 0
    for index, novel in enumerate(novels, start=1):
        url = chapter_url(novel["external_id"], novel["chapter_no"], novel["kind"] or "serial")
        try:
            result = await collector.fetch(url, kind="chapter")
            pages += 1
            if result.status != 200:
                continue
            text = parse_chapter(result.body).text
            cache.delete(url)
            if save_excerpts(conn, novel["id"], novel["chapter_no"], text, want=PER_NOVEL):
                filled += 1
        except (ParseError, FetchFailed) as exc:
            progress(f"{novel['external_id']}: skipped ({exc})")
        except CollectorError as exc:
            progress(f"stopped: {exc}")
            break
        if index % 20 == 0:
            progress(f"excerpts: {index} of {len(novels)} novels")
    return filled, pages


def finish(conn: sqlite3.Connection) -> tuple[int, int]:
    """Recompute frequency ranks and every novel's statistics."""
    return rebuild_all(conn)


def mark_opened(conn: sqlite3.Connection, ncode: str, now: float | None = None) -> None:
    """Remember that a novel was opened in the UI, so ``deepen`` reads it first."""
    with conn:
        conn.execute(
            "UPDATE novel SET opened_at = ? WHERE id = ?",
            (time.time() if now is None else now, novel_id(conn, ncode)),
        )
