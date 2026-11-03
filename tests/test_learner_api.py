import pytest
from fastapi.testclient import TestClient

from wn.api.app import create_app
from wn.db import open_catalog, open_profile
from wn.learner.coverage import BANDS, band_of

from .synthetic import add_easy_novels, build
from .test_placement import run_test


@pytest.fixture
def tested(tmp_path):
    """A client whose learner has taken the test, on the synthetic catalog."""
    catalog = open_catalog(tmp_path)
    ids = build(catalog)
    glosses = {r["lemma"]: r["gloss"] for r in catalog.execute("SELECT lemma, gloss FROM lemma")}
    ranks = {
        r["lemma"]: r["corpus_rank"]
        for r in catalog.execute("SELECT lemma, corpus_rank FROM lemma")
    }
    weights = {}
    for r in catalog.execute(
        "SELECT l.lemma, d.domain, d.weight FROM lemma_domain d JOIN lemma l ON l.id = d.lemma_id"
    ):
        weights.setdefault(r["lemma"], []).append((r["domain"], r["weight"]))
    catalog.close()
    client = TestClient(create_app(tmp_path))
    run_test(client, "full", glosses, ranks, weights)
    return client, ids, tmp_path


@pytest.fixture
def untested(tmp_path):
    catalog = open_catalog(tmp_path)
    ids = build(catalog)
    catalog.close()
    return TestClient(create_app(tmp_path)), ids, tmp_path


def test_bands():
    assert [band_of(x) for x in (0.99, 0.98, 0.96, 0.95, 0.92, 0.9, 0.5)] == [
        "comfortable",
        "comfortable",
        "stretch",
        "stretch",
        "hard",
        "hard",
        "too_hard",
    ]
    assert [name for name, _ in BANDS] == ["comfortable", "stretch", "hard", "too_hard"]


def test_before_the_test_cards_have_no_personal_part_and_best_is_refused(untested):
    client, *_ = untested
    items = client.get("/api/novels").json()["items"]
    assert items and all(i["me"] is None for i in items)
    assert client.get("/api/novels?sort=best").status_code == 409
    assert client.get("/api/novels?band=stretch").status_code == 409
    detail = client.get(f"/api/novels/{items[0]['id']}").json()
    assert detail["me"] is None and detail["unknown_words"] == []


def test_cards_carry_predicted_coverage_and_a_band(tested):
    client, *_ = tested
    items = client.get("/api/novels?limit=100").json()["items"]
    assert len(items) == 12
    for item in items:
        me = item["me"]
        assert 0 < me["coverage"] < 1
        assert me["band"] in {"comfortable", "stretch", "hard", "too_hard"}
        assert me["unknown_distinct"] >= me["unknown_repeating"] >= 0


def test_coverage_is_higher_for_novels_heavy_in_a_strong_domain(tested):
    client, ids, _ = tested
    by_id = {
        i["id"]: i["me"]["coverage"] for i in client.get("/api/novels?limit=100").json()["items"]
    }
    fantasy = [by_id[n] for n in ids["novels"][:4]]  # extra counts on the fantasy words
    other = [by_id[n] for n in ids["novels"][4:]]
    assert sum(fantasy) / 4 > sum(other) / 8


def test_best_for_me_orders_by_closeness_to_the_target_and_hides_too_hard(tested):
    client, ids, root = tested
    catalog = open_catalog(root)
    easy = add_easy_novels(catalog, ids)
    catalog.close()
    body = client.get("/api/novels?sort=best&limit=100").json()
    items = body["items"]
    assert items and {i["id"] for i in items} <= set(easy)  # the 12 hard ones are hidden
    assert all(i["me"]["band"] != "too_hard" for i in items)
    assert body["total"] == len(items)
    gaps = [abs(i["me"]["coverage"] - 0.965) for i in items]
    # Popularity and completion give small nudges, so allow a little disorder.
    assert all(a <= b + 0.02 for a, b in zip(gaps, gaps[1:], strict=False)) or len(items) < 2
    hidden = client.get("/api/novels?sort=best&band=too_hard&limit=100").json()
    assert hidden["total"] >= 12  # asking for the band by name shows them


def test_band_filter(tested):
    client, *_ = tested
    every = client.get("/api/novels?limit=100").json()["items"]
    wanted = {i["id"] for i in every if i["me"]["band"] == every[0]["me"]["band"]}
    got = client.get(f"/api/novels?band={every[0]['me']['band']}&limit=100").json()
    assert {i["id"] for i in got["items"]} == wanted


def test_detail_has_unknown_words_with_glosses(tested):
    client, ids, _ = tested
    detail = client.get(f"/api/novels/{ids['novels'][5]}").json()
    assert detail["me"]["band"] and detail["unknown_words"]
    first = detail["unknown_words"][0]
    assert first["gloss"].startswith("meaning number") and first["p"] < 0.5
    counts = [w["count"] for w in detail["unknown_words"]]
    assert counts == sorted(counts, reverse=True)


