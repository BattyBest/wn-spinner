"""The fitted model, version 2: a learned slope and per-word difficulty uncertainty.

    z = a_eff * (theta + sum_d m[w,d] * delta[d] - b[w])
    a_eff = a / sqrt(1 + (pi / 8) * a^2 * s[w]^2)
    P(know w) = sigmoid(z)

``b[w]`` is the word's difficulty (ln rank) with uncertainty ``s[w]`` (see difficulty.py).
A word whose difficulty is uncertain gets a flatter curve, so a surprise on it blames the
word rather than the learner. The slope ``a = exp(alpha)`` is fitted, with a prior that keeps
a short test from swinging it far.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import sigmoid, solve

SLOPE_PRIOR = (math.log(3.0), 0.35)  # mean and sd of alpha = ln slope
THETA_PRIOR = (math.log(1500), 1.5)
DELTA_PRIOR_SD = 0.5
LOGISTIC_NORMAL = math.pi / 8


@dataclass(frozen=True)
class Obs:
    features: tuple[tuple[int, float], ...]  # (parameter index, value); index 0 is theta
    offset: float  # difficulty b of the word, in ln rank
    sd: float  # uncertainty of that difficulty
    known: bool
    weight: float
    guess: float  # chance of this answer being right with no knowledge


def effective_slope(slope: float, sd: float) -> float:
    return slope / math.sqrt(1 + LOGISTIC_NORMAL * slope**2 * sd**2)


def p_word(theta: float, slope: float, delta_sum: float, offset: float, sd: float) -> float:
    return sigmoid(effective_slope(slope, sd) * (theta + delta_sum - offset))


@dataclass
class Fit:
    beta: list[float]  # theta, then one per domain
    alpha: float
    cov: list[list[float]]  # over beta then alpha

    @property
    def slope(self) -> float:
        return math.exp(self.alpha)


def fit(obs: list[Obs], domains: int, delta_sd: float = DELTA_PRIOR_SD) -> Fit:
    """Maximum-a-posteriori fit of ability, domain offsets and slope by Fisher scoring."""
    n = 1 + domains + 1  # the last parameter is alpha
    mean0 = [THETA_PRIOR[0]] + [0.0] * domains + [SLOPE_PRIOR[0]]
    prec = [1 / THETA_PRIOR[1] ** 2] + [1 / delta_sd**2] * domains + [1 / SLOPE_PRIOR[1] ** 2]
    beta = mean0[:]
    info = [[0.0] * n for _ in range(n)]
    for _ in range(40):
        grad = [-prec[i] * (beta[i] - mean0[i]) for i in range(n)]
        info = [[prec[i] if i == j else 0.0 for j in range(n)] for i in range(n)]
        slope = math.exp(beta[-1])
        for o in obs:
            x = sum(beta[i] * v for i, v in o.features) - o.offset
            shrink = 1 + LOGISTIC_NORMAL * slope**2 * o.sd**2
            a_eff = slope / math.sqrt(shrink)
            p = sigmoid(a_eff * x)
            q = min(max(o.guess + (1 - o.guess) * p, 1e-6), 1 - 1e-6)
            dq_dz = (1 - o.guess) * p * (1 - p)
            # dz / d(parameter): a_eff * feature for beta, and for alpha (= ln slope):
            dz_dalpha = x * slope * shrink**-1.5
            g = {i: a_eff * v for i, v in o.features}
            g[n - 1] = dz_dalpha
            score = o.weight * ((1 / q if o.known else -1 / (1 - q)) * dq_dz)
            fisher = o.weight * dq_dz * dq_dz / (q * (1 - q))
            for i, gi in g.items():
                grad[i] += score * gi
                for j, gj in g.items():
                    info[i][j] += fisher * gi * gj
        step = solve(info, grad)
        biggest = max(abs(s) for s in step)
        scale = min(1.0, 1.0 / biggest) if biggest > 0 else 1.0
        beta = [b + scale * s for b, s in zip(beta, step, strict=True)]
        if biggest < 1e-5:
            break
    columns = [solve(info, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    cov = [[columns[j][i] for j in range(n)] for i in range(n)]
    return Fit(beta[:-1], beta[-1], cov)
