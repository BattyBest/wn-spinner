from datetime import date
from pathlib import Path

from wn.syosetu.api import RankEntry, parse_novels
from wn.syosetu.store import known_ncodes, save_ranking, upsert_novel

FIXTURES = Path(__file__).parent / "fixtures" / "syosetu"


def test_upsert_refreshes_without_touching_the_sampled_stamp(conn):
    novels = {n.ncode: n for n in parse_novels((FIXTURES / "novels.json").read_bytes())}
    first = upsert_novel(conn, novels["n0001aa"])
    conn.execute("UPDATE novel SET sampled_up = ? WHERE id = ?", ("2026-10-30 08:00:00", first))

    novels["n0001aa"].points = 60000
    novels["n0001aa"].last_up = "2026-11-02 09:00:00"
    again = upsert_novel(conn, novels["n0001aa"])

    assert again == first
    row = conn.execute("SELECT * FROM novel WHERE id = ?", (first,)).fetchone()
    assert (row["points"], row["last_up"]) == (60000, "2026-11-02 09:00:00")
    assert row["sampled_up"] == "2026-10-30 08:00:00"  # now differs from last_up
    assert row["kind"] == "serial" and row["url"] == "https://ncode.syosetu.com/n0001aa/"
    assert conn.execute("SELECT COUNT(*) FROM novel").fetchone()[0] == 1


def test_rankings_and_known_ncodes(conn):
    novels = parse_novels((FIXTURES / "novels.json").read_bytes())
    for meta in novels:
        upsert_novel(conn, meta)
    save_ranking(conn, "n0001aa", "daily", date(2026, 11, 3), RankEntry("n0001aa", 1, 5200))
    save_ranking(conn, "n0001aa", "daily", date(2026, 11, 3), RankEntry("n0001aa", 2, 5100))
    rows = conn.execute("SELECT rank, points FROM ranking").fetchall()
    assert [tuple(r) for r in rows] == [(2, 5100)]
    assert known_ncodes(conn) == {"n0001aa", "n0002bb", "n0003cc", "n0004dd"}