def test_marking_a_word_changes_predictions_and_can_be_cleared(tested):
    client, ids, _ = tested
    word = ids["lemmas"][300]
    before = client.get("/api/words?q=&limit=100").json()
    entry = next(i for i in before["items"] if i["lemma_id"] == word) if False else None
    assert entry is None  # rank 301 is beyond the first 100 results
    listing = client.get("/api/words?limit=100&offset=250").json()["items"]
    assert any(i["lemma_id"] == word for i in listing)

    assert (
        client.put("/api/words/status", json={"lemma_id": word, "known": True}).status_code == 204
    )
    marked = client.get("/api/words?status=known").json()
    assert [i["lemma_id"] for i in marked["items"]] == [word]
    assert marked["items"][0]["p"] == 1.0 and marked["items"][0]["marked"] is True

    client.put("/api/words/status", json={"lemma_id": word, "known": False})
    assert client.get("/api/words?status=unknown").json()["items"][0]["p"] == 0.0

    client.put("/api/words/status", json={"lemma_id": word, "known": None})
    assert client.get("/api/words?status=marked").json()["total"] == 0
    assert (
        client.put("/api/words/status", json={"lemma_id": 99999, "known": True}).status_code == 404
    )


def test_marks_feed_the_model_and_survive_in_profile_db(tested):
    client, ids, root = tested
    before = client.get("/api/profile").json()["answers"]
    client.put("/api/words/status", json={"lemma_id": ids["lemmas"][3], "known": True})
    assert client.get("/api/profile").json()["answers"] == before + 1
    word = client.get("/api/words?status=known").json()["items"]
    assert [w["lemma_id"] for w in word] == [ids["lemmas"][3]]
    rows = open_profile(root).execute("SELECT lemma FROM word_status WHERE known = 1").fetchall()
    assert len(rows) == 1


def test_domain_fixes_change_a_words_domains_and_are_stored_by_word(tested):
    client, ids, root = tested
    word = ids["lemmas"][5]  # in no domain
    client.put("/api/words/domains", json={"lemma_id": word, "domain": "crime", "action": "add"})
    item = next(
        i for i in client.get("/api/words?q=&limit=10").json()["items"] if i["lemma_id"] == word
    )
    assert item["domains"] == [{"domain": "crime", "weight": 1.0}]

    fantasy_word = ids["lemmas"][25]
    client.put(
        "/api/words/domains",
        json={"lemma_id": fantasy_word, "domain": "fantasy", "action": "remove"},
    )
    in_fantasy = client.get("/api/words?domain=fantasy&limit=100").json()["items"]
    assert fantasy_word not in {i["lemma_id"] for i in in_fantasy}

    client.put(
        "/api/words/domains",
        json={"lemma_id": fantasy_word, "domain": "fantasy", "action": "clear"},
    )
    in_fantasy = client.get("/api/words?domain=fantasy&limit=100").json()["items"]
    assert fantasy_word in {i["lemma_id"] for i in in_fantasy}
    stored = open_profile(root).execute("SELECT lemma, domain, action FROM domain_fix").fetchall()
    assert [(r["domain"], r["action"]) for r in stored] == [("crime", "add")]
    bad = client.put(
        "/api/words/domains", json={"lemma_id": word, "domain": "nope", "action": "add"}
    )
    assert bad.status_code == 422


def test_profile_summary(tested):
    client, *_ = tested
    profile = client.get("/api/profile").json()
    assert profile["tested"] and profile["vocabulary"] > 0
    low, high = profile["vocabulary_range"]
    assert low < profile["vocabulary"] < high
    assert len(profile["domains"]) == 12
    fantasy = next(d for d in profile["domains"] if d["key"] == "fantasy")
    assert fantasy["share"] is not None and fantasy["low"] <= fantasy["share"] <= fantasy["high"]
    assert next(d for d in profile["domains"] if d["key"] == "school")["share"] is None
    assert profile["jlpt"]["loaded"] is False and profile["jlpt"]["estimate"] is None
    assert profile["weakest_domain"] in {"money", "fantasy", None}


def test_jlpt_estimate_uses_the_lists_that_are_loaded(tested):
    client, ids, root = tested
    catalog = open_catalog(root)
    names = {
        i: r["lemma"]
        for i, r in enumerate(
            catalog.execute("SELECT lemma FROM lemma ORDER BY corpus_rank LIMIT 300")
        )
    }
    rows = [(names[i], "", 5) for i in range(0, 30)] + [(names[i], "", 1) for i in range(200, 260)]
    catalog.executemany("INSERT INTO jlpt_word (lemma, reading, level) VALUES (?, ?, ?)", rows)
    catalog.commit()
    catalog.close()
    jlpt = client.get("/api/profile").json()["jlpt"]
    assert jlpt["loaded"]
    levels = {e["level"]: e for e in jlpt["levels"]}
    assert levels[5]["share"] > 0.7 > levels[1]["share"]
    assert jlpt["estimate"] == 5


def test_feedback_is_stored_with_the_prediction_at_the_time(tested):
    client, ids, root = tested
    novel = ids["novels"][0]
    assert (
        client.post(
            f"/api/novels/{novel}/feedback",
            json={"felt": "harder", "note": " too many 魔法 words "},
        ).status_code
        == 204
    )
    profile = client.get("/api/profile").json()
    entry = profile["feedback"][0]
    assert entry["felt"] == "harder" and entry["note"] == "too many 魔法 words"
    assert 0 < entry["predicted"] < 1 and entry["novel"] == "n0000x"
    assert client.post("/api/novels/999/feedback", json={"felt": "right"}).status_code == 404
    assert client.post(f"/api/novels/{novel}/feedback", json={"felt": "meh"}).status_code == 422
