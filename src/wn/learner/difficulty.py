"""How hard each word is, in the same units as ``ln rank``.

The catalog's own frequency rank is the best signal for words it has seen many times and
close to random for words it saw once or twice. Outside lists (JLPT level, JMdict's news
frequency bands) say roughly where a word sits for learners. This module blends them.

Every source gives an estimate of ``ln rank`` and a variance. The blend weights each by its
inverse variance, and keeps the result's variance, so the model can tell a solid difficulty
from a guess. Nothing here depends on the language: a source is just a label per word (a
JLPT level, an HSK level, a frequency band) that is mapped to a typical ``ln rank``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

# A catalog rank is trusted only from this many sightings when calibrating the other sources.
RELIABLE_SIGHTINGS = 20
MIN_CALIBRATION = 15  # words a label needs before its typical rank is learned
UNKNOWN_SD = 1.6  # a word with no evidence at all
# There are about as many words per unit of ln rank as the rank itself (rank is a running
# count), so a word's true ln rank is expected to be *above* a noisy estimate of it by the
# estimate's variance: a word seen once and ranked 5,000th is more likely to be a 12,000th word
# than a 2,000th. This is the slope of ln(words per unit ln rank) against ln rank.
DENSITY_SLOPE = 1.0


@dataclass(frozen=True)
class Noise:
    """Variance of the catalog's ln rank for a word seen n times: ``v0 + v1 / n``."""

    v0: float = 0.10
    v1: float = 1.0

    def variance(self, sightings: int) -> float:
        return self.v0 + self.v1 / max(sightings, 1)


DEFAULT_NOISE = Noise()


def fit_noise(splits: Iterable[tuple[int, float, float]]) -> Noise:
    """Fit the catalog's rank noise from ranks computed on two halves of the novels.

    Each item is ``(sightings, ln rank from one half, ln rank from the other)``. The two
    halves differ by noise only, and the full-catalog rank has about a quarter of the
    variance of their difference, so ``(a - b)^2 / 4`` estimates it. A line ``v0 + v1 / n``
    is fitted to those by least squares, kept above zero.
    """
    rows = [(1 / max(n, 1), (a - b) ** 2 / 4) for n, a, b in splits]
    if len(rows) < 30:
        return DEFAULT_NOISE
    mean_x = sum(x for x, _ in rows) / len(rows)
    mean_y = sum(y for _, y in rows) / len(rows)
    spread = sum((x - mean_x) ** 2 for x, _ in rows)
    v1 = sum((x - mean_x) * (y - mean_y) for x, y in rows) / spread if spread else 0.0
    v1 = max(v1, 0.0)
    v0 = max(mean_y - v1 * mean_x, 0.01)
    return Noise(v0, v1)


@dataclass(frozen=True)
class Source:
    """What one outside list says about a set of words."""

    name: str
    mean: dict[str, float]  # label -> typical ln rank
    variance: float  # spread of ln rank within a label


@dataclass(frozen=True)
class Estimate:
    ln_rank: float
    sd: float


def calibrate(
    name: str,
    labels: dict[int, str],
    ln_rank: dict[int, float],
    sightings: dict[int, int],
    noise: Noise = DEFAULT_NOISE,
) -> Source:
    """Learn each label's typical ln rank from the words the catalog has seen often.

    ``labels`` maps word id to its label, ``ln_rank`` and ``sightings`` come from the
    catalog. The spread inside a label includes the catalog's own small noise, which is
    subtracted so the source is not blamed for it.
    """
    groups: dict[str, list[float]] = defaultdict(list)
    noise_by_label: dict[str, list[float]] = defaultdict(list)
    for word, label in labels.items():
        n = sightings.get(word, 0)
        if word in ln_rank and n >= RELIABLE_SIGHTINGS:
            groups[label].append(ln_rank[word])
            noise_by_label[label].append(noise.variance(n))
    mean = {label: sum(v) / len(v) for label, v in groups.items() if len(v) >= MIN_CALIBRATION}
    squares = total = 0.0
    for label, values in groups.items():
        if label not in mean:
            continue
        squares += sum((x - mean[label]) ** 2 for x in values)
        total += len(values)
    spread = squares / total if total else UNKNOWN_SD**2
    average_noise = (
        sum(v for label in mean for v in noise_by_label[label]) / total if total else noise.v0
    )
    return Source(name, mean, max(spread - average_noise, 0.05))


def blend(
    catalog: tuple[float, int] | None,
    outside: Iterable[tuple[Source, str | None]],
    unknown: float,
    noise: Noise = DEFAULT_NOISE,
) -> Estimate:
    """Combine the catalog's ``(ln rank, sightings)`` with outside labels for one word.

    ``unknown`` is the ln rank to use when nothing is known (rarer than any ranked word).
    """
    weighted = total = 0.0
    if catalog is not None:
        w = 1 / noise.variance(catalog[1])
        weighted += w * catalog[0]
        total += w
    for source, label in outside:
        if label is not None and label in source.mean:
            w = 1 / source.variance
            weighted += w * source.mean[label]
            total += w
    if total == 0:
        return Estimate(unknown, UNKNOWN_SD)
    variance = 1 / total
    return Estimate(weighted / total + DENSITY_SLOPE * variance, math.sqrt(variance))


