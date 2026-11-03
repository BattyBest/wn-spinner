from wn.analysis.japanese import NAME_POS, analyse_text, dialogue_chars
from wn.analysis.store import (
    compute_stats,
    rare_words,
    rebuild_all,
    rebuild_frequency,
    sampled_chapters,
    save_sample,
)
from wn.syosetu.api import NovelMeta
from wn.syosetu.store import upsert_novel


def lemmas(analysis) -> dict[str, int]:
    out: dict[str, int] = {}
    for word, count in analysis.counts.items():
        out[word.lemma] = out.get(word.lemma, 0) + count
    return out


def test_conjugated_forms_collapse_to_one_lemma():
    counts = lemmas(analyse_text("食べた。食べない。たべます。"))
    assert counts["食べる"] == 3


def test_function_words_are_counted_but_marked():
    analysis = analyse_text("魔王は城を出た。")
    by_lemma = {w.lemma: w for w in analysis.counts}
    assert by_lemma["は"].is_function and by_lemma["を"].is_function
    assert not by_lemma["魔王"].is_function
    assert by_lemma["城"].reading == "しろ"
    assert "。" not in by_lemma


def test_proper_nouns_are_names_and_digits_are_dropped():
    analysis = analyse_text("リリアは３人の勇者と会った。")
    words = {w.lemma: w for w in analysis.counts}
    assert words["リリア"].pos == NAME_POS and words["リリア"].is_name
    assert "３" not in words and "3" not in words


def test_full_width_and_half_width_forms_are_normalised():
    assert "アイウ" in lemmas(analyse_text("ｱｲｳ"))


def test_measurements():
    text = "魔王は城を出た。「どこへ行くのですか」と勇者は尋ねた。\n\nおしまい。"
    analysis = analyse_text(text)
    assert analysis.sentences == 3
    assert analysis.dialogue_chars == len("どこへ行くのですか")
    squashed = "".join(text.split())
    assert analysis.chars == len(squashed)
    assert analysis.kanji_chars == sum("一" <= c <= "鿿" for c in squashed)


def test_dialogue_counts_nested_and_unbalanced_brackets():
    assert dialogue_chars("「あ『い』う」え") == 3  # あ, い and う; え is outside
    assert dialogue_chars("」「あ") == 1


def test_very_long_lines_are_split_for_the_tokenizer():
    line = "魔王は城を出た。" * 3000  # about 24,000 characters on one line
    assert lemmas(analyse_text(line))["魔王"] == 3000


def add_novel(conn, ncode: str) -> int:
    return upsert_novel(conn, NovelMeta(ncode=ncode, title=ncode, kind="serial"))


def test_samples_accumulate_and_chapters_are_remembered(conn):
    novel = add_novel(conn, "n0001aa")
    save_sample(conn, novel, 1, analyse_text("魔王は城を出た。"))
    save_sample(conn, novel, 2, analyse_text("魔王は村へ行った。"))
    assert set(sampled_chapters(conn, novel)) == {1, 2}
    row = conn.execute(
        "SELECT nl.count FROM novel_lemma nl JOIN lemma l ON l.id = nl.lemma_id"
        " WHERE nl.novel_id = ? AND l.lemma = '魔王'",
        (novel,),
    ).fetchone()
    assert row[0] == 2
    # Saving a chapter again replaces its sample row but is only called once per chapter.
    assert conn.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 2


def test_frequency_rank_ignores_names_and_balances_novels(conn):
    long_novel, short_novel = add_novel(conn, "n0001aa"), add_novel(conn, "n0002bb")
    save_sample(
        conn, long_novel, 1, analyse_text("魔王は城を出た。" * 50 + "リリアは笑った。" * 40)
    )
    save_sample(conn, short_novel, 1, analyse_text("勇者は村を出た。"))
    assert rebuild_frequency(conn) > 0
    rank = {
        r["lemma"]: r["corpus_rank"] for r in conn.execute("SELECT lemma, corpus_rank FROM lemma")
    }
    assert rank["リリア"] is None  # a name
    assert rank["魔王"] is not None and rank["勇者"] is not None
    # 城 appears only in the long novel, 村 only in the short one; averaged per novel the
    # short novel's word is at least as common as the long novel's.
    assert rank["村"] <= rank["城"]


def test_stats_add_up(conn):
    novel = add_novel(conn, "n0001aa")
    text = "魔王は城を出た。「どこへ行くのですか」と勇者は尋ねた。リリアは笑った。"
    analysis = analyse_text(text)
    save_sample(conn, novel, 1, analysis)
    assert rebuild_all(conn) == (
        conn.execute("SELECT COUNT(*) FROM lemma WHERE corpus_rank").fetchone()[0],
        1,
    )

    stats = conn.execute("SELECT * FROM novel_stats WHERE novel_id = ?", (novel,)).fetchone()
    names = sum(c for w, c in analysis.counts.items() if w.is_name)
    assert stats["tokens"] == sum(analysis.counts.values()) - names
    assert stats["sample_chars"] == analysis.chars
    assert stats["cover_10k"] == 1.0  # every non-name word is ranked in a one-novel catalog
    assert 0 < stats["cover_1k"] <= stats["cover_2k"] <= stats["cover_3k"] <= stats["cover_10k"]
    assert abs(stats["sentence_len"] - analysis.chars / analysis.sentences) < 1e-9
    assert abs(stats["dialogue_pct"] - 9 / analysis.chars) < 1e-9
    assert 0 < stats["kanji_pct"] < 1


def test_repeated_unknown_katakana_counts_as_a_name(conn):
    novel = add_novel(conn, "n0001aa")
    analysis = analyse_text("ゼルフィリアは笑った。" * 6)
    oov = [w for w in analysis.counts if w.oov and not w.is_name]
    assert oov, "the test word should be unknown to the dictionary"
    save_sample(conn, novel, 1, analysis)
    rebuild_all(conn)
    ranked = conn.execute("SELECT lemma FROM lemma WHERE corpus_rank IS NOT NULL").fetchall()
    assert oov[0].lemma not in {r[0] for r in ranked}


def test_stats_need_a_sample(conn):
    novel = add_novel(conn, "n0001aa")
    assert compute_stats(conn, novel) is False


def test_rare_words_skip_names_and_common_words(conn):
    novel = add_novel(conn, "n0001aa")
    save_sample(conn, novel, 1, analyse_text("魔王は城を出た。リリアは笑った。"))
    rebuild_all(conn)
    # In a one-novel catalog every ranked word is within the top 5,000, so none are rare.
    assert rare_words(conn, novel) == []
