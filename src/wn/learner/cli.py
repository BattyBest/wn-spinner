"""``wn dict ...``: reference dictionaries for glosses, domains and JLPT or HSK levels."""

from __future__ import annotations

from pathlib import Path

import httpx
import typer

from .. import lang as languages
from ..config import data_dir
from ..db import open_catalog
from . import dictionary as d

app = typer.Typer(
    no_args_is_help=True,
    help="Reference dictionaries (JMdict and JLPT lists, CC-CEDICT and HSK lists).",
)


_JMDICT = typer.Option(None, exists=True, dir_okay=False, help="A jmdict-simplified JSON.")
_JLPT = typer.Option([], exists=True, dir_okay=False, help="A JLPT word list CSV.")
_LEVEL = typer.Option(None, min=1, max=5, help="Level, for a JLPT list file with no level.")
_CEDICT = typer.Option(None, exists=True, dir_okay=False, help="CC-CEDICT (.zip, .gz or text).")
_HSK = typer.Option(None, exists=True, dir_okay=False, help="complete.json from the HSK project.")
_LANG = typer.Option("ja", "--lang", help="Language: ja or zh.")


def _fail(message: str) -> typer.Exit:
    typer.secho(message, fg=typer.colors.RED, err=True)
    return typer.Exit(1)


def _check(lang: str) -> None:
    if lang not in languages.CODES:
        raise _fail(f"--lang must be one of: {', '.join(languages.CODES)}")


def _load(
    jmdict: Path | None,
    jlpt: list[Path],
    level: int | None,
    cedict: Path | None = None,
    hsk: Path | None = None,
) -> None:
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
        if cedict:
            result = d.load_cedict(conn, cedict)
            typer.echo(
                f"CC-CEDICT: {result['entries']} entries, {result['forms']} written forms; "
                f"glosses and pinyin added to {result['lemmas_matched']} catalog words"
            )
        if hsk:
            typer.echo(f"HSK: {d.load_hsk(conn, hsk)} words loaded")
    except (d.DictError, OSError) as exc:
        raise _fail(str(exc)) from exc
    finally:
        conn.close()


@app.command()
def fetch(
    lang: str = _LANG,
    levels: bool = typer.Option(
        True, "--levels/--no-levels", help="Also download the level lists."
    ),
) -> None:
    """Download a language's dictionary (and its JLPT or HSK lists) into data/dicts/, then load."""
    _check(lang)
    root = data_dir()
    try:
        with d.new_client() as client:
            if lang == "zh":
                cedict = d.fetch_cedict(root, client, typer.echo)
                hsk = d.fetch_hsk(root, client, typer.echo) if levels else None
            else:
                jmdict = d.fetch_jmdict(root, client, typer.echo)
                lists = d.fetch_jlpt(root, client, typer.echo) if levels else []
    except (d.DictError, httpx.HTTPError) as exc:
        raise _fail(
            f"download failed: {exc}\nDownload the files yourself and use `wn dict load`."
        ) from exc
    if lang == "zh":
        _load(None, [], None, cedict=cedict, hsk=hsk)
    else:
        _load(jmdict, [p for p, _ in lists], None)


@app.command()
def load(
    jmdict: Path = _JMDICT,
    jlpt: list[Path] = _JLPT,
    level: int = _LEVEL,
    cedict: Path = _CEDICT,
    hsk: Path = _HSK,
) -> None:
    """Load dictionary files you downloaded yourself."""
    if not (jmdict or jlpt or cedict or hsk):
        raise _fail("give --jmdict, --jlpt, --cedict and/or --hsk")
    _load(jmdict, jlpt, level, cedict, hsk)


@app.command()
def status() -> None:
    """What is loaded, and how many catalog words have a gloss."""
    conn = open_catalog(data_dir())
    try:
        for lang in languages.CODES:
            info = d.status(conn, lang)
            language = languages.get(lang)
            typer.echo(language.name)
            for name in (language.dictionary, language.level_name.lower()):
                row = info["meta"].get(name)
                typer.echo(
                    f"  {name:<7} "
                    + (f"{row['entries']} entries from {row['source']}" if row else "not loaded")
                )
            typer.echo(
                f"  ranked words with a gloss: {info['glossed_lemmas']} of {info['ranked_lemmas']}"
            )
    finally:
        conn.close()
