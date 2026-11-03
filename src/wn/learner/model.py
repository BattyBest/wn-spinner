"""The learner model: how likely you are to know a word, and how it is fitted.

    P(know w) = sigmoid(a * (theta + sum_d m[w,d] * delta[d] - ln rank[w]))

``theta`` is general ability (``e ** theta`` reads as a vocabulary size), ``delta[d]`` is
strength in domain ``d`` and ``m[w,d]`` how much the word belongs to it. The fit is a
maximum-a-posteriori estimate with Gaussian priors, found by Fisher scoring; the inverse of
the final information matrix gives each parameter's uncertainty. It is a handful of
parameters and a few hundred answers, so plain Python is fast enough.

Answers say more or less about a word. A "yes" on a word check may be over-claiming, so the
chance of a yes is ``p + (1 - p) * g`` where ``g`` is how often you say yes to fake words. A
meaning check can be guessed right a quarter of the time. Weights scale how much each kind
of answer counts.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass, field

from .domains import DOMAIN_KEYS

SLOPE = 1.5
THETA_PRIOR = (math.log(1500), 1.5)
DELTA_PRIOR_SD = 0.8
MEANING_GUESS = 0.25
FAKE_PRIOR = (0.5, 5.0)  # pseudo "yes" and pseudo answers for the guess rate
MODEL_VERSION = 1

# Weight of each kind of evidence; see the plan's table.
WEIGHTS = {"word": 1.0, "meaning": 2.0, "tap": 1.0, "untapped": 0.3, "mark": 1.0}


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)


@dataclass(frozen=True)
class Observation:
    features: tuple[tuple[int, float], ...]  # (parameter index, value); index 0 is theta
    offset: float  # ln rank
    known: bool
    weight: float
    guess: float  # chance of this answer being right with no knowledge


@dataclass
class Params:
    theta: float = THETA_PRIOR[0]
    theta_sd: float = THETA_PRIOR[1]
    deltas: dict[str, float] = field(default_factory=lambda: dict.fromkeys(DOMAIN_KEYS, 0.0))
    delta_sds: dict[str, float] = field(
        default_factory=lambda: dict.fromkeys(DOMAIN_KEYS, DELTA_PRIOR_SD)
    )
    guess_rate: float = FAKE_PRIOR[0] / FAKE_PRIOR[1]
    answers: int = 0

    def vocabulary(self) -> int:
        return round(math.exp(self.theta))

    def to_json(self) -> str:
        return json.dumps(
            {
                "theta": [self.theta, self.theta_sd],
                "domains": {k: [self.deltas[k], self.delta_sds[k]] for k in DOMAIN_KEYS},
            }
        )

    @classmethod
    def from_json(cls, text: str, guess_rate: float, answers: int) -> Params:
        data = json.loads(text)
        out = cls(guess_rate=guess_rate, answers=answers)
        out.theta, out.theta_sd = data["theta"]
        for key, (mean, sd) in data["domains"].items():
            if key in out.deltas:
                out.deltas[key], out.delta_sds[key] = mean, sd
        return out


def p_know(params: Params, rank: float, weights: list[tuple[str, float]]) -> float:
    """Chance of knowing a word of this frequency rank and domain weights."""
    x = params.theta - math.log(max(rank, 1.0))
    for domain, m in weights:
        x += m * params.deltas.get(domain, 0.0)
    return sigmoid(SLOPE * x)


def solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Solve ``matrix x = rhs`` by Gaussian elimination with partial pivoting."""
    n = len(rhs)
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        if abs(a[col][col]) < 1e-12:
            raise ValueError("singular matrix")
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            for k in range(col, n + 1):
                a[row][k] -= factor * a[col][k]
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        x[row] = (a[row][n] - sum(a[row][k] * x[k] for k in range(row + 1, n))) / a[row][row]
    return x


