"""``wn syosetu ...``: collect novels from Syosetu."""

from __future__ import annotations

import asyncio

import typer

from ..collector.http import CollectorError
from ..collector.session import Session, open_session
from . import pipeline
from .api import ApiError
from .chapter import DEEP_PASS_CHARS, FIRST_PASS_CHARS

app = typer.Typer(no_args_is_help=True, help="Collect novels from Syosetu.")

_YES = typer.Option(False, "--yes", "-y", help="Start without asking first.")
_TARGET = typer.Option(FIRST_PASS_CHARS, help="Characters to read per novel in the first pass.")


def _say(message: str) -> None:
    typer.echo(message)


def _fail(message: str) -> typer.Exit:
    typer.secho(message, fg=typer.colors.RED, err=True)
    return typer.Exit(1)


def _minutes(seconds: float) -> str:
    return "under a minute" if seconds < 60 else f"about {round(seconds / 60)} min"


def _show_plan(plan: pipeline.Estimate, target: int) -> None:
    _say(f"novels to read:  {plan.novels}")
    _say(f"pages to fetch:  about {plan.pages} (target {target:,} characters each)")
    _say(f"time:            {_minutes(plan.seconds)} at the host's delay")
    _say(f"requests left:   {plan.requests_left} on ncode.syosetu.com today")


async def _sample(
    session: Session, *, target: int, deepen: bool, limit: int | None, yes: bool, dry_run: bool
) -> None:
    novels = pipeline.pending_novels(session.conn, target, deepen=deepen, limit=limit)
    if not novels:
        _say("nothing to read: every novel is at or above the target")
        return
    if not dry_run:
        await session.collector.rules(pipeline.CHAPTER_HOST)  # so the plan uses its delay
    _show_plan(pipeline.estimate(session.collector, session.conn, novels, target), target)
    if dry_run:
        return
    if not yes and not typer.confirm("Start?"):
        raise typer.Abort()
    result = await pipeline.sample_all(
        session.collector, session.cache, session.conn, novels, target, _say
    )
    ranked, scored = pipeline.finish(session.conn)
    _say(f"done: {result.novels_done} novels, {result.pages} pages, {scored} scored")
    if result.skipped:
        _say(f"{result.skipped} novels were skipped (see messages above)")
    if result.stopped:
        _say(f"stopped early: {result.stopped}")
        _say("run the same command again to carry on where it stopped")
        raise typer.Exit(2)


def _run(coro_factory) -> None:
    async def main() -> None:
        async with open_session() as session:
            await coro_factory(session)

    try:
        asyncio.run(main())
    except (CollectorError, ApiError, ValueError) as exc:
        raise _fail(str(exc)) from exc


@app.command()
def discover(limit: int = typer.Option(200, help="Novels to keep from the rankings.")) -> None:
    """Fetch the rankings and save metadata for the best novels. Reads no chapters."""

    async def go(session: Session) -> None:
        chosen = await pipeline.discover(session.collector, session.conn, limit, progress=_say)
        _say(f"saved {len(chosen)} novels")

    _run(go)


@app.command()
def sample(
    limit: int = typer.Option(None, help="Only read this many novels."),
    target: int = _TARGET,
    yes: bool = _YES,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan; send nothing."),
) -> None:
    """First pass: read chapters from novels that have none, then analyse them."""
    _run(lambda s: _sample(s, target=target, deepen=False, limit=limit, yes=yes, dry_run=dry_run))


@app.command()
def deepen(
    limit: int = typer.Option(None, help="Only read this many novels."),
    target: int = typer.Option(DEEP_PASS_CHARS, help="Characters to read per novel in total."),
    yes: bool = _YES,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan; send nothing."),
) -> None:
    """Second pass: top novels up to a bigger sample, opened ones first."""
    _run(lambda s: _sample(s, target=target, deepen=True, limit=limit, yes=yes, dry_run=dry_run))


@app.command()
def run(
    limit: int = typer.Option(200, help="Novels to keep from the rankings."),
    target: int = _TARGET,
    yes: bool = _YES,
) -> None:
    """Discover, then read and analyse: the whole first collection in one command."""

    async def go(session: Session) -> None:
        chosen = await pipeline.discover(session.collector, session.conn, limit, progress=_say)
        _say(f"saved {len(chosen)} novels; metadata is ready to browse")
        await _sample(session, target=target, deepen=False, limit=None, yes=yes, dry_run=False)

    _run(go)


@app.command()
def excerpts(
    limit: int = typer.Option(None, help="Only fill this many novels."),
    yes: bool = _YES,
) -> None:
    """Fetch one chapter for each sampled novel without test excerpts and keep up to 3."""

    async def go(session: Session) -> None:
        novels = pipeline.novels_without_excerpts(session.conn, limit)
        if not novels:
            _say("nothing to do: every sampled novel already has excerpts")
            return
        await session.collector.rules(pipeline.CHAPTER_HOST)
        plan = session.collector.plan(f"https://{pipeline.CHAPTER_HOST}/")
        seconds = len(novels) * (plan.delay if plan.robots_known else 0.5)
        _say(f"novels to fill: {len(novels)} (one page each, {_minutes(seconds)})")
        _say(f"requests left:  {plan.cap_remaining} on {pipeline.CHAPTER_HOST} today")
        if not yes and not typer.confirm("Start?"):
            raise typer.Abort()
        filled, pages = await pipeline.fill_excerpts(
            session.collector, session.cache, session.conn, novels, _say
        )
        _say(f"done: {filled} novels now have excerpts, {pages} pages fetched")

    _run(go)
