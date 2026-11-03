import json
import zipfile

import pytest

from wn.learner import dictionary as d

# A tiny document shaped like jmdict-simplified output, written for these tests.
ENTRIES = [
    {
        "id": "1001",
        "kanji": [{"common": True, "text": "反応", "tags": []}],
        "kana": [{"common": True, "text": "はんのう", "tags": [], "appliesToKanji": ["*"]}],
        "sense": [
            {
                "partOfSpeech": ["n", "vs"],
                "field": ["chem"],
                "misc": [],
                "gloss": [
                    {"lang": "eng", "text": "reaction"},
                    {"lang": "eng", "text": "response"},
                ],
            }
        ],
    },
    {
        "id": "1002",
        "kanji": [{"common": False, "text": "魔法", "tags": []}],
        "kana": [{"common": False, "text": "まほう", "tags": [], "appliesToKanji": ["*"]}],
        "sense": [
            {
                "partOfSpeech": ["n"],
                "field": ["myth"],
                "misc": ["uk", "xx"],
                "gloss": [{"lang": "eng", "text": "magic"}],
            }
        ],
    },
    {
        "id": 1003,  # older builds use numbers
        "kanji": [],
        "kana": [{"common": True, "text": "やばい", "tags": [], "appliesToKanji": []}],
        "sense": [
            {
                "partOfSpeech": ["adj-i"],
                "field": [],
                "misc": ["sl", "col"],
                "gloss": [{"lang": "eng", "text": "dangerous; awesome"}],
            }
        ],
    },
    {
        "id": "1004",  # a kana homophone of 魔法 that is not common
        "kanji": [],
        "kana": [{"common": False, "text": "まほう", "tags": [], "appliesToKanji": []}],
        "sense": [
            {
                "partOfSpeech": ["n"],
                "field": [],
                "misc": [],
                "gloss": [{"lang": "eng", "text": "wrong match"}],
            }
        ],
    },
]


def document(entries=ENTRIES) -> str:
    head = {"version": "3.6.1", "dictDate": "2026-10-26", "tags": {}}
    return json.dumps({**head, "words": entries}, ensure_ascii=False)


def add_lemma(conn, lemma, pos="名詞", rank=10):
    return conn.execute(
        "INSERT INTO lemma (language, lemma, pos, corpus_rank) VALUES ('ja', ?, ?, ?)",
        (lemma, pos, rank),
    ).lastrowid


def test_entries_stream_one_at_a_time():
    found = list(d.iter_jmdict(document()))
    assert [str(e["id"]) for e in found] == ["1001", "1002", "1003", "1004"]


def test_a_file_that_is_not_jmdict_is_refused():
    with pytest.raises(d.DictError):
        list(d.iter_jmdict('{"hello": 1}'))


def test_gloss_tags_and_usage_tags():
    entry = ENTRIES[0]
    assert d.entry_gloss(entry) == "reaction, response"
    assert d.entry_tags(entry) == "chem"
    assert d.entry_tags(ENTRIES[1]) == "myth uk"  # xx is not a kept usage tag
    assert d.entry_tags(ENTRIES[2]) == "sl col"


def test_load_matches_lemmas_and_prefers_the_kanji_entry(conn, tmp_path):
    react = add_lemma(conn, "反応")
    magic = add_lemma(conn, "魔法")
    slang = add_lemma(conn, "やばい", "形容詞")
    unknown = add_lemma(conn, "謎語")
    name = add_lemma(conn, "反応", "固有名詞")
    path = tmp_path / "jmdict.json"
    path.write_text(document(), encoding="utf-8")

    result = d.load_jmdict(conn, path)

    assert result["entries"] == 4
    row = lambda i: conn.execute("SELECT * FROM lemma WHERE id = ?", (i,)).fetchone()  # noqa: E731
    assert (row(react)["gloss"], row(react)["tags"]) == ("reaction, response", "chem")
    assert row(magic)["gloss"] == "magic" and row(magic)["jmdict_id"] == 1002
    assert row(slang)["tags"] == "sl col"
    assert row(unknown)["gloss"] is None
    assert row(name)["gloss"] is None  # proper nouns are never glossed
    forms = {r[0] for r in conn.execute("SELECT form FROM dict_form")}
    assert {"反応", "はんのう", "まほう", "やばい"} <= forms
    meta = conn.execute("SELECT * FROM dict_meta WHERE name = 'jmdict'").fetchone()
    assert meta["entries"] == 4 and meta["version"] == "3.6.1 2026-10-26"


def test_zip_files_load_and_reloading_replaces(conn, tmp_path):
    add_lemma(conn, "魔法")
    archive = tmp_path / "jmdict-eng-3.6.1.json.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("jmdict-eng-3.6.1.json", document())
    d.load_jmdict(conn, archive)
    d.load_jmdict(conn, archive)
    assert conn.execute("SELECT COUNT(*) FROM dict_form WHERE form = '魔法'").fetchone()[0] == 1
    assert conn.execute("SELECT gloss FROM lemma").fetchone()[0] == "magic"


def test_jlpt_csv_with_header_and_level_column():
    text = (
        "expression,reading,meaning,tags\n"
        "反応,はんのう,reaction,JLPT_N2\n"
        "魔法,まほう,magic,JLPT_N3\n"
    )
    assert d.parse_jlpt(text) == [("反応", "はんのう", 2), ("魔法", "まほう", 3)]


def test_jlpt_file_without_header_takes_level_from_the_name(conn, tmp_path):
    (tmp_path / "jlpt-n4.csv").write_text("反応\tはんのう\tx\n魔法\tまほう\tx\n", encoding="utf-8")
    (tmp_path / "n5.csv").write_text("魔法,まほう\n", encoding="utf-8")
    count = d.load_jlpt(conn, [(tmp_path / "jlpt-n4.csv", None), (tmp_path / "n5.csv", None)])
    assert count == 2
    levels = dict(conn.execute("SELECT lemma, level FROM jlpt_word").fetchall())
    assert levels == {"反応": 4, "魔法": 5}  # a word in two lists keeps the easier level


def test_jlpt_rows_without_any_level_are_an_error(conn, tmp_path):
    (tmp_path / "words.csv").write_text("反応,はんのう\n", encoding="utf-8")
    with pytest.raises(d.DictError):
        d.load_jlpt(conn, [(tmp_path / "words.csv", None)])
