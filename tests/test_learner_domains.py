import json

from wn.learner import domains
from wn.learner.domains import GROUPS, rebuild_domains, tag_domains
from wn.learner.excerpts import candidates, pick, save_excerpts

from .synthetic import build


def boost(conn, ids, lemma_ids):
    """Make these words much more common in the four fantasy-genre novels."""
    marks = ",".join(str(i) for i in lemma_ids)
    novels = ",".join(str(n) for n in ids["novels"][:4])
    conn.execute(
        "UPDATE novel_lemma SET count = count + 40"
        f" WHERE novel_id IN ({novels}) AND lemma_id IN ({marks})"
    )


def test_tags_map_to_domains():
    assert tag_domains("chem col") == {"science", "speech"}
    assert tag_domains("uk") == set()
    assert tag_domains(None) == set()


def test_every_domain_key_has_a_group_and_a_database_row(conn):
    in_db = [r[0] for r in conn.execute("SELECT key FROM domain ORDER BY position")]
    assert tuple(in_db) == domains.DOMAIN_KEYS
    assert set(GROUPS) == set(domains.DOMAIN_KEYS)


def test_dictionary_tags_give_weight_one(conn):
    ids = build(conn)
    conn.execute("DELETE FROM lemma_domain")
    conn.execute("UPDATE lemma SET tags = 'med' WHERE id = ?", (ids["lemmas"][50],))
    rebuild_domains(conn)
    row = conn.execute(
        "SELECT weight, source FROM lemma_domain WHERE lemma_id = ? AND domain = 'medicine'",
        (ids["lemmas"][50],),
    ).fetchone()
    assert (row["weight"], row["source"]) == (1.0, "dictionary")


def test_words_over_used_by_one_genre_group_are_learned(conn):
    ids = build(conn)
    # In the fantasy group (novels 0-3) words 20..59 are used much more than elsewhere.
    # Give the other genres a clearly flatter profile, and make the group big enough.
    conn.execute("DELETE FROM lemma_domain")
    boosted = set(ids["lemmas"][20:60])
    boost(conn, ids, boosted)
    report = rebuild_domains(conn)
    assert report.groups["fantasy"] == 4
    assert "fantasy" not in report.skipped
    learned = {
        r["lemma_id"]: r["weight"]
        for r in conn.execute("SELECT * FROM lemma_domain WHERE domain = 'fantasy'")
    }
    assert learned and set(learned) <= boosted
    assert all(0.3 <= w <= 0.8 for w in learned.values())
    # Words outside the boosted set are not tagged, and groups with no novels are skipped.
    assert not set(ids["lemmas"][100:]) & set(learned)
    assert "school" in report.skipped


def test_a_dictionary_tag_beats_a_learned_one(conn):
    ids = build(conn)
    conn.execute("DELETE FROM lemma_domain")
    boosted = ids["lemmas"][20:60]
    boost(conn, ids, boosted)
    conn.execute("UPDATE lemma SET tags = 'myth' WHERE id = ?", (boosted[0],))
    rebuild_domains(conn)
    row = conn.execute(
        "SELECT weight, source FROM lemma_domain WHERE lemma_id = ? AND domain = 'fantasy'",
        (boosted[0],),
    ).fetchone()
    assert (row["weight"], row["source"]) == (1.0, "dictionary")


# --- excerpts -----------------------------------------------------------------------------

TEXT = (
    "空は高く晴れていた。村の人々は朝早くから畑に出て、静かに働いていた。"
    "遠くの山には雪が残り、風はまだ冷たかった。少年は古い剣を背負って、長い道を歩き始めた。"
    "「どこへ行くのですか」と老人が尋ねると、少年は黙って北の空を指さした。"
    "その夜、彼は小さな宿で眠れずに、窓の外の星を数えていた。"
)


def test_candidates_are_whole_sentences_within_the_limits():
    found = candidates(TEXT)
    assert found
    assert all(80 <= len(c) <= 300 for c in found)
    assert all(c.endswith(("。", "」")) for c in found)


def test_pick_spreads_through_the_text_and_never_repeats():
    chosen = pick(TEXT, 3)
    assert 1 <= len(chosen) <= 3 and len(set(chosen)) == len(chosen)
    assert pick("短い。", 3) == []
    assert pick(TEXT, 0) == []


def test_save_excerpts_stores_tokens_and_stops_at_three(conn):
    ids = build(conn)
    novel = ids["novels"][0]
    conn.execute("DELETE FROM excerpt")
    saved = save_excerpts(conn, novel, 1, TEXT, want=3)
    assert 1 <= saved <= 3
    row = conn.execute("SELECT * FROM excerpt WHERE novel_id = ?", (novel,)).fetchone()
    tokens = json.loads(row["tokens"])
    assert "".join(t[0] for t in tokens) == row["text"]
    assert save_excerpts(conn, novel, 2, TEXT, want=3) == 0 or (
        conn.execute("SELECT COUNT(*) FROM excerpt WHERE novel_id = ?", (novel,)).fetchone()[0] <= 3
    )
    for _ in range(3):
        save_excerpts(conn, novel, 3, TEXT + "月は静かに沈み、朝が来た。" * 4, want=3)
    assert (
        conn.execute("SELECT COUNT(*) FROM excerpt WHERE novel_id = ?", (novel,)).fetchone()[0] <= 3
    )
