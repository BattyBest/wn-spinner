"""What the model says about novels and domains: personal coverage, bands, JLPT level."""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from ..analysis.store import is_name
from . import LANGUAGE
from .domains import DOMAIN_KEYS
from .model import Learner, Params, p_know

TARGET = 0.965
BANDS = (("comfortable", 0.98), ("stretch", 0.95), ("hard", 0.90), ("too_hard", 0.0))
UNKNOWN_BELOW = 0.5  # a word counts as "probably unknown" under this chance
REPEAT_MIN = 5
JLPT_KNOWN_SHARE = 0.8
DOMAIN_WORDS = 500
DOMAIN_MIN_WORDS = 20


def band_of(coverage: float) -> str:
    for name, floor in BANDS:
        if coverage >= floor:
            return name
    return "too_hard"


@dataclass
class NovelFit:
    coverage: float
    tokens: int
    unknown_distinct: int
    unknown_repeating: int
    domain_unknown: dict[str, float] = field(default_factory=dict)  # expected unknown tokens

    @property
    def band(self) -> str:
        return band_of(self.coverage)

    def top_domains(self, count: int = 2) -> list[str]:
        ranked = sorted(self.domain_unknown.items(), key=lambda kv: -kv[1])
        return [d for d, n in ranked if n >= 1][:count]


def novel_fits(catalog: sqlite3.Connection, learner: Learner) -> dict[int, NovelFit]:
    """Predicted coverage for every analysed novel: expected known tokens over all tokens."""
    lex = learner.lexicon
    chance: dict[int, float] = {}
    known = defaultdict(float)
    total = defaultdict(int)
    distinct = defaultdict(int)
    repeating = defaultdict(int)
    domain_unknown: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    rows = catalog.execute(
        "SELECT nl.novel_id, nl.lemma_id, nl.count, nl.is_name, l.lemma, l.oov"
        " FROM novel_lemma nl JOIN lemma l ON l.id = nl.lemma_id"
        " WHERE l.language = ? AND nl.novel_id IN (SELECT novel_id FROM novel_stats)",
        (LANGUAGE,),
    )
    for row in rows:
        if is_name(row):
            continue
        lemma_id, count, novel_id = row["lemma_id"], row["count"], row["novel_id"]
        p = chance.get(lemma_id)
        if p is None:
            p = chance[lemma_id] = learner.p(lemma_id)
        total[novel_id] += count
        known[novel_id] += count * p
        if p < UNKNOWN_BELOW:
            distinct[novel_id] += 1
            if count >= REPEAT_MIN:
                repeating[novel_id] += 1
        for domain, weight in lex.weights.get(lemma_id, ()):
            domain_unknown[novel_id][domain] += count * (1 - p) * weight
    return {
        novel_id: NovelFit(
            known[novel_id] / n,
            n,
            distinct[novel_id],
            repeating[novel_id],
            dict(domain_unknown[novel_id]),
        )
        for novel_id, n in total.items()
        if n
    }


def unknown_words(
    catalog: sqlite3.Connection, learner: Learner, novel_id: int, limit: int = 20
) -> list[dict]:
    """The most frequent words in a novel you probably don't know, with reading and gloss.

    Words you have already marked (known or not) are left out; there is nothing to ask.
    """
    out = []
    rows = catalog.execute(
        "SELECT nl.lemma_id, nl.count, nl.is_name, l.lemma, l.pos, l.reading, l.gloss, l.oov,"
        " l.corpus_rank FROM novel_lemma nl JOIN lemma l ON l.id = nl.lemma_id"
        " WHERE nl.novel_id = ? ORDER BY nl.count DESC",
        (novel_id,),
    )
    for row in rows:
        if is_name(row):
            continue
        if learner.status.get(learner.lexicon.keys.get(row["lemma_id"], ("", ""))) is not None:
            continue  # already answered: marked words leave the to-mark list either way
        p = learner.p(row["lemma_id"])
        if p < UNKNOWN_BELOW:
            out.append(
                {
                    "lemma_id": row["lemma_id"],
                    "lemma": row["lemma"],
                    "pos": row["pos"],
                    "reading": row["reading"],
                    "gloss": row["gloss"],
                    "count": row["count"],
                    "rank": row["corpus_rank"],
                    "p": round(p, 3),
                }
            )
            if len(out) == limit:
                break
    return out


