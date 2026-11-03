"""Collect jjwxc novels: rankings, book pages, then free chapters, analysed as they arrive.

Every request goes through the shared ``Collector``, so robots.txt, the per-host delay,
daily caps and the circuit breaker apply as for any other fetch. Only free chapters are
fetched: the free list comes from the book page, and ``free_chapter_url`` refuses any
other kind of URL. State lives in ``catalog.db``, so a run can be stopped and resumed.
"""

from __future__ import annotations

import asyncio
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..analysis.chinese import analyse_text
from ..analysis.store import compute_stats, rebuild_all, sampled_chapters, save_sample
from ..collector import Cache, Collector
from ..collector.http import CollectorError, FetchFailed
from ..config import DEFAULT_DELAY, MAX_CONNECTIONS
from ..learner.excerpts import save_excerpts
from ..sampling import (
    Estimate,
    ParseError,
    Progress,
    RunResult,
    quiet,
    run_sampling,
)
from ..sampling import fill_excerpts as sampling_fill_excerpts
from ..sampling import novels_without_excerpts as sampling_novels_without_excerpts
from .pages import (
    HOST,
    RANK_LISTS,
    book_url,
    free_chapter_url,
    is_free_chapter_url,
    merge_rankings,
    parse_book,
    parse_chapter,
    parse_ranking,
    rank_url,
)
from .store import free_chapters, novel_id, save_ranking, source_id, upsert_book

FIRST_PASS_CHARS = 10_000
DEEP_PASS_CHARS = 20_000
MAX_PAGES = 12  # a safety stop per novel and run, whatever the chapters' lengths
GUESS_CHAPTER_CHARS = 3000

_quiet = quiet


