"""Saving analysis results, and computing frequency ranks and per-novel statistics."""

from __future__ import annotations

import re
import sqlite3
import time
from collections import defaultdict

from .japanese import ANALYSER_VERSION, TextAnalysis

LANGUAGE = "ja"
COVER_STEPS = (1_000, 2_000, 3_000, 5_000, 10_000)
RARE_AFTER_RANK = 5_000
RARE_MIN_COUNT = 5
NAME_MIN_COUNT = 5  # an unknown katakana word seen this often in one novel is a name
_KATAKANA = re.compile(r"^[ァ-ヶー]+$")


def save_sample(
    conn: sqlite3.Connection,
    novel_id: int,
    chapter_no: int,
    analysis: TextAnalysis,
    now: float | None = None,
) -> None:
    """Add one analysed chapter: its lemma counts and measurements, in one transaction."""
    now = time.time() if now is None else now
    with conn:
        for word, count in analysis.counts.items():
            lemma_id = conn.execute(
                "INSERT INTO lemma (language, lemma, pos, reading, is_function, oov)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (language, lemma, pos) DO UPDATE SET"
                " reading = COALESCE(lemma.reading, excluded.reading)"
                " RETURNING id",
                (
                    LANGUAGE,
                    word.lemma,
                    word.pos,
                    word.reading,
                    int(word.is_function),
                    int(word.oov),
                ),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO novel_lemma (novel_id, lemma_id, count, is_name)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT (novel_id, lemma_id) DO UPDATE SET count = count + excluded.count",
                (novel_id, lemma_id, count, int(word.is_name)),
            )
        conn.execute(
            "INSERT OR REPLACE INTO sample (novel_id, chapter_no, chars, sentences, kanji_chars,"
            " dialogue_chars, fetched_at, analysed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                novel_id,
                chapter_no,
                analysis.chars,
                analysis.sentences,
                analysis.kanji_chars,
                analysis.dialogue_chars,
                now,
                now,
            ),
        )


def sampled_chapters(conn: sqlite3.Connection, novel_id: int) -> dict[int, int]:
    rows = conn.execute("SELECT chapter_no, chars FROM sample WHERE novel_id = ?", (novel_id,))
    return {r[0]: r[1] for r in rows}


def _novel_rows(conn: sqlite3.Connection, novel_id: int | None = None):
    query = (
        "SELECT nl.novel_id, nl.lemma_id, nl.count, nl.is_name, l.lemma, l.oov"
        " FROM novel_lemma nl JOIN lemma l ON l.id = nl.lemma_id"
    )
    args: tuple = ()
    if novel_id is not None:
        query += " WHERE nl.novel_id = ?"
        args = (novel_id,)
    return conn.execute(query, args)


def is_name(row) -> bool:
    """Proper nouns, plus unknown katakana words repeated often in one novel."""
    return bool(row["is_name"]) or (
        bool(row["oov"]) and row["count"] >= NAME_MIN_COUNT and bool(_KATAKANA.match(row["lemma"]))
    )


def rebuild_frequency(conn: sqlite3.Connection) -> int:
    """Recompute every lemma's corpus count and rank, and return how many were ranked.

    Rank follows the mean relative frequency across novels, so one long novel with a
    large cast of invented terms can't dominate the list. Names are left out.
    """
    totals: dict[int, int] = defaultdict(int)
    kept: list[tuple[int, int, int]] = []
    for row in _novel_rows(conn):
        if not is_name(row):
            totals[row["novel_id"]] += row["count"]
            kept.append((row["novel_id"], row["lemma_id"], row["count"]))
    novels = len(totals) or 1
    score: dict[int, float] = defaultdict(float)
    count: dict[int, int] = defaultdict(int)
    for novel_id, lemma_id, n in kept:
        score[lemma_id] += n / totals[novel_id] / novels
        count[lemma_id] += n
    ordered = sorted(score, key=lambda i: (-score[i], -count[i], i))
    with conn:
        conn.execute("UPDATE lemma SET corpus_count = 0, corpus_rank = NULL")
        conn.executemany(
            "UPDATE lemma SET corpus_count = ?, corpus_rank = ? WHERE id = ?",
            [(count[i], rank, i) for rank, i in enumerate(ordered, start=1)],
        )
    return len(ordered)


