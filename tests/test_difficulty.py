import math

from wn.analysis.store import rebuild_frequency
from wn.db import open_catalog, open_profile
from wn.learner import difficulty
from wn.learner.model import Lexicon, load_learner, observations, refit

from .synthetic import build


def _catalog(tmp_path):
    catalog = open_catalog(tmp_path)
    ids = build(catalog)
    rebuild_frequency(catalog, "ja")
    return catalog, ids


def test_rebuild_gives_ranked_words_a_difficulty_and_an_uncertainty(tmp_path):
    catalog, ids = _catalog(tmp_path)
    # Level lists for the 60 commonest words (level 5) and for words 100-159 (level 1).
    rows = [
        (
            catalog.execute("SELECT lemma FROM lemma WHERE id = ?", (ids["lemmas"][i],)).fetchone()[
                0
            ],
            5,
        )
        for i in range(60)
    ]
    rows += [
        (
            catalog.execute("SELECT lemma FROM lemma WHERE id = ?", (ids["lemmas"][i],)).fetchone()[
                0
            ],
            1,
        )
        for i in range(100, 160)
    ]
    with catalog:
        catalog.executemany(
            "INSERT OR IGNORE INTO level_word (language, lemma, reading, level)"
            " VALUES ('ja', ?, '', ?)",
            rows,
        )
    report = difficulty.rebuild(catalog, "ja")
    assert report["words"] >= 360 and report["noise"]["v0"] > 0
    assert report["sources"]["level"]["labels"] == 2
    lex = Lexicon.load(catalog)
    easy, hard = ids["lemmas"][5], ids["lemmas"][130]
    assert lex.rank_of(easy) < lex.rank_of(hard)
    assert lex.sd_of(easy) > 0 and lex.sd_of(hard) > 0
    # The particle is not part of the ranking and has no difficulty, so the old rule applies.
    assert ids["particle"] not in lex.difficulty


def test_without_a_rebuild_the_raw_rank_and_no_uncertainty_are_used(tmp_path):
    catalog, ids = _catalog(tmp_path)
    lex = Lexicon.load(catalog)
    word = ids["lemmas"][10]
    assert lex.rank_of(word) == lex.rank[word] and lex.sd_of(word) == 0.0
    assert lex.sd_of(10**9) == difficulty.UNKNOWN_SD  # a word the catalog never ranked


def test_domain_weights_of_a_word_sum_to_at_most_one(tmp_path):
    catalog, ids = _catalog(tmp_path)
    word = ids["lemmas"][25]  # a fantasy word; give it two more domains
    with catalog:
        for domain in ("combat", "court"):
            catalog.execute(
                "INSERT INTO lemma_domain (lemma_id, domain, weight, source)"
                " VALUES (?, ?, 1, 'dictionary')",
                (word, domain),
            )
    weights = Lexicon.load(catalog).weights[word]
    assert len(weights) == 3 and abs(sum(w for _d, w in weights) - 1.0) < 1e-9
    single = Lexicon.load(catalog).weights[ids["lemmas"][65]]
    assert single == [("money", 1.0)]  # one domain keeps its full weight


def test_a_word_marked_again_counts_once_and_clearing_it_removes_its_evidence(tmp_path):
    catalog, ids = _catalog(tmp_path)
    profile = open_profile(tmp_path)
    lexicon = Lexicon.load(catalog)
    lemma, pos = lexicon.keys[ids["lemmas"][700 // 4]]

    def mark(known: int | None) -> None:
        with profile:
            if known is None:
                profile.execute("DELETE FROM word_status")
            else:
                profile.execute(
                    "INSERT OR REPLACE INTO word_status (language, lemma, pos, known, at)"
                    " VALUES ('ja', ?, ?, ?, 1.0)",
                    (lemma, pos, known),
                )
                profile.execute(
                    "INSERT INTO answer (language, kind, lemma, pos, known, weight, at)"
                    " VALUES ('ja', 'mark', ?, ?, ?, 1.0, 1.0)",
                    (lemma, pos, known),
                )

    for known in (1, 0, 1, 1):  # flip-flopping leaves four mark rows but one mark
        mark(known)
    obs, _g, used = observations(profile, lexicon)
    assert len(obs) == 1 and used == 1 and obs[0].known
    mark(None)  # the status is cleared; the mark rows stay as history
    obs, _g, used = observations(profile, lexicon)
    assert obs == [] and used == 0
    assert profile.execute("SELECT COUNT(*) FROM answer WHERE kind = 'mark'").fetchone()[0] == 4


def test_marking_easy_words_known_moves_the_fit_up(tmp_path):
    catalog, ids = _catalog(tmp_path)
    profile = open_profile(tmp_path)
    lexicon = Lexicon.load(catalog)
    before = refit(profile, lexicon).theta
    with profile:
        for lid in ids["lemmas"][150:200]:
            lemma, pos = lexicon.keys[lid]
            profile.execute(
                "INSERT INTO word_status (language, lemma, pos, known, at)"
                " VALUES ('ja', ?, ?, 1, 1.0)",
                (lemma, pos),
            )
    after = refit(profile, lexicon).theta
    assert after > before + 0.1
    assert math.isfinite(load_learner(profile, catalog).p(ids["lemmas"][20]))


def test_a_fit_from_an_older_model_version_is_refitted_when_loaded(tmp_path):
    catalog, ids = _catalog(tmp_path)
    profile = open_profile(tmp_path)
    lexicon = Lexicon.load(catalog)
    with profile:
        for lid in ids["lemmas"][:200:4]:
            lemma, pos = lexicon.keys[lid]
            profile.execute(
                "INSERT INTO answer (language, kind, lemma, pos, known, weight, at)"
                " VALUES ('ja', 'word', ?, ?, 1, 1.0, 1.0)",
                (lemma, pos),
            )
        profile.execute(
            "INSERT INTO model (language, version, params, guess_rate, answers, fitted_at)"
            " VALUES ('ja', 1, '{\"theta\": [5.0, 1.0], \"domains\": {}}', 0.1, 50, 1.0)"
        )
    params = load_learner(profile, catalog).params
    assert params.theta != 5.0 and params.answers == 50
    row = profile.execute("SELECT version FROM model WHERE language = 'ja'").fetchone()
    assert row[0] == 2
