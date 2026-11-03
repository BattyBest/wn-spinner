"""Short passages for the placement test, kept in the local catalog only.

An excerpt is one to three whole sentences, 80 to 300 characters, taken from a chapter body
that is being analysed anyway. It is stored with its tokens so the test can show it with
tappable words. Excerpts never leave catalog.db, which is gitignored, and are meant for the
reader's own use as a test item, like a quoted line in a review.
"""

from __future__ import annotations

import json
import re
import sqlite3

from ..analysis.japanese import NAME_POS, iter_tokens, normalise
from . import LANGUAGE

MIN_CHARS = 80
MAX_CHARS = 300
PER_NOVEL = 3

_SENTENCES = re.compile(r"[^。！？!?\n]*[。！？!?]+[」』）)]*|[^。！？!?\n]+")
_KANJI = re.compile(r"[㐀-䶿一-鿿々〆]")


def candidates(text: str) -> list[str]:
    """Every window of one to three sentences that fits the length limits, in text order."""
    sentences = [s.strip() for s in _SENTENCES.findall(normalise(text)) if s.strip()]
    found = []
    for start in range(len(sentences)):
        joined = ""
        for end in range(start, min(start + 3, len(sentences))):
            joined += sentences[end]
            if len(joined) > MAX_CHARS:
                break
            if len(joined) >= MIN_CHARS and _KANJI.search(joined):
                found.append(joined)
                break
    return found


def pick(text: str, count: int) -> list[str]:
    """Up to ``count`` windows spread evenly through the text."""
    windows = candidates(text)
    if count <= 0 or not windows:
        return []
    chosen: list[str] = []
    for k in range(count):
        window = windows[min(int((k + 0.5) / count * len(windows)), len(windows) - 1)]
        if window not in chosen:
            chosen.append(window)
    return chosen


def tokenise(conn: sqlite3.Connection, text: str) -> list[list]:
    """``[surface, lemma_id or None, pos or None]`` for each token of the text."""
    out: list[list] = []
    for surface, word in iter_tokens(text):
        if surface == "\n":
            continue
        if word is None or word.pos == NAME_POS:
            out.append([surface, None, word.pos if word else None])
            continue
        row = conn.execute(
            "SELECT id FROM lemma WHERE language = ? AND lemma = ? AND pos = ?",
            (LANGUAGE, word.lemma, word.pos),
        ).fetchone()
        out.append([surface, row[0] if row else None, word.pos])
    return out


def have(conn: sqlite3.Connection, novel_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM excerpt WHERE novel_id = ?", (novel_id,)).fetchone()[
        0
    ]


def save_excerpts(
    conn: sqlite3.Connection, novel_id: int, chapter_no: int, text: str, want: int = 1
) -> int:
    """Store up to ``want`` new excerpts from a chapter, never more than PER_NOVEL in all."""
    room = PER_NOVEL - have(conn, novel_id)
    saved = 0
    for window in pick(text, min(want, room)):
        tokens = tokenise(conn, window)
        cursor = conn.execute(
            "INSERT OR IGNORE INTO excerpt (novel_id, chapter_no, text, chars, tokens)"
            " VALUES (?, ?, ?, ?, ?)",
            (novel_id, chapter_no, window, len(window), json.dumps(tokens, ensure_ascii=False)),
        )
        saved += cursor.rowcount
    conn.commit()
    return saved
