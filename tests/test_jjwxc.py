from datetime import date

import httpx
import pytest
import respx

from wn.collector import Cache
from wn.jjwxc import pages, pipeline
from wn.sampling import ParseError

from .jjwxc_site import book_page, chapter_page, ranking_page, story

TODAY = date(2026, 11, 4)
BOOKS = {"101": "甲书", "102": "乙书", "103": "丙书"}


def test_free_chapter_urls_are_only_plain_free_chapters():
    url = pages.free_chapter_url(101, 7)
    assert url == "https://www.jjwxc.net/onebook.php?novelid=101&chapterid=7"
    assert pages.is_free_chapter_url(url)
    for bad in (
        "https://my.jjwxc.net/onebook_vip.php?novelid=101&chapterid=7",
        "https://www.jjwxc.net/onebook_vip.php?novelid=101&chapterid=7",
        "https://www.jjwxc.net/onebook.php?novelid=101&chapterid=7&token=x",
        "https://www.jjwxc.net/login.php",
    ):
        assert not pages.is_free_chapter_url(bad)


def test_parse_ranking_and_merge_round_robin():
    entries = pages.parse_ranking(ranking_page([("1", "甲"), ("2", "乙"), ("3", "丙")]))
    assert [e.novel_id for e in entries] == ["1", "2", "3"]
    assert entries[0].title == "甲" and entries[0].status == "ongoing"
    assert entries[0].words == 1_200_000
    other = pages.parse_ranking(ranking_page([("3", "丙"), ("4", "丁")]))
    merged = pages.merge_rankings({"a": entries, "b": other}, 10)
    assert merged == ["1", "3", "2", "4"]
    assert pages.merge_rankings({"a": entries, "b": other}, 2) == ["1", "3"]


def test_parse_book_reads_metadata_and_tells_free_from_vip():
    meta = pages.parse_book(book_page(101, "甲书", free=3, vip=2), 101)
    assert (meta.title, meta.author, meta.status) == ("甲书", "某某", "ongoing")
    assert meta.genre == "近代现代-爱情"
    assert meta.tags == ["甜文", "都市"] and meta.perspective == "女主"
    assert (meta.favourites, meta.points) == (4321, 1_234_567)
    assert meta.last_up == "2026-10-20 12:00:00"
    assert not meta.is_mature
    assert [c.chapter_id for c in meta.free] == [1, 2, 3]
    assert len(meta.chapters) == 5
    assert "甜文" in meta.keywords and "女主" in meta.keywords
    assert meta.synopsis.startswith("一个关于重逢的故事")


def test_mature_books_are_flagged():
    assert pages.parse_book(book_page(5, "戊书", mature=True), 5).is_mature


def test_a_page_without_a_title_is_a_parse_error():
    with pytest.raises(ParseError):
        pages.parse_book("<html></html>".encode("gb18030"), 1)


def test_parse_chapter_drops_header_lines():
    text = pages.parse_chapter(chapter_page(story(3)))
    assert text.splitlines()[0].startswith("她推开窗户")
    assert "《" not in text.splitlines()[0]


def test_garbled_or_missing_chapters_are_refused():
    with pytest.raises(ParseError):
        pages.parse_chapter(b"<html></html>")
    with pytest.raises(ParseError):
        pages.parse_chapter("<div id='paragraph_comment_content'>她推开\ufffd窗户</div>")


@pytest.fixture
def site():
    with respx.mock(assert_all_called=False) as router:
        router.get("https://www.jjwxc.net/robots.txt").respond(200, text="User-agent: *\n")

        def ranking(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=ranking_page(list(BOOKS.items())))

        router.get(url__startswith="https://www.jjwxc.net/topten.php").mock(side_effect=ranking)

        def book(request: httpx.Request) -> httpx.Response:
            nid = request.url.params["novelid"]
            if "chapterid" in request.url.params:
                return httpx.Response(200, content=chapter_page(story(12)))
            return httpx.Response(200, content=book_page(int(nid), BOOKS[nid], mature=nid == "103"))

        router.books = router.get(url__regex=r"https://www\.jjwxc\.net/onebook\.php.*").mock(
            side_effect=book
        )
        yield router


@pytest.fixture
def cache(conn, tmp_path):
    return Cache(conn, tmp_path / "cache")


async def test_discover_and_sample_never_request_anything_but_free_chapters(
    collector, cache, conn, site
):
    chosen = await pipeline.discover(collector, conn, limit=10, today=TODAY)
    assert sorted(chosen) == ["101", "102", "103"]
    rows = conn.execute("SELECT external_id, is_mature, favourites FROM novel").fetchall()
    assert {r["external_id"]: r["is_mature"] for r in rows} == {"101": 0, "102": 0, "103": 1}
    assert all(r["favourites"] == 4321 for r in rows)

    novels = pipeline.pending_novels(conn, 400, deepen=False)
    assert len(novels) == 3
    result = await pipeline.sample_all(collector, cache, conn, novels, 400)
    assert (result.novels_done, result.stopped) == (3, None)
    assert conn.execute("SELECT COUNT(*) FROM novel_stats").fetchone()[0] == 3
    assert not [r for r in cache.stats() if r["kind"] == "chapter"]

    for call in site.calls:
        url = str(call.request.url)
        assert "vip" not in url.lower() and "login" not in url and "my.jjwxc.net" not in url
        if "chapterid" in url:
            assert pages.is_free_chapter_url(url)
            chapter = int(call.request.url.params["chapterid"])
            assert chapter <= 3  # chapters 4 and 5 are VIP in the fixture
    stats = conn.execute("SELECT idiom_rate FROM novel_stats").fetchall()
    assert all(s["idiom_rate"] is not None for s in stats)


async def test_a_second_run_has_nothing_to_fetch(collector, cache, conn, site):
    await pipeline.discover(collector, conn, limit=10, today=TODAY)
    await pipeline.sample_all(
        collector, cache, conn, pipeline.pending_novels(conn, 400, deepen=False), 400
    )
    assert pipeline.pending_novels(conn, 400, deepen=False) == []
    assert pipeline.finish(conn)
