import gzip
import json
import zipfile

import pytest

from wn.analysis.chinese import analyse_text, dialogue_chars, iter_tokens
from wn.learner import dictionary as d
from wn.learner.coverage import level_estimate
from wn.learner.model import load_learner

from .synthetic import build

# --- analysis ---------------------------------------------------------------------------


def lemmas(analysis) -> dict[str, int]:
    out: dict[str, int] = {}
    for word, count in analysis.counts.items():
        out[word.lemma] = out.get(word.lemma, 0) + count
    return out


def test_words_are_segmented_and_punctuation_and_numbers_dropped():
    counts = lemmas(analyse_text("她走进房间，看见３个人。"))
    assert "房间" in counts and "看见" in counts
    assert "，" not in counts and "。" not in counts and "３" not in counts and "3" not in counts


def test_particles_are_function_words():
    words = {w.lemma: w for w in analyse_text("他的书很好。").counts}
    assert words["的"].is_function and not words["书"].is_function


def test_people_and_places_become_names():
    analysis = analyse_text("张伟去了北京。张伟很高兴。")
    words = {w.lemma: w for w in analysis.counts}
    assert words["张伟"].is_name or words["北京"].is_name


def test_dialogue_chars_count_quoted_text_only():
    assert dialogue_chars("他说：“你好吗？”然后走了。") == 4
    assert dialogue_chars("「你好」") == 2


def test_sentences_and_chars():
    analysis = analyse_text("他来了。她走了！你呢？")
    assert analysis.sentences == 3 and analysis.chars == 11


def test_tokens_keep_every_surface_in_order():
    surfaces = "".join(s for s, _w in iter_tokens("她走进房间。\n他笑了。"))
    assert surfaces.replace("\n", "") == "她走进房间。他笑了。"


# --- pinyin and CC-CEDICT ------------------------------------------------------------------


def test_pinyin_tone_marks():
    assert d.pinyin_marks("ni3 hao3") == "nǐ hǎo"
    assert d.pinyin_marks("lu:e4") == "lüè"
    assert d.pinyin_marks("ma5") == "ma"
    assert d.pinyin_marks("zhong1 guo2") == "zhōng guó"


def test_parse_cedict_line():
    entry = d.parse_cedict_line("你好 你好 [ni3 hao3] /hello/hi/")
    assert entry["simplified"] == "你好" and entry["pinyin"] == "nǐ hǎo"
    assert entry["meanings"] == ["hello", "hi"]
    assert d.parse_cedict_line("# a comment") is None
    assert d.parse_cedict_line("not an entry") is None


def test_cedict_gloss_skips_classifiers_and_shortens():
    assert d.cedict_gloss(["CL:個|个[ge4]", "a", "b", "c", "d"]) == "a; b; c"


CEDICT = """#! version=1
#! date=2026-10-01
魔法 魔法 [mo2 fa3] /magic/
書 书 [shu1] /book/CL:本[ben3]/
書 书 [shu1] /variant of something/
成語 成语 [cheng2 yu3] /idiom/(idiom) set phrase/
"""


@pytest.fixture
def zh_world(tmp_path):
    from wn.db import open_catalog

    catalog = open_catalog(tmp_path)
    build(catalog, lang="zh")
    yield catalog
    catalog.close()


