from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wn.analysis.japanese import analyse_text
from wn.analysis.store import rebuild_all, save_sample
from wn.api.app import create_app
from wn.db import open_catalog
from wn.syosetu.api import RankEntry, parse_novels
from wn.syosetu.store import novel_id, save_ranking, upsert_novel

FIXTURES = Path(__file__).parent / "fixtures" / "syosetu"


@pytest.fixture
def client(tmp_path):
    conn = open_catalog(tmp_path)
    for meta in parse_novels((FIXTURES / "novels.json").read_bytes()):
        upsert_novel(conn, meta)
    sentences = {
        "n0001aa": "魔王は城を出た。「どこへ行くのですか」と勇者は尋ねた。",
        "n0003cc": "彼女は静かに笑った。",
    }
    for ncode, text in sentences.items():
        save_sample(conn, novel_id(conn, ncode), 1, analyse_text(text))
    rebuild_all(conn)
    save_ranking(conn, "n0001aa", "daily", date(2026, 11, 3), RankEntry("n0001aa", 1, 5200))
    save_ranking(conn, "n0001aa", "daily", date(2026, 11, 2), RankEntry("n0001aa", 4, 4000))
    conn.close()
    return TestClient(create_app(tmp_path))


def ncodes(body) -> list[str]:
    return [i["ncode"] for i in body["items"]]


def test_list_defaults_to_popularity(client):
    body = client.get("/api/novels").json()
    assert body["total"] == 4
    assert ncodes(body) == ["n0001aa", "n0003cc", "n0002bb", "n0004dd"]
    first = body["items"][0]
    assert first["title"] == "テスト魔王の冒険" and first["is_r15"] is False
    assert first["stats"]["sample_chars"] > 0 and 0 < first["stats"]["cover_3k"] <= 1
    assert body["items"][2]["stats"] is None  # not sampled yet


def test_filters(client):
    def ask(**params):
        return ncodes(client.get("/api/novels", params=params).json())

    assert ask(completed=True) == ["n0003cc", "n0002bb"]
    assert "n0003cc" not in ask(hide_r15=True)
    assert ask(genre="ヒューマンドラマ〔文芸〕") == ["n0002bb"]
    assert ask(min_length=100000) == ["n0001aa", "n0003cc"]
    assert ask(max_length=10000) == ["n0002bb"]
    assert ask(q="魔王") == ["n0001aa"]
    assert ask(min_cover_3k=0.5) != []
    assert client.get("/api/novels", params={"min_cover_3k": 2}).status_code == 422


def test_sorting_and_paging(client):
    def ask(**params):
        return ncodes(client.get("/api/novels", params=params).json())

    assert set(ask(sort="easiest")[:2]) == {"n0001aa", "n0003cc"}  # the analysed ones first
    assert ask(sort="length")[0] == "n0001aa"
    assert ask(sort="updated")[0] == "n0001aa"
    page = client.get("/api/novels", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 4 and ncodes(page) == ["n0002bb", "n0004dd"]


def test_detail(client):
    listing = client.get("/api/novels").json()["items"][0]
    detail = client.get(f"/api/novels/{listing['id']}").json()
    assert detail["synopsis"].startswith("魔王が旅に出る")
    assert detail["keywords"] == "異世界 魔王 冒険"
    assert detail["url"] == "https://ncode.syosetu.com/n0001aa/"
    assert [p["words"] for p in detail["curve"]] == [0, 1000, 2000, 3000, 5000, 10000]
    covers = [p["cover"] for p in detail["curve"]]
    assert covers == sorted(covers) and covers[0] == 0.0
    assert detail["rankings"] == [
        {"list": "daily", "date": "2026-11-03", "rank": 1, "points": 5200}
    ]
    assert detail["stats"]["tokens"] > 0 and detail["site_dialogue_pct"] == 41


def test_detail_of_an_unanalysed_novel_and_a_missing_one(client):
    short = next(i for i in client.get("/api/novels").json()["items"] if i["ncode"] == "n0002bb")
    detail = client.get(f"/api/novels/{short['id']}").json()
    assert detail["stats"] is None and detail["curve"] == [] and detail["rare_words"] == []
    assert client.get("/api/novels/999").status_code == 404


def test_opening_a_novel_is_remembered(client, tmp_path):
    item = client.get("/api/novels").json()["items"][2]
    assert client.post(f"/api/novels/{item['id']}/open").status_code == 204
    assert client.post("/api/novels/999/open").status_code == 404
    conn = open_catalog(tmp_path)
    assert conn.execute("SELECT opened_at FROM novel WHERE id = ?", (item["id"],)).fetchone()[0]


def test_genres_and_status(client):
    genres = {g["genre"]: g["novels"] for g in client.get("/api/genres").json()}
    assert genres["ハイファンタジー〔ファンタジー〕"] == 1 and len(genres) == 4
    status = client.get("/api/collect/status").json()
    assert (status["novels"], status["sampled"], status["analysed"]) == (4, 2, 2)
    assert status["last_sample_at"] is not None
    hosts = {h["host"]: h for h in status["hosts"]}
    assert hosts["api.syosetu.com"]["requests_left"] == 2000
