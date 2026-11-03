from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from wn import config
from wn.collector import Cache
from wn.config import HostPolicy
from wn.syosetu import pipeline
from wn.syosetu.store import novel_id

FIXTURES = Path(__file__).parent / "fixtures" / "syosetu"
TODAY = date(2026, 11, 4)
TARGET = 50  # characters; each fixture chapter has 27, so two chapters per serial
CHAPTER_HOST = "https://ncode.syosetu.com"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def site():
    """A fake Syosetu: robots.txt, both APIs, and the same chapter page everywhere."""
    with respx.mock(assert_all_called=False) as router:
        router.get("https://api.syosetu.com/robots.txt").respond(404)
        router.get(f"{CHAPTER_HOST}/robots.txt").respond(
            200, text="User-agent: *\nCrawl-delay: 1\n"
        )

        def ranking(request: httpx.Request) -> httpx.Response:
            day, _, suffix = request.url.params["rtype"].partition("-")
            if suffix == "m" and day == "20261101":
                return httpx.Response(200, json=[])  # this month's list is not out yet
            return httpx.Response(
                200, text=fixture("ranking_daily.json" if suffix == "d" else "ranking_weekly.json")
            )

        router.get(url__startswith="https://api.syosetu.com/rank/rankget/").mock(
            side_effect=ranking
        )
        router.get(url__startswith="https://api.syosetu.com/novelapi/api/").respond(
            200, text=fixture("novels.json")
        )
        router.chapters = router.get(url__regex=r"https://ncode\.syosetu\.com/n\d+\w+/.*").respond(
            200, text=fixture("chapter_new.html")
        )
        yield router


@pytest.fixture
def cache(conn, tmp_path):
    return Cache(conn, tmp_path / "cache")


async def test_discover_saves_novels_and_the_newest_published_rankings(collector, conn, site):
    chosen = await pipeline.discover(collector, conn, limit=10, today=TODAY)
    assert chosen == ["n0001aa", "n0003cc", "n0004dd", "n0002bb"]
    assert conn.execute("SELECT COUNT(*) FROM novel").fetchone()[0] == 4
    lists = {
        (r["list"], r["date"])
        for r in conn.execute("SELECT DISTINCT list, date FROM ranking").fetchall()
    }
    assert ("monthly", "2026-10-01") in lists  # fell back from the empty 2026-11-01 list
    assert ("weekly", "2026-11-03") in lists and ("daily", "2026-11-03") in lists
    rank = conn.execute(
        "SELECT rank FROM ranking WHERE novel_id = ? AND list = 'weekly'",
        (novel_id(conn, "n0003cc"),),
    ).fetchone()[0]
    assert rank == 1


async def test_limit_keeps_only_the_best_ranked(collector, conn, site):
    chosen = await pipeline.discover(collector, conn, limit=2, today=TODAY)
    assert chosen == ["n0001aa", "n0003cc"]


async def test_sampling_analyses_chapters_and_forgets_their_text(collector, cache, conn, site):
    await pipeline.discover(collector, conn, limit=10, today=TODAY)
    novels = pipeline.pending_novels(conn, TARGET, deepen=False)
    assert len(novels) == 4

    result = await pipeline.sample_all(collector, cache, conn, novels, TARGET)
    assert (result.novels_done, result.stopped) == (4, None)

    by_ncode = {
        r["external_id"]: r["n"]
        for r in conn.execute(
            "SELECT n.external_id, COUNT(s.chapter_no) AS n FROM novel n"
            " LEFT JOIN sample s ON s.novel_id = n.id GROUP BY n.id"
        )
    }
    assert by_ncode["n0002bb"] == 1  # a short story is one page
    assert by_ncode["n0001aa"] == by_ncode["n0003cc"] == 2  # 2 x 27 characters reaches 50
    assert conn.execute("SELECT COUNT(*) FROM novel_stats").fetchone()[0] == 4
    assert not [r for r in cache.stats() if r["kind"] == "chapter"]  # raw text is gone
    assert conn.execute("SELECT COUNT(*) FROM novel WHERE sampled_up IS NULL").fetchone()[0] == 0


async def test_chapters_are_requested_with_the_robots_delay(collector, cache, conn, clock, site):
    await pipeline.discover(collector, conn, limit=1, today=TODAY)
    novels = [
        n for n in pipeline.pending_novels(conn, TARGET, deepen=False) if n.ncode == "n0001aa"
    ]
    await pipeline.sample_all(collector, cache, conn, novels, TARGET)
    assert site.chapters.call_count == 2
    assert 1.0 in clock.sleeps  # Crawl-delay: 1 between the two chapter pages


async def test_a_second_run_has_nothing_to_fetch(collector, cache, conn, site):
    await pipeline.discover(collector, conn, limit=10, today=TODAY)
    novels = pipeline.pending_novels(conn, TARGET, deepen=False)
    await pipeline.sample_all(collector, cache, conn, novels, TARGET)
    calls = site.chapters.call_count

    assert pipeline.pending_novels(conn, TARGET, deepen=False) == []
    await pipeline.discover(collector, conn, limit=10, today=TODAY)  # cached, unchanged
    assert pipeline.pending_novels(conn, TARGET, deepen=False) == []
    assert site.chapters.call_count == calls