def compute_stats(conn: sqlite3.Connection, novel_id: int, now: float | None = None) -> bool:
    """Recompute one novel's statistics from its samples and lemma counts."""
    sample = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(chars), 0) AS chars, COALESCE(SUM(sentences), 0) AS s,"
        " COALESCE(SUM(kanji_chars), 0) AS kanji, COALESCE(SUM(dialogue_chars), 0) AS talk"
        " FROM sample WHERE novel_id = ?",
        (novel_id,),
    ).fetchone()
    if not sample["n"] or not sample["chars"]:
        return False
    ranks = {
        r[0]: r[1] for r in conn.execute("SELECT id, corpus_rank FROM lemma WHERE corpus_rank > 0")
    }
    flags = {r[0]: r[1] for r in conn.execute("SELECT id, is_function FROM lemma")}
    tokens = 0
    covered = dict.fromkeys(COVER_STEPS, 0)
    unique = rare = 0
    for row in _novel_rows(conn, novel_id):
        if is_name(row):
            continue
        n, rank = row["count"], ranks.get(row["lemma_id"])
        tokens += n
        unique += 1
        for step in COVER_STEPS:
            if rank is not None and rank <= step:
                covered[step] += n
        if (
            n >= RARE_MIN_COUNT
            and not flags[row["lemma_id"]]
            and (rank is None or rank > RARE_AFTER_RANK)
        ):
            rare += 1
    if not tokens:
        return False
    cover = {step: covered[step] / tokens for step in COVER_STEPS}
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO novel_stats (novel_id, sample_chars, tokens, unique_lemmas,"
            " cover_1k, cover_2k, cover_3k, cover_5k, cover_10k, sentence_len, kanji_pct,"
            " dialogue_pct, rare_load, analyser_version, analysed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                novel_id,
                sample["chars"],
                tokens,
                unique,
                *(cover[step] for step in COVER_STEPS),
                sample["chars"] / sample["s"] if sample["s"] else None,
                sample["kanji"] / sample["chars"],
                sample["talk"] / sample["chars"],
                rare,
                ANALYSER_VERSION,
                time.time() if now is None else now,
            ),
        )
    return True


def rebuild_all(conn: sqlite3.Connection) -> tuple[int, int]:
    """Recompute frequency ranks, then statistics for every sampled novel."""
    ranked = rebuild_frequency(conn)
    ids = [r[0] for r in conn.execute("SELECT DISTINCT novel_id FROM sample")]
    done = sum(compute_stats(conn, i) for i in ids)
    return ranked, done


def rare_words(conn: sqlite3.Connection, novel_id: int, limit: int = 30) -> list[dict]:
    """The most frequent words in a novel that sit outside the common 5,000."""
    rows = []
    for row in conn.execute(
        "SELECT nl.count, nl.is_name, l.lemma, l.oov, l.reading, l.pos, l.corpus_rank,"
        " l.is_function"
        " FROM novel_lemma nl JOIN lemma l ON l.id = nl.lemma_id WHERE nl.novel_id = ?"
        " ORDER BY nl.count DESC",
        (novel_id,),
    ):
        if is_name(row) or row["is_function"]:
            continue
        if row["corpus_rank"] is None or row["corpus_rank"] > RARE_AFTER_RANK:
            rows.append(
                {
                    "lemma": row["lemma"],
                    "reading": row["reading"],
                    "pos": row["pos"],
                    "count": row["count"],
                    "rank": row["corpus_rank"],
                }
            )
            if len(rows) == limit:
                break
    return rows