# --- the catalog's side ---------------------------------------------------------------------


def _half_ranks(conn, lang: str, novel_ids: set[int]) -> dict[int, float]:
    """ln rank of each lemma, ranked as ``rebuild_frequency`` does but over some novels."""
    from ..analysis.store import _novel_rows, is_name

    totals: dict[int, int] = defaultdict(int)
    kept = []
    for row in _novel_rows(conn, lang):
        if row["novel_id"] in novel_ids and not is_name(row, lang):
            totals[row["novel_id"]] += row["count"]
            kept.append((row["novel_id"], row["lemma_id"], row["count"]))
    score: dict[int, float] = defaultdict(float)
    for novel_id, lemma_id, n in kept:
        score[lemma_id] += n / totals[novel_id] / (len(totals) or 1)
    ordered = sorted(score, key=lambda i: (-score[i], i))
    return {lemma_id: math.log(rank) for rank, lemma_id in enumerate(ordered, start=1)}


def measure_noise(conn, lang: str, counts: dict[int, int]) -> Noise:
    """How noisy the catalog's ranks are, from ranking twice over alternate novels."""
    novels = sorted(
        {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT ns.novel_id FROM novel_stats ns JOIN novel n ON n.id = ns.novel_id"
                " JOIN source s ON s.id = n.source_id WHERE s.language = ?",
                (lang,),
            )
        }
    )
    if len(novels) < 4:
        return DEFAULT_NOISE
    first = _half_ranks(conn, lang, set(novels[0::2]))
    second = _half_ranks(conn, lang, set(novels[1::2]))
    return fit_noise(
        (counts[i], first[i], second[i]) for i in first.keys() & second.keys() if i in counts
    )


def rebuild(conn, lang: str, now: float | None = None) -> dict:
    """Recompute every lemma's blended difficulty. Run after ``rebuild_frequency``."""
    import json
    import time

    rows = conn.execute(
        "SELECT id, lemma, corpus_count, corpus_rank, is_common FROM lemma WHERE language = ?",
        (lang,),
    ).fetchall()
    ranked = [r for r in rows if r["corpus_rank"]]
    if not ranked:
        return {"words": 0, "noise": DEFAULT_NOISE, "sources": {}}
    ln_rank = {r["id"]: math.log(r["corpus_rank"]) for r in ranked}
    counts = {r["id"]: r["corpus_count"] or 0 for r in ranked}
    top = math.log(max(r["corpus_rank"] for r in ranked) * 1.5)
    noise = measure_noise(conn, lang, counts)

    # Level lists: a lemma gets its list's level; a lemma in two lists keeps the easier one.
    levels: dict[str, str] = {}
    for word, level in conn.execute(
        "SELECT lemma, level FROM level_word WHERE language = ?", (lang,)
    ):
        levels[word] = str(level)
    level_label = {r["id"]: levels[r["lemma"]] for r in rows if r["lemma"] in levels}
    common_label = {r["id"]: str(r["is_common"]) for r in rows if r["is_common"] is not None}
    sources = [
        calibrate("level", level_label, ln_rank, counts, noise),
        calibrate("common", common_label, ln_rank, counts, noise),
    ]

    updates = []
    for r in rows:
        catalog = (ln_rank[r["id"]], counts[r["id"]]) if r["id"] in ln_rank else None
        outside = [(sources[0], level_label.get(r["id"])), (sources[1], common_label.get(r["id"]))]
        if catalog is None and not any(label for _, label in outside):
            updates.append((None, None, r["id"]))
            continue
        est = blend(catalog, outside, top, noise)
        updates.append((est.ln_rank, est.sd, r["id"]))
    report = {
        "noise": {"v0": noise.v0, "v1": noise.v1},
        "sources": {s.name: {"labels": len(s.mean), "sd": math.sqrt(s.variance)} for s in sources},
    }
    with conn:
        conn.executemany("UPDATE lemma SET difficulty = ?, difficulty_sd = ? WHERE id = ?", updates)
        conn.execute(
            "INSERT OR REPLACE INTO dict_meta (name, version, source, sha256, entries, loaded_at)"
            " VALUES (?, NULL, ?, NULL, ?, ?)",
            (
                f"difficulty-{lang}",
                json.dumps(report),
                sum(1 for u in updates if u[0] is not None),
                time.time() if now is None else now,
            ),
        )
    return {"words": sum(1 for u in updates if u[0] is not None), **report}