async def test_an_updated_novel_is_queued_again(collector, cache, conn, site):
    await pipeline.discover(collector, conn, limit=10, today=TODAY)
    await pipeline.sample_all(
        collector, cache, conn, pipeline.pending_novels(conn, TARGET, deepen=False), TARGET
    )
    conn.execute("UPDATE novel SET last_up = '2026-11-04 00:00:00' WHERE external_id = 'n0004dd'")
    conn.execute("UPDATE sample SET chars = 1 WHERE novel_id = ?", (novel_id(conn, "n0004dd"),))
    queued = pipeline.pending_novels(conn, TARGET, deepen=False)
    assert [n.ncode for n in queued] == ["n0004dd"]


async def test_deepen_reads_opened_novels_first(collector, cache, conn, site):
    await pipeline.discover(collector, conn, limit=10, today=TODAY)
    await pipeline.sample_all(
        collector, cache, conn, pipeline.pending_novels(conn, TARGET, deepen=False), TARGET
    )
    pipeline.mark_opened(conn, "n0004dd")
    queue = pipeline.pending_novels(conn, 200, deepen=True)
    assert queue[0].ncode == "n0004dd"
    assert "n0002bb" not in [n.ncode for n in queue]  # a short story has no more pages

    calls = site.chapters.call_count
    await pipeline.sample_all(collector, cache, conn, queue, 200)
    assert site.chapters.call_count > calls
    assert sum(sampled for sampled in pipeline.sampled_chapters(conn, queue[0].id).values()) >= 200


async def test_estimate_uses_the_hosts_delay(collector, conn, site):
    await pipeline.discover(collector, conn, limit=10, today=TODAY)
    await collector.rules("ncode.syosetu.com")
    novels = pipeline.pending_novels(conn, 10_000, deepen=False)
    plan = pipeline.estimate(collector, conn, novels, 10_000)
    assert plan.novels == 4 and plan.pages > 0
    assert plan.seconds == plan.pages * 1.0  # robots.txt says Crawl-delay: 1
    assert plan.requests_left > 0


async def test_daily_cap_stops_the_run_cleanly_and_it_resumes(
    collector, cache, conn, clock, site, monkeypatch
):
    await pipeline.discover(collector, conn, limit=10, today=TODAY)
    monkeypatch.setitem(config.POLICIES, "ncode.syosetu.com", HostPolicy(5, None))
    novels = pipeline.pending_novels(conn, TARGET, deepen=False)
    first = await pipeline.sample_all(collector, cache, conn, novels, TARGET)
    assert "daily cap" in (first.stopped or "")
    assert first.novels_done < 4

    clock.now += 24 * 60 * 60
    monkeypatch.setitem(config.POLICIES, "ncode.syosetu.com", HostPolicy(3000, None))
    again = pipeline.pending_novels(conn, TARGET, deepen=False)
    assert 0 < len(again) <= 4
    rest = await pipeline.sample_all(collector, cache, conn, again, TARGET)
    assert rest.stopped is None
    assert pipeline.pending_novels(conn, TARGET, deepen=False) == []


async def test_unrecognised_pages_stop_the_run_instead_of_saving_nothing(
    collector, cache, conn, site
):
    site.chapters.respond(200, text=fixture("chapter_broken.html"))
    await pipeline.discover(collector, conn, limit=10, today=TODAY)
    novels = pipeline.pending_novels(conn, TARGET, deepen=False)
    result = await pipeline.sample_all(collector, cache, conn, novels, TARGET)
    assert "layout" in (result.stopped or "")
    assert result.novels_done == 0 and result.skipped == 3
    assert conn.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 0


async def test_a_disallowed_path_stops_the_run(collector, cache, conn, site):
    site.get(f"{CHAPTER_HOST}/robots.txt").respond(200, text="User-agent: *\nDisallow: /n0\n")
    await pipeline.discover(collector, conn, limit=10, today=TODAY)
    novels = pipeline.pending_novels(conn, TARGET, deepen=False)
    result = await pipeline.sample_all(collector, cache, conn, novels, TARGET)
    assert "robots.txt" in (result.stopped or "")
    assert site.chapters.call_count == 0


async def test_sampling_keeps_excerpts_for_the_test(collector, cache, conn, site):
    site.chapters.respond(200, text=fixture("chapter_long.html"))
    await pipeline.discover(collector, conn, limit=10, today=TODAY)
    novels = pipeline.pending_novels(conn, 200, deepen=False)
    await pipeline.sample_all(collector, cache, conn, novels, 200)
    rows = conn.execute("SELECT * FROM excerpt").fetchall()
    assert rows and all(80 <= r["chars"] <= 300 for r in rows)
    per_novel = conn.execute("SELECT COUNT(*) FROM excerpt GROUP BY novel_id").fetchall()
    assert all(r[0] <= 3 for r in per_novel)
    # Excerpts are stored in catalog.db only; the cached chapter pages are still deleted.
    assert not [r for r in cache.stats() if r["kind"] == "chapter"]


async def test_excerpts_command_fills_novels_that_have_none(collector, cache, conn, site):
    await pipeline.discover(collector, conn, limit=10, today=TODAY)
    novels = pipeline.pending_novels(conn, TARGET, deepen=False)
    await pipeline.sample_all(collector, cache, conn, novels, TARGET)  # 27-character fixtures
    assert conn.execute("SELECT COUNT(*) FROM excerpt").fetchone()[0] == 0

    site.chapters.respond(200, text=fixture("chapter_long.html"))
    missing = pipeline.novels_without_excerpts(conn)
    assert len(missing) == 4
    filled, pages = await pipeline.fill_excerpts(collector, cache, conn, missing)
    assert (filled, pages) == (4, 4)
    assert pipeline.novels_without_excerpts(conn) == []
    assert not [r for r in cache.stats() if r["kind"] == "chapter"]
