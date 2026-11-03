from pathlib import Path

import pytest

from wn.syosetu.chapter import ParseError, chapter_url, next_chapter, parse_chapter

FIXTURES = Path(__file__).parent / "fixtures" / "syosetu"


def test_story_body_only_without_ruby_or_extras():
    chapter = parse_chapter((FIXTURES / "chapter_new.html").read_bytes())
    assert chapter.title == "第一話　旅立ち"
    assert chapter.text.splitlines() == [
        "魔王は城を出た。",
        "",
        "「どこへ行くのですか」と勇者は尋ねた。",
    ]
    assert "前書き" not in chapter.text and "後書き" not in chapter.text
    assert chapter.chars == len("魔王は城を出た。「どこへ行くのですか」と勇者は尋ねた。")


def test_older_layout_is_still_read():
    chapter = parse_chapter((FIXTURES / "chapter_old.html").read_text(encoding="utf-8"))
    assert chapter.text == "旧式のページです。\n本文はここにあります。"
    assert chapter.title == "第二話"


def test_unknown_layout_fails_loudly():
    with pytest.raises(ParseError):
        parse_chapter((FIXTURES / "chapter_broken.html").read_bytes())


def test_urls():
    assert chapter_url("n0001aa", 3, "serial") == "https://ncode.syosetu.com/n0001aa/3/"
    assert chapter_url("n0002bb", 1, "short") == "https://ncode.syosetu.com/n0002bb/"


def test_reads_in_order_until_the_target_is_met():
    assert next_chapter("serial", 50, {}, 10_000) == 1
    assert next_chapter("serial", 50, {1: 3000}, 10_000) == 2
    assert next_chapter("serial", 50, {1: 3000, 2: 3000, 3: 4000}, 10_000) is None


def test_short_story_is_one_page():
    assert next_chapter("short", 1, {}, 10_000) == 1
    assert next_chapter("short", 1, {1: 4000}, 10_000) is None


def test_serial_with_few_chapters_stops_at_the_end():
    assert next_chapter("serial", 2, {1: 500, 2: 500}, 10_000) is None


def test_deepen_takes_one_middle_chapter_once_half_the_target_is_read():
    done = {1: 4000, 2: 4000, 3: 3000}  # 11,000 of 20,000
    assert next_chapter("serial", 100, done, 20_000) == 50
    done[50] = 3000
    assert next_chapter("serial", 100, done, 20_000) == 4


def test_stops_after_the_page_cap():
    done = {n: 10 for n in range(1, 13)}
    assert next_chapter("serial", 100, done, 20_000) is None
