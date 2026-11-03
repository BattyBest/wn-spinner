"""Short passages for the placement test, kept in the local catalog only.

An excerpt is one to three whole sentences, 80 to 300 characters, taken from a chapter body
that is being analysed anyway. It is stored with its tokens so the test can show it with
tappable words. Excerpts never leave catalog.db, which is gitignored, and are meant for the
reader's own use as a test item, like a quoted line in a review.
"""

from __future__ import annotations

import json
import sqlite3

from .. import lang as languages
from ..analysis.store import novel_language

# Characters per excerpt. Chinese packs more into a character, so its windows are shorter.
LIMITS = {"ja": (80, 300), "zh": (60, 200)}
MIN_CHARS, MAX_CHARS = LIMITS["ja"]
PER_NOVEL = 3


def candidates(text: str, lang: str = "ja") -> list[str]:
    """Every window of one to three sentences that fits the length limits, in text order."""
    low, high = LIMITS[lang]
    pattern = languages.sentence_pattern(lang)
    sentences = [s.strip() for s in pattern.findall(languages.normalise(lang, text)) if s.strip()]
    found = []
    for start in range(len(sentences)):
        joined = ""
        for end in range(start, min(start + 3, len(sentences))):
            joined += sentences[end]
            if len(joined) > high:
                break
            if len(joined) >= low and languages.has_script(lang, joined):
                found.append(joined)
                break
    return found


def pick(text: str, count: int, lang: str = "ja") -> list[str]:
    """Up to ``count`` windows spread evenly through the text."""
    windows = candidates(text, lang)
    if count <= 0 or not windows:
        return []
    chosen: list[str] = []
    for k in range(count):
        window = windows[min(int((k + 0.5) / count * len(windows)), len(windows) - 1)]
        if window not in chosen:
            chosen.append(window)
    return chosen


def tokenise(conn: sqlite3.Connection, text: str, lang: str = "ja") -> list[list]:
    """``[surface, lemma_id or None, pos or None]`` for each token of the text."""
    out: list[list] = []
    name_pos = languages.get(lang).name_pos
    for surface, word in languages.iter_tokens(lang, text):
        if surface == "\n":
            continue
        if word is None or word.pos == name_pos:
            out.append([surface, None, word.pos if word else None])
            continue
        row = conn.execute(
            "SELECT id FROM lemma WHERE language = ? AND lemma = ? AND pos = ?",
            (lang, word.lemma, word.pos),
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
    lang = novel_language(conn, novel_id)
    saved = 0
    for window in pick(text, min(want, room), lang):
        tokens = tokenise(conn, window, lang)
        cursor = conn.execute(
            "INSERT OR IGNORE INTO excerpt (novel_id, chapter_no, text, chars, tokens)"
            " VALUES (?, ?, ?, ?, ?)",
            (novel_id, chapter_no, window, len(window), json.dumps(tokens, ensure_ascii=False)),
        )
        saved += cursor.rowcount
    conn.commit()
    return saved
