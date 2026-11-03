"""Per-request access to the learner model, with the slow parts cached on the app.

The lexicon (every lemma's rank and domain weights), the test word pool and each novel's
predicted coverage are rebuilt only when the data they depend on changes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from fastapi import Request

from ..db import open_catalog, open_profile
from ..learner.coverage import NovelFit, novel_fits
from ..learner.model import Learner, Lexicon, load_fixes, load_params, load_status
from ..learner.placement import Pool


@dataclass
class Context:
    profile: sqlite3.Connection
    catalog: sqlite3.Connection
    learner: Learner
    request: Request
    lang: str = "ja"

    def close(self) -> None:
        self.profile.close()
        self.catalog.close()

    @property
    def tested(self) -> bool:
        return self.learner.params.answers > 0

    def pool(self) -> Pool:
        key = (f"pool:{self.lang}", _catalog_stamp(self.catalog))
        return _cached(self.request, key, lambda: Pool.load(self.catalog, self.lang))

    def fits(self) -> dict[int, NovelFit]:
        """Predicted coverage for every analysed novel, cached until the model changes."""
        row = self.profile.execute(
            "SELECT fitted_at FROM model WHERE language = ?", (self.lang,)
        ).fetchone()
        status = self.profile.execute(
            "SELECT COUNT(*), MAX(at) FROM word_status WHERE language = ?", (self.lang,)
        ).fetchone()
        key = (
            f"fits:{self.lang}",
            _catalog_stamp(self.catalog),
            row[0] if row else None,
            tuple(status),
            _fixes_stamp(self.profile, self.lang),
        )
        return _cached(self.request, key, lambda: novel_fits(self.catalog, self.learner))


def _catalog_stamp(catalog: sqlite3.Connection) -> tuple:
    row = catalog.execute(
        "SELECT (SELECT MAX(analysed_at) FROM novel_stats),"
        " (SELECT COUNT(*) FROM novel_stats),"
        " (SELECT COUNT(*) FROM lemma_domain),"
        " (SELECT MAX(loaded_at) FROM dict_meta),"
        " (SELECT COUNT(*) FROM excerpt)"
    ).fetchone()
    return tuple(row)


def _fixes_stamp(profile: sqlite3.Connection, lang: str) -> tuple:
    row = profile.execute(
        "SELECT COUNT(*), SUM(action = 'add') FROM domain_fix WHERE language = ?", (lang,)
    ).fetchone()
    return tuple(row)


def _cached(request: Request, key: tuple, build):
    cache: dict = request.app.state.cache
    kind = key[0]
    held = cache.get(kind)
    if held is not None and held[0] == key:
        return held[1]
    value = build()
    cache[kind] = (key, value)
    return value


def open_context(request: Request, lang: str = "ja") -> Context:
    root = request.app.state.data_dir
    catalog = open_catalog(root)
    profile = open_profile(root)
    key = (f"lexicon:{lang}", _catalog_stamp(catalog), _fixes_stamp(profile, lang))
    lexicon: Lexicon = _cached(
        request, key, lambda: Lexicon.load(catalog, load_fixes(profile, lang), lang)
    )
    learner = Learner(load_params(profile, lang), lexicon, load_status(profile, lang))
    return Context(profile, catalog, learner, request, lang)
