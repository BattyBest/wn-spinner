from fastapi.testclient import TestClient

from wn.api.app import create_app


def test_health(tmp_path):
    client = TestClient(create_app(tmp_path))
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["catalog_version"] == 3 and body["profile_version"] == 2


def test_stats_on_an_empty_catalog(tmp_path):
    client = TestClient(create_app(tmp_path))
    body = client.get("/api/stats").json()
    assert body["novels"] == 0 and body["cache_pages"] == 0
    assert [s["name"] for s in body["sources"]] == ["jjwxc", "syosetu"]


def test_startup_creates_both_databases(tmp_path):
    create_app(tmp_path / "fresh")
    assert (tmp_path / "fresh" / "catalog.db").exists()
    assert (tmp_path / "fresh" / "profile.db").exists()
