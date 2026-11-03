from datetime import date
from pathlib import Path

import pytest

from wn.syosetu.api import (
    ApiError,
    RankEntry,
    merge_rankings,
    novel_url,
    parse_novels,
    parse_ranking,
    rank_dates,
    rank_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "syosetu"


def read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_ranking_entries_are_lowercased_and_sorted():
    entries = parse_ranking(read("ranking_weekly.json"))
    assert [e.ncode for e in entries] == ["n0003cc", "n0004dd", "n0001aa"]
    assert entries[0] == RankEntry("n0003cc", 1, 21000)


def test_empty_ranking_means_not_published_yet():
    assert parse_ranking(b"[]") == []


def test_bad_json_is_an_api_error():
    with pytest.raises(ApiError):
        parse_ranking(b"<html>maintenance</html>")


def test_merge_uses_best_position_then_number_of_lists():
    lists = {
        "daily": parse_ranking(read("ranking_daily.json")),
        "weekly": parse_ranking(read("ranking_weekly.json")),
    }
    # n0001aa and n0003cc both reach rank 1 somewhere; n0003cc is on both lists too,
    # but so is n0001aa, so the tie falls through to the ncode.
    assert merge_rankings(lists, 10) == ["n0001aa", "n0003cc", "n0002bb", "n0004dd"]
    assert merge_rankings(lists, 2) == ["n0001aa", "n0003cc"]


def test_ranking_dates_follow_each_lists_calendar():
    today = date(2026, 11, 4)  # a Wednesday
    assert rank_dates("daily", today) == [date(2026, 11, 3), date(2026, 11, 2)]
    weekly = rank_dates("weekly", today)
    assert weekly == [date(2026, 11, 3), date(2026, 10, 27)]
    assert all(d.weekday() == 1 for d in weekly)  # Tuesdays
    assert rank_dates("monthly", today) == [date(2026, 11, 1), date(2026, 10, 1)]
    assert rank_dates("quarterly", today) == [date(2026, 10, 1), date(2026, 7, 1)]
    assert rank_dates("monthly", date(2027, 1, 15)) == [date(2027, 1, 1), date(2026, 12, 1)]


def test_ranking_dates_on_a_tuesday_use_the_previous_one():
    assert rank_dates("weekly", date(2026, 11, 3))[0] == date(2026, 10, 27)


def test_ranking_url():
    url = rank_url("weekly", date(2026, 11, 3))
    assert url == "https://api.syosetu.com/rank/rankget/?out=json&rtype=20261103-w"


def test_novel_fields():
    novels = {n.ncode: n for n in parse_novels(read("novels.json"))}
    assert set(novels) == {"n0001aa", "n0002bb", "n0003cc", "n0004dd"}

    serial = novels["n0001aa"]
    assert (serial.kind, serial.status, serial.chapter_count) == ("serial", "ongoing", 120)
    assert serial.genre == "ハイファンタジー〔ファンタジー〕"
    assert (serial.points, serial.bookmarks, serial.site_dialogue_pct) == (52000, 9000, 41)
    assert serial.url == "https://ncode.syosetu.com/n0001aa/"

    short = novels["n0002bb"]
    assert (short.kind, short.status, short.chapter_count) == ("short", "completed", 1)

    done = novels["n0003cc"]
    assert (done.status, done.is_r15) == ("completed", True)

    assert novels["n0004dd"].status == "hiatus"


def test_novel_url_sorts_and_limits_ncodes():
    assert novel_url(["n2", "n1"]).endswith("&lim=2&ncode=n1-n2")
    with pytest.raises(ValueError):
        novel_url([])
    with pytest.raises(ValueError):
        novel_url([f"n{i}" for i in range(101)])