# --- domains and levels -----------------------------------------------------------------


def _domain_words(catalog: sqlite3.Connection, learner: Learner) -> dict[str, list[int]]:
    """Each domain's most common words (weight 0.5 or more), by how often they occur."""
    lex = learner.lexicon
    members: dict[str, list[tuple[int, int]]] = defaultdict(list)
    counts = {
        r[0]: r[1]
        for r in catalog.execute(
            "SELECT id, corpus_count FROM lemma WHERE language = ? AND corpus_rank IS NOT NULL",
            (LANGUAGE,),
        )
    }
    for lemma_id, weights in lex.weights.items():
        if lemma_id in lex.function or lemma_id not in counts:
            continue
        for domain, weight in weights:
            if weight >= 0.5:
                members[domain].append((counts[lemma_id], lemma_id))
    return {
        d: [lid for _, lid in sorted(pairs, reverse=True)[:DOMAIN_WORDS]]
        for d, pairs in members.items()
    }


def domain_strengths(catalog: sqlite3.Connection, learner: Learner) -> list[dict]:
    """Per domain: the share of its common words you are expected to know, with a range.

    The range moves only the domain's own offset by one standard deviation each way; it does
    not include the uncertainty of general ability.
    """
    names = {
        r["key"]: (r["name_en"], r["name_ja"])
        for r in catalog.execute("SELECT key, name_en, name_ja FROM domain")
    }
    words = _domain_words(catalog, learner)
    params = learner.params
    out = []
    for key in DOMAIN_KEYS:
        ids = words.get(key, [])
        entry = {
            "key": key,
            "name_en": names.get(key, (key, key))[0],
            "name_ja": names.get(key, (key, key))[1],
            "delta": params.deltas[key],
            "delta_sd": params.delta_sds[key],
            "words": len(ids),
            "share": None,
            "low": None,
            "high": None,
        }
        if len(ids) >= DOMAIN_MIN_WORDS:

            def share(shift: float, ids=ids, key=key) -> float:
                shifted = Params(
                    theta=params.theta, deltas={**params.deltas, key: params.deltas[key] + shift}
                )
                lex = learner.lexicon
                return sum(
                    p_know(shifted, lex.rank_of(i), lex.weights.get(i, [])) for i in ids
                ) / len(ids)

            entry["share"] = share(0.0)
            entry["low"] = share(-params.delta_sds[key])
            entry["high"] = share(params.delta_sds[key])
        out.append(entry)
    return out


def weakest_domain(strengths: list[dict]) -> str | None:
    """The domain with the lowest share known, among those the test has some evidence on."""
    from .model import DELTA_PRIOR_SD

    tested = [
        s for s in strengths if s["share"] is not None and s["delta_sd"] < 0.95 * DELTA_PRIOR_SD
    ]
    return min(tested, key=lambda s: s["share"])["key"] if tested else None


def jlpt_estimate(catalog: sqlite3.Connection, learner: Learner) -> dict:
    """Share of each JLPT list you are expected to know, over the words the catalog has seen.

    The estimate is the hardest level where at least 80% are known. Words the catalog has
    never met are left out, so each level also reports how many of its words were checked.
    """
    lex = learner.lexicon
    best_rank: dict[str, int] = {}
    for lemma_id, (lemma, _pos) in lex.keys.items():
        rank = lex.rank.get(lemma_id)
        if rank and (lemma not in best_rank or rank < lex.rank[best_rank[lemma]]):
            best_rank[lemma] = lemma_id
    levels = []
    for level in (5, 4, 3, 2, 1):
        words = [
            r[0] for r in catalog.execute("SELECT lemma FROM jlpt_word WHERE level = ?", (level,))
        ]
        ids = [best_rank[w] for w in set(words) if w in best_rank]
        share = sum(learner.p(i) for i in ids) / len(ids) if ids else None
        levels.append(
            {"level": level, "total": len(set(words)), "checked": len(ids), "share": share}
        )
    reached = [
        e["level"] for e in levels if e["share"] is not None and e["share"] >= JLPT_KNOWN_SHARE
    ]
    estimate = min(reached) if reached else None
    loaded = any(e["total"] for e in levels)
    return {"loaded": loaded, "estimate": estimate, "levels": levels}


def vocabulary_size(params: Params) -> int:
    return round(math.exp(params.theta))
