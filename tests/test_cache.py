import gzip

from wn.collector import Cache
from wn.db import open_catalog


def test_round_trip_and_expiry(tmp_path):
    conn = open_catalog(tmp_path)
    cache = Cache(conn, tmp_path / "cache")
    cache.put("https://a.test/x", "page", 200, "本文".encode(), now=100.0)

    page = cache.get("https://a.test/x", max_age=None, now=10_000.0)
    assert page is not None and page.body.decode() == "本文"
    assert cache.get("https://a.test/x", max_age=60, now=110.0) is not None
    assert cache.get("https://a.test/x", max_age=60, now=200.0) is None
    assert cache.get("https://a.test/missing", max_age=None) is None


def test_files_are_gzipped_on_disk(tmp_path):
    conn = open_catalog(tmp_path)
    cache = Cache(conn, tmp_path / "cache")
    cache.put("https://a.test/x", "page", 200, b"hello")
    (path,) = (tmp_path / "cache").rglob("*.gz")
    assert gzip.decompress(path.read_bytes()) == b"hello"


def test_stats_and_purge_by_kind(tmp_path):
    conn = open_catalog(tmp_path)
    cache = Cache(conn, tmp_path / "cache")
    cache.put("https://a.test/robots.txt", "robots", 200, b"abc")
    cache.put("https://a.test/1", "chapter", 200, b"12345")
    cache.put("https://a.test/2", "chapter", 200, b"12345")
    stats = {(r["host"], r["kind"]): r for r in cache.stats()}
    assert stats[("a.test", "chapter")]["pages"] == 2
    assert stats[("a.test", "chapter")]["bytes"] == 10

    assert cache.purge("chapter") == 2
    assert len(list((tmp_path / "cache").rglob("*.gz"))) == 1
    assert cache.get("https://a.test/robots.txt", max_age=None) is not None
    assert cache.purge() == 1
    assert cache.stats() == []
