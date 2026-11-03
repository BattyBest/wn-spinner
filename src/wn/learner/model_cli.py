"""``wn model ...``: checks on the learner model."""

from __future__ import annotations

import typer

from .. import lang as languages
from ..config import data_dir
from ..db import open_catalog, open_profile
from . import bench as b

app = typer.Typer(no_args_is_help=True, help="Checks on the learner model.")


@app.command()
def bench(
    learners: int = typer.Option(100, min=5, help="Simulated learners to test."),
    seed: int = typer.Option(1, help="Random seed."),
) -> None:
    """Score the model on simulated learners whose vocabulary is known (takes a few minutes)."""
    typer.echo(b.compare(learners, seed))


@app.command()
def check(
    lang: str = typer.Option("ja", "--lang", help="Language: ja or zh."),
) -> None:
    """Hold out your own test answers and marked words and see how well the model predicts them."""
    if lang not in languages.CODES:
        raise typer.BadParameter("language must be ja or zh")
    root = data_dir()
    typer.echo(b.check(open_profile(root), open_catalog(root), lang))