def invert(matrix: list[list[float]]) -> list[list[float]]:
    n = len(matrix)
    columns = [solve(matrix, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[columns[j][i] for j in range(n)] for i in range(n)]


def guess_rate(fake_yes: int, fakes: int) -> float:
    """Share of fake words you said you knew, smoothed so a few answers don't swing it."""
    return (fake_yes + FAKE_PRIOR[0]) / (fakes + FAKE_PRIOR[1])


def fit(observations: list[Observation], guess: float | None = None, answers: int = 0) -> Params:
    """Maximum-a-posteriori fit of theta and the domain offsets."""
    keys = list(DOMAIN_KEYS)
    n = 1 + len(keys)
    mean0 = [THETA_PRIOR[0]] + [0.0] * len(keys)
    prec = [1 / THETA_PRIOR[1] ** 2] + [1 / DELTA_PRIOR_SD**2] * len(keys)
    beta = mean0[:]
    info = [[0.0] * n for _ in range(n)]
    for _ in range(40):
        grad = [-prec[i] * (beta[i] - mean0[i]) for i in range(n)]
        info = [[prec[i] if i == j else 0.0 for j in range(n)] for i in range(n)]
        for o in observations:
            x = sum(beta[i] * v for i, v in o.features) - o.offset
            p = sigmoid(SLOPE * x)
            q = min(max(o.guess + (1 - o.guess) * p, 1e-6), 1 - 1e-6)
            dq = (1 - o.guess) * p * (1 - p) * SLOPE  # dq / dx
            slope = o.weight * ((1 / q if o.known else -1 / (1 - q)) * dq)
            fisher = o.weight * dq * dq / (q * (1 - q))
            for i, vi in o.features:
                grad[i] += slope * vi
                for j, vj in o.features:
                    info[i][j] += fisher * vi * vj
        step = solve(info, grad)
        biggest = max(abs(s) for s in step)
        scale = min(1.0, 1.0 / biggest) if biggest > 0 else 1.0
        beta = [b + scale * s for b, s in zip(beta, step, strict=True)]
        if biggest < 1e-5:
            break
    cov = invert(info)
    params = Params(
        theta=beta[0],
        theta_sd=math.sqrt(max(cov[0][0], 0.0)),
        deltas={k: beta[1 + i] for i, k in enumerate(keys)},
        delta_sds={k: math.sqrt(max(cov[1 + i][1 + i], 0.0)) for i, k in enumerate(keys)},
        answers=answers,
    )
    if guess is not None:
        params.guess_rate = guess
    return params


# --- the catalog's view of words --------------------------------------------------------


@dataclass
class Lexicon:
    """What the model needs to know about each catalog lemma, loaded once."""

    rank: dict[int, int | None] = field(default_factory=dict)
    function: set[int] = field(default_factory=set)
    names: set[int] = field(default_factory=set)
    weights: dict[int, list[tuple[str, float]]] = field(default_factory=dict)
    ids: dict[tuple[str, str], int] = field(default_factory=dict)
    keys: dict[int, tuple[str, str]] = field(default_factory=dict)
    max_rank: int = 1
    lang: str = "ja"

    def rank_of(self, lemma_id: int) -> float:
        rank = self.rank.get(lemma_id)
        # A word the catalog never saw often enough to rank is treated as rarer than any ranked.
        return float(rank) if rank else self.max_rank * 1.5

    @classmethod
    def load(
        cls,
        catalog: sqlite3.Connection,
        fixes: list[tuple[str, str, str, str]] = (),
        lang: str = "ja",
    ):
        """``fixes`` are ``(lemma, pos, domain, action)`` from profile.db."""
        lex = cls(lang=lang)
        for row in catalog.execute(
            "SELECT id, lemma, pos, corpus_rank, is_function FROM lemma WHERE language = ?",
            (lang,),
        ):
            lex.rank[row["id"]] = row["corpus_rank"]
            lex.keys[row["id"]] = (row["lemma"], row["pos"])
            lex.ids[(row["lemma"], row["pos"])] = row["id"]
            if row["is_function"]:
                lex.function.add(row["id"])
            if row["corpus_rank"] and row["corpus_rank"] > lex.max_rank:
                lex.max_rank = row["corpus_rank"]
        for row in catalog.execute(
            "SELECT ld.lemma_id, ld.domain, ld.weight FROM lemma_domain ld"
            " JOIN lemma l ON l.id = ld.lemma_id WHERE l.language = ?",
            (lang,),
        ):
            lex.weights.setdefault(row["lemma_id"], []).append((row["domain"], row["weight"]))
        for lemma, pos, domain, action in fixes:
            lemma_id = lex.ids.get((lemma, pos))
            if lemma_id is None:
                continue
            current = [(d, w) for d, w in lex.weights.get(lemma_id, []) if d != domain]
            if action == "add":
                current.append((domain, 1.0))
            if current:
                lex.weights[lemma_id] = current
            else:
                lex.weights.pop(lemma_id, None)
        return lex


@dataclass
class Learner:
    """Params plus the lexicon and the words you marked: answers 'do I know this lemma?'."""

    params: Params
    lexicon: Lexicon
    status: dict[tuple[str, str], bool] = field(default_factory=dict)

    def p(self, lemma_id: int) -> float:
        lex = self.lexicon
        if lemma_id in lex.function:
            return 1.0
        marked = self.status.get(lex.keys.get(lemma_id, ("", "")))
        if marked is not None:
            return 1.0 if marked else 0.0
        return p_know(self.params, lex.rank_of(lemma_id), lex.weights.get(lemma_id, []))


# --- profile.db ------------------------------------------------------------------------


def load_fixes(profile: sqlite3.Connection, lang: str = "ja") -> list[tuple[str, str, str, str]]:
    rows = profile.execute(
        "SELECT lemma, pos, domain, action FROM domain_fix WHERE language = ?", (lang,)
    )
    return [(r[0], r[1], r[2], r[3]) for r in rows]


def load_status(profile: sqlite3.Connection, lang: str = "ja") -> dict[tuple[str, str], bool]:
    rows = profile.execute("SELECT lemma, pos, known FROM word_status WHERE language = ?", (lang,))
    return {(r[0], r[1]): bool(r[2]) for r in rows}


def observations(
    profile: sqlite3.Connection, lexicon: Lexicon
) -> tuple[list[Observation], float, int]:
    """Turn stored answers into observations. Returns them, the guess rate and the count."""
    domain_index = {k: 1 + i for i, k in enumerate(DOMAIN_KEYS)}
    out: list[Observation] = []
    fakes = fake_yes = used = 0
    for row in profile.execute(
        "SELECT kind, lemma, pos, known, weight FROM answer WHERE language = ? ORDER BY id",
        (lexicon.lang,),
    ):
        used += 1
        if row["kind"] == "fake":
            fakes += 1
            fake_yes += row["known"]
            continue
        lemma_id = lexicon.ids.get((row["lemma"], row["pos"]))
        if lemma_id is None or lemma_id in lexicon.function:
            continue
        features = [(0, 1.0)] + [
            (domain_index[d], w) for d, w in lexicon.weights.get(lemma_id, []) if d in domain_index
        ]
        out.append(
            Observation(
                tuple(features),
                math.log(max(lexicon.rank_of(lemma_id), 1.0)),
                bool(row["known"]),
                row["weight"],
                MEANING_GUESS
                if row["kind"] == "meaning"
                else (-1.0 if row["kind"] == "word" else 0.0),
            )
        )
    g = guess_rate(fake_yes, fakes)
    # Word-check answers carry the guess rate, which is only known once all fakes are counted.
    fixed = [
        Observation(o.features, o.offset, o.known, o.weight, g if o.guess < 0 else o.guess)
        for o in out
    ]
    return fixed, g, used


def refit(profile: sqlite3.Connection, lexicon: Lexicon, now: float | None = None) -> Params:
    """Fit the model from every stored answer, save it and return it."""
    obs, g, used = observations(profile, lexicon)
    params = fit(obs, g, used)
    with profile:
        profile.execute(
            "INSERT OR REPLACE INTO model"
            " (language, version, params, guess_rate, answers, fitted_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                lexicon.lang,
                MODEL_VERSION,
                params.to_json(),
                g,
                used,
                time.time() if now is None else now,
            ),
        )
    return params


def load_params(profile: sqlite3.Connection, lang: str = "ja") -> Params:
    row = profile.execute("SELECT * FROM model WHERE language = ?", (lang,)).fetchone()
    if row is None:
        return Params()
    return Params.from_json(row["params"], row["guess_rate"], row["answers"])


def load_learner(
    profile: sqlite3.Connection, catalog: sqlite3.Connection, lang: str = "ja"
) -> Learner:
    lexicon = Lexicon.load(catalog, load_fixes(profile, lang), lang)
    return Learner(load_params(profile, lang), lexicon, load_status(profile, lang))
