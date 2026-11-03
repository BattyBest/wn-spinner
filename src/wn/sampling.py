"""The sampling loop both sources share: workers, error handling and progress.

A source supplies the novels to sample and an async function that samples one of them
(fetch chapters, analyse, save). This module runs those in parallel up to ``workers`` at a
time, skips novels whose pages fail, and stops cleanly when the host says stop (robots
disallow, a switched-off host, the daily cap) or when pages stop parsing, which means the
site's layout has probably changed. Resume later by running the same command.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .collector import Cache, Collector
from .collector.http import CollectorError, FetchFailed
from .config import MAX_CONNECTIONS
from .learner.excerpts import PER_NOVEL, save_excerpts

PARSE_FAILURES_BEFORE_STOP = 3

Progress = Callable[[str], None]


def quiet(_: str) -> None:
    pass


class ParseError(Exception):
    """A page has no content we recognise. Fail loudly rather than return nothing."""


class Sampled(Protocol):
    """What the loop needs to know about a novel to report on it."""

    ncode: str
    have: dict[int, int]


@dataclass
class RunResult:
    novels_done: int = 0
    pages: int = 0
    skipped: int = 0
    stopped: str | None = None


async def run_sampling[N: Sampled](
    novels: list[N],
    sample_one: Callable[[N], Awaitable[int]],
    progress: Progress = quiet,
    workers: int = MAX_CONNECTIONS,
) -> RunResult:
    """Sample the novels, up to ``workers`` at a time.

    ``sample_one`` returns the number of pages it fetched. Workers overlap their waits for
    responses, but the collector still starts requests no closer together than the host's
    delay.
    """
    result = RunResult()
    parse_failures = 0
    started = time.monotonic()
    queue = iter(novels)

    async def worker() -> None:
        nonlocal parse_failures
        for novel in queue:
            if result.stopped:
                return
            try:
                pages = await sample_one(novel)  # read after the await: workers overlap
                result.pages += pages
            except ParseError as exc:
                parse_failures += 1
                result.skipped += 1
                progress(f"{novel.ncode}: skipped ({exc})")
                if parse_failures >= PARSE_FAILURES_BEFORE_STOP:
                    result.stopped = (
                        "chapter pages no longer parse; the site layout may have changed"
                    )
                    return
                continue
            except FetchFailed as exc:
                result.skipped += 1
                progress(f"{novel.ncode}: skipped ({exc})")
                continue
            except CollectorError as exc:  # robots disallow, suspended host, daily cap
                result.stopped = result.stopped or str(exc)
                return
            parse_failures = 0
            result.novels_done += 1
            progress(
                f"[{result.novels_done + result.skipped}/{len(novels)}] {novel.ncode}: "
                f"{sum(novel.have.values())} chars from {len(novel.have)} chapters "
                f"({time.monotonic() - started:.0f} s elapsed)"
            )

    async with asyncio.TaskGroup() as group:
        for _ in range(max(1, min(workers, len(novels)))):
            group.create_task(worker())
    return result


@dataclass
class Estimate:
    novels: int
    pages: int
    seconds: float
    requests_left: int


def novels_without_excerpts(
    conn: sqlite3.Connection, source_id: int, limit: int | None = None
) -> list[sqlite3.Row]:
    """Sampled novels of a source that have no test excerpts yet, opened ones first."""
    rows = conn.execute(
        "SELECT n.id, n.external_id, n.kind, MIN(s.chapter_no) AS chapter_no FROM novel n"
        " JOIN sample s ON s.novel_id = n.id"
        " WHERE n.source_id = ? AND NOT EXISTS (SELECT 1 FROM excerpt e WHERE e.novel_id = n.id)"
        " GROUP BY n.id ORDER BY n.opened_at IS NULL, n.opened_at DESC, n.points DESC, n.id",
        (source_id,),
    ).fetchall()
    return rows[:limit] if limit else rows


async def fill_excerpts(
    collector: Collector,
    cache: Cache,
    conn: sqlite3.Connection,
    novels: list[sqlite3.Row],
    url_of: Callable[[sqlite3.Row], str],
    text_of: Callable[[bytes], str],
    progress: Progress = quiet,
) -> tuple[int, int]:
    """Fetch one chapter per novel and keep up to PER_NOVEL excerpts from it.

    ``url_of`` gives a novel's chapter URL and ``text_of`` turns the page into its text
    (raising ParseError when it can't). Returns ``(novels filled, pages fetched)``. Stops
    quietly when the host says stop.
    """
    filled = pages = 0
    for index, novel in enumerate(novels, start=1):
        url = url_of(novel)
        try:
            result = await collector.fetch(url, kind="chapter")
            pages += 1
            if result.status != 200:
                continue
            text = text_of(result.body)
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
