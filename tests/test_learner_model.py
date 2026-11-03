import math
import random

from wn.db import open_catalog, open_profile
from wn.learner.domains import DOMAIN_KEYS
from wn.learner.model import (
    Learner,
    Lexicon,
    Observation,
    Params,
    fit,
    guess_rate,
    load_learner,
    p_know,
    refit,
)

from .synthetic import build


def simulate(true: Params, n: int, seed: int, guess: float = 0.0) -> list[Observation]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        rank = rng.choice([30, 100, 300, 800, 2000, 5000, 12000])
        domain = rng.choice([None, "fantasy", "money", "science"])
        weights = [(domain, 1.0)] if domain else []
        p = p_know(true, rank, weights)
        features = [(0, 1.0)] + ([(1 + DOMAIN_KEYS.index(domain), 1.0)] if domain else [])
        out.append(
            Observation(
                tuple(features), math.log(rank), rng.random() < p + (1 - p) * guess, 1.0, guess
            )
        )
    return out


def test_fit_recovers_ability_and_domain_signs():
    true = Params(theta=math.log(3000))
    true.deltas["fantasy"] = 1.2
    true.deltas["money"] = -1.2
    fitted = fit(simulate(true, 600, seed=1), 0.0, 600)
    assert abs(fitted.theta - true.theta) < 0.3
    assert fitted.deltas["fantasy"] > 0.3
    assert fitted.deltas["money"] < -0.3
    assert abs(fitted.deltas["science"]) < 0.5


def test_more_answers_shrink_uncertainty():
    true = Params(theta=math.log(1500))
    few = fit(simulate(true, 30, seed=2), 0.0, 30)
    many = fit(simulate(true, 400, seed=2), 0.0, 400)
    assert many.theta_sd < few.theta_sd < Params().theta_sd
    assert many.delta_sds["fantasy"] < Params().delta_sds["fantasy"]


def test_no_answers_gives_the_prior():
    p = fit([], None, 0)
    assert abs(p.theta - Params().theta) < 1e-6
    assert all(abs(v) < 1e-9 for v in p.deltas.values())


def test_guess_rate_is_smoothed():
    assert guess_rate(0, 0) < 0.15
    assert guess_rate(12, 12) > 0.7
    assert guess_rate(0, 12) < guess_rate(3, 12) < guess_rate(8, 12)


def test_an_overclaimer_comes_out_lower_than_an_honest_learner():
    """Same yes-rate on real words; one says yes to every fake, the other to none."""
    rng = random.Random(5)
    true_yes = 0.8
    obs = []
    for _ in range(200):
        rank = rng.choice([500, 2000, 8000])
        obs.append((math.log(rank), rng.random() < true_yes))

    def run(g: float) -> Params:
        data = [Observation(((0, 1.0),), off, known, 1.0, g) for off, known in obs]
        return fit(data, g, len(data))

    honest, overclaimer = run(guess_rate(0, 12)), run(guess_rate(12, 12))
    assert overclaimer.theta < honest.theta - 0.5


def test_marked_and_function_words_override_the_model(tmp_path):
    catalog, profile = open_catalog(tmp_path), open_profile(tmp_path)
    ids = build(catalog)
    learner = load_learner(profile, catalog)
    word = ids["lemmas"][200]
    assert 0 < learner.p(word) < 1
    assert learner.p(ids["particle"]) == 1.0
    key = learner.lexicon.keys[word]
    learner.status[key] = True
    assert learner.p(word) == 1.0
    learner.status[key] = False
    assert learner.p(word) == 0.0


def test_refit_from_stored_answers_moves_the_model(tmp_path):
    catalog, profile = open_catalog(tmp_path), open_profile(tmp_path)
    ids = build(catalog)
    lexicon = Lexicon.load(catalog)
    # Knows the 150 most common words, none of the rest.
    with profile:
        for lid in ids["lemmas"][:300:3]:
            lemma, pos = lexicon.keys[lid]
            profile.execute(
                "INSERT INTO answer (language, kind, lemma, pos, known, weight, at)"
                " VALUES ('ja', 'word', ?, ?, ?, 1.0, 1.0)",
                (lemma, pos, int(lexicon.rank[lid] <= 150)),
            )
    params = refit(profile, lexicon)
    assert params.answers == 100
    assert 60 < params.vocabulary() < 400
    saved = profile.execute("SELECT answers FROM model").fetchone()[0]
    assert saved == 100
    assert Learner(params, lexicon).p(ids["lemmas"][5]) > 0.9
    assert Learner(params, lexicon).p(ids["lemmas"][340]) < 0.2
