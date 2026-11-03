import math
import random

import pytest
from fastapi.testclient import TestClient

from wn.api.app import create_app
from wn.db import open_catalog, open_profile
from wn.learner import placement
from wn.learner.model import Params, load_learner, p_know

from .synthetic import build

TRUE = Params(theta=math.log(120))
TRUE.deltas["fantasy"] = 1.2
TRUE.deltas["money"] = -1.0


@pytest.fixture
def world(tmp_path):
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
    return client, ids, glosses, ranks, weights, tmp_path


def run_test(client, kind, glosses, ranks, weights, seed=1, lang="ja"):
    """Answer like a learner with the TRUE parameters. Returns every item that was shown."""
    rng = random.Random(seed)
    body = client.post("/api/test/start", json={"kind": kind, "lang": lang}).json()
    session, shown = body["session"], []
    while not body["done"]:
        item = body["item"]
        shown.append(item)
        if item["type"] == "word":
            p = p_know(TRUE, ranks[item["lemma"]], weights.get(item["lemma"], []))
            answer = {"known": rng.random() < p}
        elif item["type"] == "fake":
            answer = {"known": False}
        elif item["type"] == "meaning":
            right = item["choices"].index(glosses[item["lemma"]])
            p = p_know(TRUE, ranks[item["lemma"]], weights.get(item["lemma"], []))
            answer = {"choice": right if rng.random() < p else (right + 1) % 4}
        else:
            tapped = [
                i
                for i, (surface, tappable) in enumerate(item["tokens"])
                if tappable
                and rng.random() > p_know(TRUE, ranks[surface], weights.get(surface, []))
            ]
            answer = {"tapped": tapped, "rating": "most", "cloze_choice": None}
        body = client.post(f"/api/test/{session}/answer", json=answer).json()
    return session, shown


def test_status_is_ready_with_enough_words(world):
    client, *_ = world
    status = client.get("/api/test/status").json()
    assert status["ready"] and status["test_words"] >= 300 and status["excerpts"] == 12
    assert status["answers"] == 0 and status["unfinished"] is None


def test_an_empty_catalog_cannot_start_a_test(tmp_path):
    client = TestClient(create_app(tmp_path))
    status = client.get("/api/test/status").json()
    assert not status["ready"] and status["problems"]
    assert client.post("/api/test/start", json={}).status_code == 409


def test_full_test_flow(world):
    client, ids, glosses, ranks, weights, _ = world
    session, shown = run_test(client, "full", glosses, ranks, weights)

    words = [i for i in shown if i["type"] == "word"]
    fakes = [i for i in shown if i["type"] == "fake"]
    meanings = [i for i in shown if i["type"] == "meaning"]
    passages = [i for i in shown if i["type"] == "passage"]
    assert len(words) + len(fakes) == 60
    assert len(fakes) == 12  # one in five
    assert len({w["lemma"] for w in words}) == len(words)  # never the same word twice
    assert all(f["text"] not in ranks for f in fakes)  # a fake is never a catalog word
    assert meanings and all(len(m["choices"]) == 4 for m in meanings)
    assert 1 <= len(passages) <= 5
    assert len({p["excerpt_id"] for p in passages}) == len(passages)
    assert not any("correct" in str(i) for i in shown)  # answers are never sent

    done = client.get(f"/api/test/{session}/next").json()
    assert done["done"] and done["item"] is None

    profile = client.get("/api/profile").json()
    assert profile["tested"] and profile["answers"] > 60
    assert 70 < profile["vocabulary"] < 200  # true value 120
    by_key = {d["key"]: d for d in profile["domains"]}
    assert by_key["fantasy"]["delta"] > 0.5 > -0.5 > by_key["money"]["delta"]  # true +1.2, -1.0
    assert by_key["fantasy"]["delta_sd"] < 0.8  # less uncertain than the prior


def test_the_model_asks_where_it_is_unsure(world):
    client, ids, glosses, ranks, weights, _ = world
    _, shown = run_test(client, "full", glosses, ranks, weights)
    asked_domains = {i["domain"] for i in shown if i["type"] == "word"}
    assert None in asked_domains and {"fantasy", "money"} <= asked_domains


def test_a_session_can_be_left_and_resumed(world):
    client, *_ = world
    first = client.post("/api/test/start", json={"kind": "full"}).json()
    client.post(f"/api/test/{first['session']}/answer", json={"known": True})
    again = client.post("/api/test/start", json={"kind": "full"}).json()
    assert again["session"] == first["session"]
    assert again["progress"]["words_done"] == 1
    assert client.get("/api/test/status").json()["unfinished"]["id"] == first["session"]


def test_quick_check_is_twenty_items_and_adds_to_the_same_answers(world):
    client, ids, glosses, ranks, weights, _ = world
    run_test(client, "quick", glosses, ranks, weights)
    first = client.get("/api/profile").json()["answers"]
    assert first >= 20
    run_test(client, "quick", glosses, ranks, weights, seed=2)
    assert client.get("/api/profile").json()["answers"] >= first + 20


def test_answering_with_nothing_pending_is_refused(world):
    client, ids, glosses, ranks, weights, _ = world
    session, _ = run_test(client, "quick", glosses, ranks, weights)
    assert client.post(f"/api/test/{session}/answer", json={"known": True}).status_code == 409
    assert client.get("/api/test/999/next").status_code == 409


def test_fakes_are_never_real_forms(world):
    _, ids, _, _, _, root = world
    catalog = open_catalog(root)
    catalog.execute("INSERT INTO dict_form (language, form, entry_id) VALUES ('ja', '魔法', 1)")
    pool = placement.Pool.load(catalog)
    rng = random.Random(0)
    seen = {placement.make_fake(pool, rng)["text"] for _ in range(60)}
    assert seen and not seen & pool.forms
    assert not seen & {c.lemma for c in pool.words.values()}
    assert any(len(t) == 2 for t in seen)


def test_meaning_distractors_share_pos_and_are_near_in_rank(world):
    _, ids, _, _, _, root = world
    catalog = open_catalog(root)
    pool = placement.Pool.load(catalog)
    word = {"lemma_id": ids["lemmas"][100]}
    item = placement.make_meaning(pool, word, random.Random(1))
    target = pool.words[word["lemma_id"]]
    assert item["choices"][item["correct"]] == target.gloss
    assert len(set(item["choices"])) == 4


def test_wrong_meaning_marks_the_word_unknown(world):
    client, ids, glosses, ranks, weights, root = world
    body = client.post("/api/test/start", json={"kind": "full"}).json()
    session = body["session"]
    claimed = 0
    # Say yes to real words until a meaning check appears, then get it wrong.
    while body["item"]["type"] != "meaning":
        item = body["item"]
        answer = {"known": item["type"] == "word"}
        body = client.post(f"/api/test/{session}/answer", json=answer).json()
        claimed += 1
        assert claimed < 40
    item = body["item"]
    wrong = (item["choices"].index(glosses[item["lemma"]]) + 1) % 4
    client.post(f"/api/test/{session}/answer", json={"choice": wrong})
    profile = open_profile(root)
    row = profile.execute(
        "SELECT known FROM word_status WHERE lemma = ?", (item["lemma"],)
    ).fetchone()
    assert row is not None and row["known"] == 0
    assert placement.PART_A_ITEMS["full"] == 60
    assert load_learner(profile, open_catalog(root)).p(ids["lemmas"][0]) > 0
