"""A synthetic catalog for learner tests: invented words, no real novel text."""

from __future__ import annotations

import json
import random

KANJI = [chr(0x4E00 + i * 7) for i in range(60)]
KATA = "アイウエオカキクケコサシスセソタチツテトナニヌネノ"
NOVELS = 12


def word_for(i: int) -> str:
    if i % 6 == 5:  # a katakana word
        a, b, c, d = (KATA[(i * k + k) % len(KATA)] for k in (1, 2, 3, 5))
        return a + b + c + d + "ー"
    return KANJI[i % 60] + KANJI[(i * 7 + 3) % 60]


def build(conn, words: int = 360, rng_seed: int = 3) -> dict:
    """Fill a catalog: ``words`` lemmas ranked 1..N, 12 novels, domains, excerpts."""
    rng = random.Random(rng_seed)
    source = conn.execute("SELECT id FROM source WHERE name = 'syosetu'").fetchone()[0]
    ids: list[int] = []
    names: list[str] = []
    seen: set[str] = set()
    for i in range(words):
        lemma = word_for(i)
        if lemma in seen:
            lemma += KANJI[(i // 60) % 60]
        seen.add(lemma)
        names.append(lemma)
        pos = "名詞"
        cursor = conn.execute(
            "INSERT INTO lemma (language, lemma, pos, reading, corpus_count, corpus_rank, gloss)"
            " VALUES ('ja', ?, ?, 'よみ', ?, ?, ?)",
            (lemma, pos, 1000 // (i + 1) + 5, i + 1, f"meaning number {i}"),
        )
        ids.append(cursor.lastrowid)
    particle = conn.execute(
        "INSERT INTO lemma (language, lemma, pos, reading, is_function, corpus_rank)"
        " VALUES ('ja', 'の', '助詞', 'の', 1, 1000)"
    ).lastrowid
    for i in range(20, 60):
        conn.execute(
            "INSERT INTO lemma_domain (lemma_id, domain, weight, source)"
            " VALUES (?, 'fantasy', 1, 'dictionary')",
            (ids[i],),
        )
    for i in range(60, 100):
        conn.execute(
            "INSERT INTO lemma_domain (lemma_id, domain, weight, source)"
            " VALUES (?, 'money', 1, 'dictionary')",
            (ids[i],),
        )
    novels = []
    for n in range(NOVELS):
        nid = conn.execute(
            "INSERT INTO novel"
            " (source_id, external_id, title, url, genre, keywords, points, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source,
                f"n{n:04d}x",
                f"Novel {n}",
                f"https://example.invalid/{n}",
                "ハイファンタジー〔ファンタジー〕" if n < 4 else "ヒューマンドラマ〔文芸〕",
                "魔法 異世界" if n < 4 else "日常",
                100 * (n + 1),
                "completed" if n % 2 else "ongoing",
            ),
        ).lastrowid
        novels.append(nid)
        total = 0
        for i, lid in enumerate(ids):
            count = max(1, 400 // (i + 1)) + (3 if n < 4 and 20 <= i < 60 else 0)
            conn.execute(
                "INSERT INTO novel_lemma (novel_id, lemma_id, count) VALUES (?, ?, ?)",
                (nid, lid, count),
            )
            total += count
        conn.execute(
            "INSERT INTO novel_stats (novel_id, sample_chars, tokens, unique_lemmas,"
            " cover_1k, cover_2k, cover_3k, cover_5k, cover_10k, analyser_version, analysed_at)"
            " VALUES (?, 10000, ?, ?, 0.8, 0.85, 0.9, 0.95, 0.99, 1, 1000.0)",
            (nid, total, len(ids)),
        )
    excerpt_ids = []
    for n in range(NOVELS):
        pool = rng.sample(range(0, 140), 12)
        tokens = []
        for i in pool:
            tokens.append([names[i], ids[i], "名詞"])
            tokens.append(["の", particle, "助詞"])
        tokens.append(["。", None, None])
        text = "".join(t[0] for t in tokens)
        excerpt_ids.append(
            conn.execute(
                "INSERT INTO excerpt (novel_id, chapter_no, text, chars, tokens)"
                " VALUES (?, 1, ?, ?, ?)",
                (novels[n], text + str(n), len(text), json.dumps(tokens, ensure_ascii=False)),
            ).lastrowid
        )
    conn.commit()
    return {"lemmas": ids, "novels": novels, "excerpts": excerpt_ids, "particle": particle}


def add_easy_novels(conn, ids: dict, heavy=(600, 250, 100)) -> list[int]:
    """Novels made almost entirely of the commonest 40 words, so coverage is high."""
    source = conn.execute("SELECT id FROM source WHERE name = 'syosetu'").fetchone()[0]
    out = []
    for k, weight in enumerate(heavy):
        nid = conn.execute(
            "INSERT INTO novel (source_id, external_id, title, url, genre, points, status)"
            " VALUES (?, ?, ?, ?, 'ヒューマンドラマ〔文芸〕', ?, 'completed')",
            (source, f"e{k:04d}x", f"Easy {k}", f"https://example.invalid/e{k}", 50 * (k + 1)),
        ).lastrowid
        total = 0
        for i, lid in enumerate(ids["lemmas"]):
            count = weight if i < 40 else 1
            conn.execute(
                "INSERT INTO novel_lemma (novel_id, lemma_id, count) VALUES (?, ?, ?)",
                (nid, lid, count),
            )
            total += count
        conn.execute(
            "INSERT INTO novel_stats (novel_id, sample_chars, tokens, unique_lemmas,"
            " cover_1k, cover_2k, cover_3k, cover_5k, cover_10k, analyser_version, analysed_at)"
            " VALUES (?, 10000, ?, ?, 0.8, 0.85, 0.9, 0.95, 0.99, 1, 2000.0)",
            (nid, total, len(ids["lemmas"])),
        )
        out.append(nid)
    conn.commit()
    return out
