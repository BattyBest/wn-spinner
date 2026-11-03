import math
import random

from wn.learner import bench, difficulty, model


def test_the_new_model_beats_the_old_one_on_simulated_learners():
    old = bench.run(10, seed=3, make=bench.baseline_scheme, words=3000)[1]
    new = bench.run(10, seed=3, make=bench.improved_scheme, words=3000)[1]
    assert new.total_loss() < old.total_loss() - 0.03
    # When the new model says "probably known", it is mostly right.
    top = new.reliability()[-1]
    assert top[0] > 0.85 and top[1] > 0.8


def test_the_report_has_a_table_for_every_band():
    text = bench.report(*bench.run(3, seed=1, words=2000))
    assert "before version 2" in text and "when it says" in text


def test_a_learner_with_a_steep_slope_gets_a_steeper_fit():
    rng = random.Random(4)

    def answers(slope: float) -> list[model.Observation]:
        out = []
        for _ in range(400):
            rank = math.exp(rng.uniform(math.log(100), math.log(20000)))
            p = model.sigmoid(slope * (math.log(2000) - math.log(rank)))
            out.append(model.Observation(((0, 1.0),), math.log(rank), rng.random() < p, 1.0, 0.0))
        return out

    shallow, steep = model.fit(answers(1.5)), model.fit(answers(5.0))
    assert shallow.slope < 2.6 < 3.6 < steep.slope
    assert abs(steep.theta - math.log(2000)) < 0.2


def test_an_uncertain_difficulty_flattens_the_curve():
    params = model.Params(theta=math.log(1000))
    sure = model.p_know(params, 100, [], 0.0)
    unsure = model.p_know(params, 100, [], 1.5)
    assert 0.5 < unsure < sure < 1
    assert model.p_know(params, 1000, [], 1.5) == 0.5


def test_params_saved_before_version_2_load_with_the_default_slope():
    old = '{"theta": [7.0, 0.4], "domains": {"fantasy": [0.3, 0.2]}}'
    params = model.Params.from_json(old, 0.1, 50)
    assert params.slope == model.SLOPE and params.deltas["fantasy"] == 0.3
    again = model.Params.from_json(params.to_json(), 0.1, 50)
    assert abs(again.slope - params.slope) < 1e-9


def test_fit_noise_measures_how_rank_noise_falls_with_sightings():
    rng = random.Random(2)
    splits = []
    for n in [1, 2, 5, 20, 100] * 80:
        sd = math.sqrt(0.1 + 1.0 / n)
        half = rng.gauss(0, sd)  # the halves differ by 2 * half
        splits.append((n, 7.0 + half, 7.0 - half))
    noise = difficulty.fit_noise(splits)
    assert 0.7 < noise.v1 < 1.4 and noise.v0 < 0.3
    assert difficulty.fit_noise([(1, 5.0, 6.0)]) == difficulty.DEFAULT_NOISE


def test_blend_trusts_the_better_source_and_pushes_unsure_words_harder():
    source = difficulty.Source("level", {"5": math.log(500), "1": math.log(8000)}, 0.5)
    seen_often = difficulty.blend((math.log(520), 200), [(source, "5")], 12.0)
    seen_once = difficulty.blend((math.log(520), 1), [(source, "5")], 12.0)
    assert abs(seen_often.ln_rank - math.log(520)) < 0.1 and seen_often.sd < seen_once.sd
    # Seen once, the level list counts for more than the catalog's rank.
    assert abs(seen_once.ln_rank - math.log(500)) < abs(seen_once.ln_rank - math.log(520)) + 0.7
    alone = difficulty.blend((math.log(5000), 1), [], 12.0)
    assert alone.ln_rank > math.log(5000)  # a word seen once is likely harder than it looks
    assert difficulty.blend(None, [], 12.0) == difficulty.Estimate(12.0, difficulty.UNKNOWN_SD)


def test_the_check_reports_on_held_out_answers(tmp_path):
    from wn.analysis.store import rebuild_frequency
    from wn.db import open_catalog, open_profile
    from wn.learner import difficulty as diff

    from .synthetic import build

    catalog, profile = open_catalog(tmp_path), open_profile(tmp_path)
    ids = build(catalog)
    rebuild_frequency(catalog, "ja")
    diff.rebuild(catalog, "ja")
    assert "take the placement test first" in bench.check(profile, catalog)
    lex = model.Lexicon.load(catalog)
    rng = random.Random(1)
    with profile:
        for lid in ids["lemmas"][:340:4]:
            lemma, pos = lex.keys[lid]
            known = rng.random() < model.sigmoid(2.5 * (math.log(120) - math.log(lex.rank[lid])))
            profile.execute(
                "INSERT INTO answer (language, kind, lemma, pos, known, weight, at)"
                " VALUES ('ja', 'word', ?, ?, ?, 1.0, 1.0)",
                (lemma, pos, int(known)),
            )
    text = bench.check(profile, catalog)
    assert "before version 2" in text and "version 2: overall log loss" in text


def test_the_model_command_is_registered():
    from typer.testing import CliRunner

    from wn.cli import app

    result = CliRunner().invoke(app, ["model", "--help"])
    assert result.exit_code == 0 and "bench" in result.output and "check" in result.output


def test_every_model_meets_the_same_simulated_learners():
    first = bench.run(6, seed=5, make=bench.baseline_scheme, words=2000)[1]
    again = bench.run(6, seed=5, make=bench.baseline_scheme, words=2000)[1]
    other = bench.run(6, seed=5, make=bench.improved_scheme, words=2000)[1]
    assert first.total_loss() == again.total_loss()
    # Same learners and same words held out: the number of scored words matches.
    assert sum(len(v) for v in first.loss.values()) == sum(len(v) for v in other.loss.values())
