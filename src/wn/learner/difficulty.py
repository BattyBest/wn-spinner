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