@dataclass
class Pending:
    """A novel that still needs chapters, with its free chapters in reading order."""

    id: int
    ncode: str  # the jjwxc novel id; named like Syosetu's so the shared loop can report it
    free: list[tuple[int, int | None]]
    have: dict[int, int] = field(default_factory=dict)

    def next_chapter(self, target: int) -> int | None:
        """The next free chapter to fetch, or None when the sample is complete."""
        if sum(self.have.values()) >= target or len(self.have) >= MAX_PAGES:
            return None
        for chapter_id, _words in self.free:
            if chapter_id not in self.have:
                return chapter_id
        return None

    def pages_needed(self, target: int) -> int:
        """A rough count of the pages still to fetch to reach ``target`` characters."""
        missing = target - sum(self.have.values())
        left = [(c, w) for c, w in self.free if c not in self.have]
        if missing <= 0 or not left:
            return 0
        known = [w for _c, w in self.free if w]
        average = max(500, sum(known) // len(known)) if known else GUESS_CHAPTER_CHARS
        return max(0, min(math.ceil(missing / average), MAX_PAGES - len(self.have), len(left)))


def pending_novels(
    conn: sqlite3.Connection, target: int, *, deepen: bool, limit: int | None = None
) -> list[Pending]:
    """Novels that still need chapters, opened ones first, then the most popular."""
    query = (
        "SELECT id, external_id FROM novel WHERE source_id = ?"
        + (
            " AND id IN (SELECT novel_id FROM sample)"
            if deepen
            else " AND (sampled_up IS NULL OR sampled_up != last_up)"
        )
        + " ORDER BY opened_at IS NULL, opened_at DESC, points DESC, id"
    )
    found = []
    for row in conn.execute(query, (source_id(conn),)).fetchall():
        pending = Pending(
            row["id"],
            row["external_id"],
            free_chapters(conn, row["id"]),
            sampled_chapters(conn, row["id"]),
        )
        if sum(pending.have.values()) < target and pending.pages_needed(target) > 0:
            found.append(pending)
        if limit and len(found) == limit:
            break
    return found


def estimate(collector: Collector, novels: list[Pending], target: int) -> Estimate:
    pages = sum(n.pages_needed(target) for n in novels)
    plan = collector.plan(f"https://{HOST}/")
    delay = plan.delay if plan.robots_known else DEFAULT_DELAY
    return Estimate(len(novels), pages, pages * delay, plan.cap_remaining)


# --- discovery -----------------------------------------------------------------------


async def fetch_rankings(collector: Collector, progress: Progress = _quiet) -> dict[str, list]:
    found = {}
    for kind, orderstr in RANK_LISTS.items():
        result = await collector.fetch(rank_url(orderstr))
        entries = parse_ranking(result.body) if result.status == 200 else []
        if entries:
            found[kind] = entries
            progress(f"{kind}: {len(entries)} entries")
        else:
            progress(f"{kind}: no list found")
    return found


async def fetch_books(
    collector: Collector,
    conn: sqlite3.Connection,
    ids: list[str],
    progress: Progress = _quiet,
    workers: int = MAX_CONNECTIONS,
) -> int:
    """Save the book page metadata of ``ids``, several at a time. Returns how many were saved."""
    saved = 0
    stop: str | None = None
    queue = iter(ids)

    async def worker() -> None:
        nonlocal saved, stop
        for novel in queue:
            if stop:
                return
            try:
                result = await collector.fetch(book_url(novel))
                if result.status != 200:
                    progress(f"{novel}: skipped (HTTP {result.status})")
                    continue
                upsert_book(conn, parse_book(result.body, novel))
            except (ParseError, FetchFailed) as exc:
                progress(f"{novel}: skipped ({exc})")
                continue
            except CollectorError as exc:
                stop = str(exc)
                return
            saved += 1
            if saved % 20 == 0:
                progress(f"books: {saved} of {len(ids)}")

    async with asyncio.TaskGroup() as group:
        for _ in range(max(1, min(workers, len(ids)))):
            group.create_task(worker())
    if stop:
        raise CollectorError(stop)
    return saved


class DiscoverError(Exception):
    pass


async def discover(
    collector: Collector,
    conn: sqlite3.Connection,
    limit: int,
    progress: Progress = _quiet,
    today=None,
) -> list[str]:
    """Pull the ranking lists, keep the best ``limit`` books and save their metadata."""
    lists = await fetch_rankings(collector, progress)
    if not lists:
        raise DiscoverError("no ranking list could be fetched")
    chosen = merge_rankings(lists, limit)
    await fetch_books(collector, conn, chosen, progress)
    when = today or datetime.now(UTC).date()
    wanted = set(chosen)
    for kind, entries in lists.items():
        for entry in entries:
            if entry.novel_id in wanted:
                try:
                    save_ranking(conn, kind, when, entry)
                except KeyError:  # its book page was skipped
                    continue
    return chosen


# --- sampling --------------------------------------------------------------------------


async def sample_novel(
    collector: Collector, cache: Cache, conn: sqlite3.Connection, novel: Pending, target: int
) -> int:
    """Fetch, analyse and forget free chapters until the character target is met.

    Returns the number of pages fetched. A chapter's text exists only in memory and in the
    cache until it has been analysed, then the cached copy is deleted.
    """
    pages = 0
    while (chapter := novel.next_chapter(target)) is not None:
        url = free_chapter_url(novel.ncode, chapter)
        if not is_free_chapter_url(url):  # belt and braces: never request anything else
            break
        result = await collector.fetch(url, kind="chapter")
        pages += 1
        if result.status != 200:
            break  # a missing or withdrawn chapter ends this novel's sample
        text = parse_chapter(result.body)
        analysis = analyse_text(text)
        save_sample(conn, novel.id, chapter, analysis, lang="zh")
        save_excerpts(conn, novel.id, chapter, text)
        cache.delete(url)
        novel.have[chapter] = analysis.chars
    with conn:
        conn.execute("UPDATE novel SET sampled_up = last_up WHERE id = ?", (novel.id,))
    compute_stats(conn, novel.id)
    return pages


async def sample_all(
    collector: Collector,
    cache: Cache,
    conn: sqlite3.Connection,
    novels: list[Pending],
    target: int,
    progress: Progress = _quiet,
    workers: int = MAX_CONNECTIONS,
) -> RunResult:
    """Sample the novels, up to ``workers`` at a time. Stops cleanly when the host says stop."""
    return await run_sampling(
        novels,
        lambda novel: sample_novel(collector, cache, conn, novel, target),
        progress,
        workers,
    )


def novels_without_excerpts(
    conn: sqlite3.Connection, limit: int | None = None
) -> list[sqlite3.Row]:
    return sampling_novels_without_excerpts(conn, source_id(conn), limit)


async def fill_excerpts(
    collector: Collector,
    cache: Cache,
    conn: sqlite3.Connection,
    novels: list[sqlite3.Row],
    progress: Progress = _quiet,
) -> tuple[int, int]:
    """Fetch one free chapter per novel and keep up to three excerpts from it."""
    return await sampling_fill_excerpts(
        collector,
        cache,
        conn,
        novels,
        lambda n: free_chapter_url(n["external_id"], n["chapter_no"]),
        parse_chapter,
        progress,
    )


def finish(conn: sqlite3.Connection) -> tuple[int, int]:
    """Recompute frequency ranks and every novel's statistics."""
    return rebuild_all(conn, "zh")


def mark_opened(conn: sqlite3.Connection, external_id: str, now: float | None = None) -> None:
    import time

    with conn:
        conn.execute(
            "UPDATE novel SET opened_at = ? WHERE id = ?",
            (time.time() if now is None else now, novel_id(conn, external_id)),
        )