def test_load_cedict_from_text_gz_and_zip(zh_world, tmp_path):
    conn = zh_world
    conn.execute("INSERT INTO lemma (language, lemma, pos) VALUES ('zh', '书', 'n')")
    ja_before = conn.execute(
        "SELECT COUNT(*) FROM lemma WHERE language = 'ja' AND gloss IS NOT NULL"
    ).fetchone()[0]
    plain = tmp_path / "cedict.u8"
    plain.write_text(CEDICT, encoding="utf-8")
    gz = tmp_path / "cedict.txt.gz"
    gz.write_bytes(gzip.compress(CEDICT.encode()))
    zipped = tmp_path / "cedict.zip"
    with zipfile.ZipFile(zipped, "w") as z:
        z.writestr("cedict_ts.u8", CEDICT)
    for path in (plain, gz, zipped):
        result = d.load_cedict(conn, path)
        assert result["entries"] == 4
        row = conn.execute("SELECT gloss, reading FROM lemma WHERE lemma = '书'").fetchone()
        assert row["gloss"] == "book" and row["reading"] == "shū"
    forms = conn.execute("SELECT form FROM dict_form WHERE language = 'zh'").fetchall()
    assert {"書", "书", "魔法"} <= {f[0] for f in forms}
    assert conn.execute("SELECT COUNT(*) FROM dict_form WHERE language = 'ja'").fetchone()[0] == 0
    ja_after = conn.execute(
        "SELECT COUNT(*) FROM lemma WHERE language = 'ja' AND gloss IS NOT NULL"
    ).fetchone()[0]
    assert ja_before == ja_after
    assert d.status(conn, "zh")["meta"]["cedict"]["entries"] == 4


def test_load_cedict_prefers_a_real_sense_over_pointers_and_marked_senses(zh_world, tmp_path):
    conn = zh_world
    for word in ("绿", "行"):
        conn.execute("INSERT INTO lemma (language, lemma, pos) VALUES ('zh', ?, 'n')", (word,))
    path = tmp_path / "cedict.u8"
    path.write_text(
        "綠 绿 [Lu:4] /surname Lü/\n"
        "綠 绿 [lu4] /used in names/\n"
        "綠 绿 [lu:4] /green/\n"
        "行 行 [hang2] /(bound form) row; line/\n"
        "行 行 [heng2] /used in 道行[dao4 heng2]/\n"
        "行 行 [xing2] /to walk; to go/capable/\n",
        encoding="utf-8",
    )
    d.load_cedict(conn, path)
    rows = {r["lemma"]: r for r in conn.execute("SELECT lemma, gloss, reading FROM lemma")}
    assert (rows["绿"]["gloss"], rows["绿"]["reading"]) == ("green", "lǜ")
    assert (rows["行"]["gloss"], rows["行"]["reading"]) == ("to walk; to go; capable", "xíng")


def test_parse_hsk_keeps_the_easiest_level_and_ignores_old_lists():
    text = json.dumps(
        [
            {
                "simplified": "爱",
                "level": ["new-1", "old-3"],
                "forms": [{"transcriptions": {"pinyin": "ài"}}],
            },
            {"simplified": "爱", "level": ["new-3"], "forms": []},
            {"simplified": "旧", "level": ["old-2"], "forms": []},
            {"simplified": "难", "level": ["new-7"], "forms": []},
        ]
    )
    rows = {w: (p, level) for w, p, level in d.parse_hsk(text)}
    assert rows == {"爱": ("ài", 1), "难": ("", 7)}
    with pytest.raises(d.DictError):
        d.parse_hsk("not json")


def test_hsk_levels_feed_the_level_estimate(zh_world, tmp_path):
    conn = zh_world
    words = [r["lemma"] for r in conn.execute("SELECT lemma FROM lemma WHERE language = 'zh'")]
    easy, hard = words[:40], words[-40:]
    path = tmp_path / "complete.json"
    path.write_text(
        json.dumps(
            [{"simplified": w, "level": ["new-1"], "forms": []} for w in easy]
            + [{"simplified": w, "level": ["new-6"], "forms": []} for w in hard]
        ),
        encoding="utf-8",
    )
    assert d.load_hsk(conn, path) == 80
    from wn.db import open_profile

    profile = open_profile(tmp_path)
    result = level_estimate(conn, load_learner(profile, conn, "zh"))
    assert result["name"] == "HSK" and result["loaded"]
    assert [lv["level"] for lv in result["levels"]] == [1, 2, 3, 4, 5, 6, 7]
    assert result["levels"][0]["total"] == 40
