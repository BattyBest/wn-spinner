"""``wn dict ...``: reference dictionaries for glosses, domains and JLPT levels."""

from __future__ import annotations

from pathlib import Path

import httpx
import typer

from ..config import data_dir
from ..db import open_catalog
from . import dictionary as d

app = typer.Typer(no_args_is_help=True, help="Reference dictionaries (JMdict, JLPT lists).")


_JMDICT = typer.Option(None, exists=True, dir_okay=False, help="A jmdict-simplified JSON.")
_JLPT = typer.Option([], exists=True, dir_okay=False, help="A JLPT word list CSV.")
_LEVEL = typer.Option(None, min=1, max=5, help="Level, for a list file with no level.")


def _fail(message: str) -> typer.Exit:
    typer.secho(message, fg=typer.colors.RED, err=True)
    return typer.Exit(1)


def _load(jmdict: Path | None, jlpt: list[Path], level: int | None) -> None:
    conn = open_catalog(data_dir())
    try:
        if jmdict:
            result = d.load_jmdict(conn, jmdict)
            typer.echo(
                f"JMdict: {result['entries']} entries, {result['forms']} written forms; "
                f"glosses added to {result['lemmas_matched']} catalog words"
            )
        if jlpt:
            count = d.load_jlpt(conn, [(p, level) for p in jlpt])
            typer.echo(f"JLPT: {count} words loaded")
    except (d.DictError, OSError) as exc:
        raise _fail(str(exc)) from exc
    finally:
        conn.close()


@app.command()
def fetch(jlpt: bool = typer.Option(True, help="Also download the JLPT lists.")) -> None:
    """Download JMdict (and the JLPT lists) into data/dicts/, then load them."""
    root = data_dir()
    try:
        with d.new_client() as client:
            jmdict = d.fetch_jmdict(root, client, typer.echo)
            lists = d.fetch_jlpt(root, client, typer.echo) if jlpt else []
    except (d.DictError, httpx.HTTPError) as exc:
        raise _fail(
            f"download failed: {exc}\nDownload the files yourself and use `wn dict load`."
        ) from exc
    _load(jmdict, [p for p, _ in lists], None)


@app.command()
def load(
    jmdict: Path = _JMDICT,
    jlpt: list[Path] = _JLPT,
    level: int = _LEVEL,
) -> None:
    """Load dictionary files you downloaded yourself."""
    if not jmdict and not jlpt:
        raise _fail("give --jmdict and/or --jlpt")
    _load(jmdict, jlpt, level)


@app.command()
def status() -> None:
    """What is loaded, and how many catalog words have a gloss."""
    conn = open_catalog(data_dir())
    try:
        info = d.status(conn)
    finally:
        conn.close()
    for name in ("jmdict", "jlpt"):
        row = info["meta"].get(name)
        typer.echo(
            f"{name:<7} "
            + (f"{row['entries']} entries from {row['source']}" if row else "not loaded")
        )
    typer.echo(f"ranked words with a gloss: {info['glossed_lemmas']} of {info['ranked_lemmas']}")
