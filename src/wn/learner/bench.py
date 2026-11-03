"""A benchmark for the learner model: simulated learners with a known vocabulary.

Each simulated learner has a true ability, a true slope and a true difficulty for every
word. The catalog only sees a noisy rank for each word, as the real one does. The learner
takes a simulated placement test (word checks near 50%, plus a few fake words) and the model
is scored on the words it never asked about, by frequency band.

    wn learner bench [--learners 100]

Nothing here reads a real profile or a real catalog.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field

from . import difficulty, model

BANDS = ((1, 300), (300, 1500), (1500, 5000), (5000, 20000))
WORDS = 20000
TEST_ITEMS = 60
FAKES = 12


@dataclass
class World:
    """True difficulty of each word (ln rank) and what the catalog saw instead."""

    truth: list[float]
    observed: list[float]
    sightings: list[int]
    splits: list[tuple[int, float, float]] = field(default_factory=list)  # half-split ranks
    jlpt: list[str | None] = field(default_factory=list)  # an outside level per word
    band: list[str | None] = field(default_factory=list)  # an outside frequency band


# True rank cut-offs for the simulated JLPT levels, and the width of a news band.
_JLPT_CUTS = ((800, "5"), (1600, "4"), (3200, "3"), (6000, "2"), (10_000_000, "1"))


def make_world(rng: random.Random, words: int = WORDS) -> World:
    truth, observed, sightings, jlpt, band, splits = [], [], [], [], [], []
    for i in range(words):
        rank = i + 1
        seen = max(1, round(4000 / rank**0.9))  # rare words are seen only a few times
        # A word seen n times has a rank known to about 1 / sqrt(n) in ln units, and
        # webnovels also skew some words (jargon up, everyday words down).
        sd = 0.35 + 1.1 / math.sqrt(seen)
        noise = rng.gauss(0, sd)
        half = rng.gauss(0, sd)  # two half-catalog ranks differ by 2 * half in ln units
        splits.append((seen, math.log(rank) + noise + half, math.log(rank) + noise - half))
        truth.append(math.log(rank))
        observed.append(math.log(rank) + noise)
        sightings.append(seen)
        # The outside lists see a word through their own noisy view of how common it is.
        view = rank * math.exp(rng.gauss(0, 0.6))
        jlpt.append(next(label for cut, label in _JLPT_CUTS if view < cut) if rank < 9000 else None)
        news = rank * math.exp(rng.gauss(0, 0.5))
        band.append(str(int(news // 500)) if news < 24_000 and rank < 20_000 else None)
    return World(truth, observed, sightings, splits, jlpt, band)


@dataclass
class Learner:
    theta: float
    slope: float
    guess: float  # chance of claiming a fake word

    def p(self, difficulty: float) -> float:
        return model.sigmoid(self.slope * (self.theta - difficulty))


def make_learner(rng: random.Random, words: int = WORDS) -> Learner:
    return Learner(
        theta=math.log(rng.uniform(words / 40, words * 0.4)),
        slope=rng.uniform(2.0, 5.0),
        guess=rng.choice([0.0, 0.0, 0.05, 0.15]),
    )


@dataclass
class Score:
    """Log loss and calibration of predictions, per band of the catalog rank the app sees."""

    loss: dict[tuple[int, int], list[float]] = field(default_factory=dict)
    predicted: dict[tuple[int, int], list[float]] = field(default_factory=dict)
    actual: dict[tuple[int, int], list[float]] = field(default_factory=dict)

    def add(self, rank: float, p: float, known: bool) -> None:
        for band in BANDS:
            if band[0] <= rank < band[1]:
                p = min(max(p, 1e-4), 1 - 1e-4)
                self.loss.setdefault(band, []).append(-math.log(p if known else 1 - p))
                self.predicted.setdefault(band, []).append(p)
                self.actual.setdefault(band, []).append(1.0 if known else 0.0)

    def table(self) -> list[dict]:
        rows = []
        for band in BANDS:
            n = len(self.loss.get(band, []))
            if not n:
                continue
            rows.append(
                {
                    "band": band,
                    "n": n,
                    "log_loss": sum(self.loss[band]) / n,
                    "predicted": sum(self.predicted[band]) / n,
                    "actual": sum(self.actual[band]) / n,
                }
            )
        return rows

    def reliability(self, buckets: int = 5) -> list[tuple[float, float, int]]:
        """(mean predicted, share actually known, n) for equal-width probability buckets."""
        rows = []
        pairs = [
            (p, a)
            for band in BANDS
            for p, a in zip(self.predicted.get(band, []), self.actual.get(band, []), strict=True)
        ]
        for k in range(buckets):
            low, high = k / buckets, (k + 1) / buckets
            part = [(p, a) for p, a in pairs if low <= p < high or (k == buckets - 1 and p == 1)]
            if part:
                rows.append(
                    (
                        sum(p for p, _ in part) / len(part),
                        sum(a for _, a in part) / len(part),
                        len(part),
                    )
                )
        return rows

    def total_loss(self) -> float:
        every = [x for v in self.loss.values() for x in v]
        return sum(every) / len(every) if every else float("nan")


# A "scheme" turns a world into what the model sees, and builds observations and predictions.
# The baseline scheme is today's model: ln of the catalog rank, a fixed slope.
Predict = Callable[[model.Params, int], float]


@dataclass
class Scheme:
    name: str
    difficulty: Callable[[World, int], float]  # what the model uses for word i
    fit: Callable[[list[model.Observation], float], model.Params]
    predict: Predict
    choose: Callable[[World, model.Params, set[int], random.Random], int]


LEGACY_SLOPE = 1.5  # the model before version 2: a fixed slope, a theta-only fit here


def _legacy_fit(obs: list[model.Observation], guess: float) -> model.Params:
    """Version 1 of the fit, kept so the benchmark can still compare against it."""
    prior_mean, prior_sd = model.THETA_PRIOR
    theta = prior_mean
    info = 1 / prior_sd**2
    for _ in range(40):
        grad = -(theta - prior_mean) / prior_sd**2
        info = 1 / prior_sd**2
        for o in obs:
            p = model.sigmoid(LEGACY_SLOPE * (theta - o.offset))
            q = min(max(o.guess + (1 - o.guess) * p, 1e-6), 1 - 1e-6)
            dq = (1 - o.guess) * p * (1 - p) * LEGACY_SLOPE
            grad += o.weight * (1 / q if o.known else -1 / (1 - q)) * dq
            info += o.weight * dq * dq / (q * (1 - q))
        step = grad / info
        theta += max(-1.0, min(1.0, step))
        if abs(step) < 1e-5:
            break
    return model.Params(theta=theta, theta_sd=math.sqrt(1 / info), guess_rate=guess)


def baseline_scheme(world: World) -> Scheme:
    """The model as it was before version 2: ln of the catalog rank, a fixed slope of 1.5."""

    def difficulty(w: World, i: int) -> float:
        return w.observed[i]

    def predict(params: model.Params, i: int) -> float:
        return model.sigmoid(LEGACY_SLOPE * (params.theta - world.observed[i]))

    def choose(w: World, params: model.Params, asked: set[int], rng: random.Random) -> int:
        order = sorted(
            (i for i in range(len(w.truth)) if i not in asked),
            key=lambda i: abs(predict(params, i) - 0.5),
        )
        return rng.choice(order[:5])

    return Scheme("before version 2", difficulty, _legacy_fit, predict, choose)


def run_learner(
    scheme: Scheme, world: World, learner: Learner, rng: random.Random, score: Score
) -> None:
    obs: list[model.Observation] = []
    asked: set[int] = set()
    fake_slots = set(rng.sample(range(TEST_ITEMS + FAKES), FAKES))
    fakes = fake_yes = 0
    params = scheme.fit([], model.guess_rate(0, 0))
    guess = model.guess_rate(0, 0)
    for step in range(TEST_ITEMS + FAKES):
        if step in fake_slots:
            fakes += 1
            fake_yes += rng.random() < learner.guess
            guess = model.guess_rate(fake_yes, fakes)
        else:
            i = scheme.choose(world, params, asked, rng)
            asked.add(i)
            p = learner.p(world.truth[i])
            known = rng.random() < p + (1 - p) * learner.guess
            obs.append(
                model.Observation(((0, 1.0),), scheme.difficulty(world, i), known, 1.0, guess)
            )
        params = scheme.fit(obs, guess)
    for i in range(len(world.truth)):
        if i in asked:
            continue
        # The learner's real chance of *knowing* the word (not of claiming it).
        known = rng.random() < learner.p(world.truth[i])
        score.add(math.exp(world.observed[i]), scheme.predict(params, i), known)


def run(
    learners: int = 100,
    seed: int = 1,
    make: Callable[[World], Scheme] = baseline_scheme,
    words: int = WORDS,
):
    rng = random.Random(seed)
    world = make_world(rng, words)
    scheme = make(world)
    score = Score()
    for _ in range(learners):
        run_learner(scheme, world, make_learner(rng, words), rng, score)
    return scheme.name, score


def report(name: str, score: Score) -> str:
    lines = [f"{name}: overall log loss {score.total_loss():.3f}"]
    lines.append("  rank band        n   log loss  predicted  actual")
    for row in score.table():
        low, high = row["band"]
        lines.append(
            f"  {low:>5}-{high:<6} {row['n']:>7}   {row['log_loss']:.3f}     "
            f"{row['predicted']:.3f}     {row['actual']:.3f}"
        )
    lines.append("  when it says  ->  actually known   (n)")
    for predicted, actual, n in score.reliability():
        lines.append(f"  {predicted:>8.2f}      {actual:>8.2f}     {n}")
    return "\n".join(lines)


def compare(learners: int = 100, seed: int = 1, words: int = WORDS) -> str:

    out = []
    for make in (baseline_scheme, improved_scheme):
        out.append(report(*run(learners, seed, make, words)))
    return "\n\n".join(out)


def improved_scheme(
    world: World,
    blend: bool = True,
    use_sd: bool = True,
    fit_noise: bool = True,
) -> Scheme:
    """Blended difficulty with its uncertainty, and a fitted slope."""
    noise = difficulty.fit_noise(world.splits) if fit_noise else difficulty.DEFAULT_NOISE
    ln_rank = dict(enumerate(world.observed))
    seen = dict(enumerate(world.sightings))
    sources = [
        difficulty.calibrate(
            "jlpt", {i: v for i, v in enumerate(world.jlpt) if v is not None}, ln_rank, seen, noise
        ),
        difficulty.calibrate(
            "news", {i: v for i, v in enumerate(world.band) if v is not None}, ln_rank, seen, noise
        ),
    ]
    top = max(world.observed) + 0.4
    blended = [
        difficulty.blend(
            (world.observed[i], world.sightings[i]),
            [(sources[0], world.jlpt[i]), (sources[1], world.band[i])] if blend else [],
            top,
            noise,
        )
        for i in range(len(world.truth))
    ]
    if not use_sd:
        blended = [difficulty.Estimate(e.ln_rank, 0.0) for e in blended]

    def difficulty_of(w: World, i: int) -> float:
        return blended[i].ln_rank

    sd_by_offset = {e.ln_rank: e.sd for e in blended}

    def fit(obs: list[model.Observation], guess: float) -> model.Params:
        # The bench's observations carry the word's difficulty as the offset; the sd comes
        # from the same table (unique per word in practice).
        rows = [
            model.Observation(
                o.features, o.offset, o.known, o.weight, o.guess, sd_by_offset[o.offset]
            )
            for o in obs
        ]
        return model.fit(rows, guess, len(rows))

    def predict(params: model.Params, i: int) -> float:
        return model.p_know(params, math.exp(blended[i].ln_rank), [], blended[i].sd)

    def choose(w: World, params: model.Params, asked: set[int], rng: random.Random) -> int:
        target = 0.5
        order = sorted(
            (i for i in range(len(w.truth)) if i not in asked),
            key=lambda i: abs(predict(params, i) - target),
        )
        return rng.choice(order[:5])

    return Scheme("improved", difficulty_of, fit, predict, choose)


# --- a check on a real profile ----------------------------------------------------------------


def _claim(p: float, guess: float) -> float:
    return guess + (1 - guess) * p


def check(profile, catalog, lang: str = "ja", folds: int = 5) -> str:
    """Hold out your own answers and marks, and compare how well each model predicts them.

    Both models are refitted on the other folds. "Before version 2" uses the raw catalog rank
    and a fixed slope of 1.5, and ignores domains; the new model uses the blended difficulty,
    a fitted slope and the domain offsets. Nothing leaves this machine.
    """
    new_lex = model.Lexicon.load(catalog, model.load_fixes(profile, lang), lang)
    old_lex = model.Lexicon.load(catalog, model.load_fixes(profile, lang), lang)
    old_lex.difficulty.clear()
    old_lex.spread.clear()
    new_obs, guess, _ = model.observations(profile, new_lex)
    old_obs, _guess, _ = model.observations(profile, old_lex)
    if len(new_obs) < folds * 10:
        return f"only {len(new_obs)} answers and marks so far; take the placement test first"
    order = list(range(len(new_obs)))
    random.Random(1).shuffle(order)
    old_score, new_score = Score(), Score()
    for fold in range(folds):
        held = set(order[fold::folds])
        train = [i for i in range(len(new_obs)) if i not in held]
        params = model.fit([new_obs[i] for i in train], guess, len(train))
        legacy = _legacy_fit([old_obs[i] for i in train], guess)
        for i in held:
            o, b = new_obs[i], old_obs[i]
            if o.guess >= 1 or o.weight < 1:  # leave out the faint "untapped" evidence
                continue
            x = sum(v * ([params.theta] + list(params.deltas.values()))[k] for k, v in o.features)
            p_new = model.sigmoid(model.effective_slope(params.slope, o.sd) * (x - o.offset))
            p_old = model.sigmoid(LEGACY_SLOPE * (legacy.theta - b.offset))
            for score, p, obs in ((new_score, p_new, o), (old_score, p_old, b)):
                score.add(math.exp(obs.offset), _claim(p, obs.guess), obs.known)
    return "\n\n".join(
        [
            "Held-out answers and marks, 5-fold; 'predicted' is the chance of the answer given.",
            report("before version 2", old_score),
            report("version 2", new_score),
        ]
    )


if __name__ == "__main__":
    import sys

    print(compare(int(sys.argv[1]) if len(sys.argv) > 1 else 100))
