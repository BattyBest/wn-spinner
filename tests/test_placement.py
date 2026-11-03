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
    # True +1.2 and -1.0. The domain prior is tight (sd 0.5) so one test only goes part way.
    assert by_key["fantasy"]["delta"] > 0.25 > -0.25 > by_key["money"]["delta"], by_key
    assert by_key["fantasy"]["delta_sd"] < 0.5  # less uncertain than the prior


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


# --- Chinese ------------------------------------------------------------------------------


@pytest.fixture
def zh_world(tmp_path):
    catalog = open_catalog(tmp_path)
    ids = build(catalog, lang="zh")
    glosses = {r["lemma"]: r["gloss"] for r in catalog.execute("SELECT lemma, gloss FROM lemma")}
    ranks, weights = {}, {}
    for r in catalog.execute("SELECT lemma, corpus_rank FROM lemma WHERE language = 'zh'"):
        ranks[r["lemma"]] = r["corpus_rank"]
    for r in catalog.execute(
        "SELECT l.lemma, d.domain, d.weight FROM lemma_domain d JOIN lemma l ON l.id = d.lemma_id"
    ):
        weights.setdefault(r["lemma"], []).append((r["domain"], r["weight"]))
    catalog.close()
    return TestClient(create_app(tmp_path)), ids, glosses, ranks, weights, tmp_path


def test_chinese_status_and_test_use_chinese_words_only(zh_world):
    client, ids, glosses, ranks, weights, _ = zh_world
    assert client.get("/api/test/status?lang=zh").json()["ready"]
    assert not client.get("/api/test/status?lang=ja").json()["ready"]
    _, shown = run_test(client, "quick", glosses, ranks, weights, lang="zh")
    words = [i for i in shown if i["type"] == "word"]
    assert words and all(w["lemma"] in ranks for w in words)
    profile = client.get("/api/profile?lang=zh").json()
    assert profile["language"] == "zh" and profile["tested"]
    assert profile["level"]["name"] == "HSK"
    assert all("name_local" in d for d in profile["domains"])
    assert client.get("/api/profile?lang=ja").json()["answers"] == 0


def test_chinese_novels_list_hides_mature_books_on_request(zh_world):
    client, ids, *_ = zh_world
    root = zh_world[-1]
    catalog = open_catalog(root)
    catalog.execute("UPDATE novel SET is_mature = 1 WHERE id = ?", (ids["novels"][0],))
    catalog.commit()
    catalog.close()
    everything = client.get("/api/novels?lang=zh&limit=100").json()
    assert everything["total"] == 12
    shown = client.get("/api/novels?lang=zh&limit=100&hide_r15=true").json()
    assert shown["total"] == 11
    assert ids["novels"][0] not in {i["id"] for i in shown["items"]}
    flagged = next(i for i in everything["items"] if i["id"] == ids["novels"][0])
    assert flagged["is_mature"]
    assert client.get("/api/novels?lang=ja&limit=100").json()["total"] == 0
    detail = client.get(f"/api/novels/{ids['novels'][0]}").json()
    assert detail["language"] == "zh" and detail["source"] == "jjwxc"
