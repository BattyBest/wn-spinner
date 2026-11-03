"""The ``wn`` command."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import typer

from . import __version__
from .collector import Cache, Collector
from .collector.http import CollectorError
from .config import DEFAULT_DELAY, POLICIES, ROBOTS_TOKEN, USER_AGENT, data_dir, policy_for
from .db import open_catalog

app = typer.Typer(no_args_is_help=True, add_completion=False, help="wn-spinner command line.")
cache_app = typer.Typer(no_args_is_help=True, help="Inspect or clear the page cache.")
app.add_typer(cache_app, name="cache")


@asynccontextmanager
async def _collector() -> AsyncIterator[Collector]:
    root = data_dir()
    conn = open_catalog(root)
    try:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
            yield Collector(conn, Cache(conn, root / "cache"), client)
    finally:
        conn.close()


def _fail(message: str) -> typer.Exit:
    typer.secho(message, fg=typer.colors.RED, err=True)
    return typer.Exit(1)


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command()
def fetch(
    url: str,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan; send nothing."),
    refresh: bool = typer.Option(False, "--refresh", help="Ignore the cache."),
    show: bool = typer.Option(False, "--show", help="Print the page body."),
) -> None:
    """Fetch one page politely (robots.txt, rate limit, cache)."""

    async def run() -> None:
        async with _collector() as collector:
            if dry_run:
                plan = collector.plan(url)
                typer.echo(f"host:        {plan.host}")
                typer.echo(f"cached:      {'yes' if plan.cached else 'no'}")
                if plan.robots_known:
                    typer.echo(f"robots.txt:  {'allowed' if plan.allowed else 'DISALLOWED'}")
                else:
                    typer.echo("robots.txt:  not cached; it would be fetched first")
                typer.echo(f"delay:       {plan.delay:g} s between requests")
                typer.echo(f"wait now:    {plan.wait:.1f} s")
                typer.echo(f"daily cap:   {plan.cap_remaining} requests left today")
                if plan.suspended:
                    typer.echo("host is switched off until tomorrow (UTC)")
                return
            result = await collector.fetch(url, refresh=refresh)
            source = "cache" if result.from_cache else "network"
            typer.echo(f"{result.status} {url} ({len(result.body)} bytes, {source})")
            if show:
                typer.echo(result.body.decode("utf-8", errors="replace"))

    try:
        asyncio.run(run())
    except (CollectorError, ValueError) as exc:
        raise _fail(str(exc)) from exc


@app.command()
def robots(
    host: str,
    path: str = typer.Option("/", help="Path to test against the rules."),
) -> None:
    """Show what a host's robots.txt allows and the delay we will use."""

    async def run() -> None:
        async with _collector() as collector:
            rules = await collector.rules(host)
            policy = policy_for(host)
            theirs = rules.crawl_delay(ROBOTS_TOKEN)
            typer.echo(f"host:           {host}")
            typer.echo(f"agent token:    {ROBOTS_TOKEN}")
            verdict = "allowed" if rules.allowed(ROBOTS_TOKEN, path) else "DISALLOWED"
            typer.echo(f"{path}: {verdict}")
            typer.echo(f"rules for us:   {rules.rule_count(ROBOTS_TOKEN)}")
            typer.echo(f"their delay:    {'none' if theirs is None else f'{theirs:g} s'}")
            typer.echo(f"our default:    {DEFAULT_DELAY:g} s (used when robots.txt sets none)")
            typer.echo(f"delay in force: {DEFAULT_DELAY if theirs is None else theirs:g} s")
            known = "configured" if host in POLICIES else "default"
            typer.echo(f"daily cap:      {policy.daily_cap} requests ({known} policy)")

    try:
        asyncio.run(run())
    except (CollectorError, ValueError) as exc:
        raise _fail(str(exc)) from exc


@cache_app.command("stats")
def cache_stats() -> None:
    """Count cached pages and bytes per host and kind."""
    root = data_dir()
    conn = open_catalog(root)
    try:
        rows = Cache(conn, root / "cache").stats()
    finally:
        conn.close()
    if not rows:
        typer.echo("cache is empty")
    for row in rows:
        typer.echo(
            f"{row['host']:<24} {row['kind']:<8} {row['pages']:>6} pages {row['bytes']:>10} bytes"
        )


@cache_app.command("purge")
def cache_purge(
    kind: str = typer.Option(None, help="Only this kind, e.g. chapter, page or robots."),
) -> None:
    """Delete cached pages. Raw chapter text should be purged once analysed."""
    root = data_dir()
    conn = open_catalog(root)
    try:
        removed = Cache(conn, root / "cache").purge(kind)
    finally:
        conn.close()
    typer.echo(f"removed {removed} cached pages")


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = typer.Option(False, "--reload", help="Restart on code changes."),
) -> None:
    """Run the local API and the web UI."""
    import uvicorn

    uvicorn.run("wn.api.app:create_app", factory=True, host=host, port=port, reload=reload)
