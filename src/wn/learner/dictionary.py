"""Reference dictionaries: JMdict and CC-CEDICT glosses, and the JLPT and HSK word lists.

All are downloaded once into ``data/dicts/`` and are never committed (JMdict is CC BY-SA
from the EDRDG; the JLPT lists are community lists, CC BY; CC-CEDICT is CC BY-SA from MDBG;
the HSK lists come from the MIT-licensed complete-hsk-vocabulary project). Loading adds
glosses (and, for Chinese, pinyin) to catalog lemmas, records every written form the
dictionary knows (to check made-up test words) and stores the level lists.

The JMdict file is the JSON build from the jmdict-simplified project, as a ``.json``,
``.json.zip`` or ``.json.tgz``. It is read as a stream, one entry at a time, so a load
needs memory for the file's text, not for a parsed copy of it.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import sqlite3
import tarfile
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

import httpx

from .. import lang as languages
from ..analysis.japanese import NAME_POS, normalise
from ..config import USER_AGENT

JMDICT_RELEASES = "https://api.github.com/repos/scriptin/jmdict-simplified/releases/latest"
# Release assets are named like jmdict-eng-3.6.2+20261102210542.json.zip (version, then
# the build timestamp); the -common build and other languages are skipped.
JMDICT_ASSET = re.compile(r"jmdict-eng-\d+(?:\.\d+)*(?:\+\d+)?\.json\.zip")
JLPT_URLS = {
    level: f"https://raw.githubusercontent.com/jamsinclair/open-anki-jlpt-decks/main/src/n{level}.csv"
    for level in (5, 4, 3, 2, 1)
}
CEDICT_URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip"
HSK_URL = "https://raw.githubusercontent.com/drkameleon/complete-hsk-vocabulary/main/complete.json"
GLOSS_MAX = 80
# JMdict "misc" tags worth keeping beside the field tags: register and usage.
USAGE_TAGS = {"col", "sl", "fam", "vulg", "hon", "hum", "pol", "arch", "form", "uk", "derog"}


class DictError(Exception):
    pass


# --- reading files ---------------------------------------------------------------------


def _read_json_text(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.namelist() if m.lower().endswith(".json")]
            if not members:
                raise DictError(f"{path.name} contains no .json file")
            return archive.read(members[0]).decode("utf-8")
    if name.endswith((".tgz", ".tar.gz")):
        with tarfile.open(path) as archive:
            for member in archive:
                if member.isfile() and member.name.lower().endswith(".json"):
                    handle = archive.extractfile(member)
                    if handle:
                        return handle.read().decode("utf-8")
        raise DictError(f"{path.name} contains no .json file")
    return path.read_text(encoding="utf-8")


def iter_jmdict(text: str) -> Iterator[dict]:
    """Yield the entries of a jmdict-simplified JSON document one at a time."""
    marker = re.search(r'"words"\s*:\s*\[', text)
    if marker is None:
        raise DictError('no "words" list found; is this a jmdict-simplified JSON file?')
    decoder = json.JSONDecoder()
    position = marker.end()
    length = len(text)
    while position < length:
        while position < length and text[position] in " \t\r\n,":
            position += 1
        if position >= length or text[position] == "]":
            return
        entry, position = decoder.raw_decode(text, position)
        yield entry


def jmdict_version(text: str) -> str:
    match = re.search(r'"version"\s*:\s*"([^"]+)"', text[:2000])
    date = re.search(r'"dictDate"\s*:\s*"([^"]+)"', text[:2000])
    return " ".join(part.group(1) for part in (match, date) if part) or "unknown"


# --- JMdict ------------------------------------------------------------------------------


def entry_forms(entry: dict) -> tuple[list[str], list[str]]:
    kanji = [normalise(k["text"]) for k in entry.get("kanji", [])]
    kana = [normalise(k["text"]) for k in entry.get("kana", [])]
    return kanji, kana


def entry_common(entry: dict) -> bool:
    return any(k.get("common") for k in entry.get("kanji", []) + entry.get("kana", []))


def entry_gloss(entry: dict) -> str:
    """A short English gloss from the entry's first sense, or its first two senses."""
    parts: list[str] = []
    for sense in entry.get("sense", [])[:2]:
        glosses = [g["text"] for g in sense.get("gloss", []) if g.get("lang", "eng") == "eng"]
        if glosses:
            parts.append(", ".join(glosses[:3]))
    text = "; ".join(parts)
    return text if len(text) <= GLOSS_MAX else text[: GLOSS_MAX - 1].rstrip(", ;") + "…"


def entry_tags(entry: dict) -> str:
    """Field tags (chem, med, ...) and usage tags (col, hon, ...) over all senses."""
    tags: dict[str, None] = {}
    for sense in entry.get("sense", []):
        for tag in sense.get("field", []):
            tags[tag] = None
        for tag in sense.get("misc", []):
            if tag in USAGE_TAGS:
                tags[tag] = None
    return " ".join(tags)


def entry_pos(entry: dict) -> set[str]:
    out: set[str] = set()
    for sense in entry.get("sense", []):
        out.update(sense.get("partOfSpeech", []))
    return out


def load_jmdict(conn: sqlite3.Connection, path: Path, now: float | None = None) -> dict:
    """Load a JMdict file: forms, then glosses and tags onto matching lemmas."""
    text = _read_json_text(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    wanted: dict[str, list[int]] = {}
    for row in conn.execute(
        "SELECT id, lemma FROM lemma WHERE language = 'ja' AND pos != ?", (NAME_POS,)
    ):
        wanted.setdefault(row["lemma"], []).append(row["id"])

    best: dict[str, tuple[tuple, dict]] = {}
    forms: list[tuple[str, int]] = []
    entries = 0
    for entry in iter_jmdict(text):
        entries += 1
        entry_id = int(entry["id"])
        kanji, kana = entry_forms(entry)
        forms.extend((form, entry_id) for form in dict.fromkeys(kanji + kana))
        common = entry_common(entry)
        for index, form in enumerate(kanji + kana):
            if form in wanted:
                is_kanji = index < len(kanji)
                # Prefer a kanji match, then a common entry, then the older (lower) id.
                key = (0 if is_kanji else 1, 0 if common else 1, entry_id)
                if form not in best or key < best[form][0]:
                    best[form] = (key, entry)
    with conn:
        conn.execute("DELETE FROM dict_form WHERE language = 'ja'")
        conn.executemany(
            "INSERT OR IGNORE INTO dict_form (language, form, entry_id) VALUES ('ja', ?, ?)", forms
        )
        conn.execute(
            "UPDATE lemma SET gloss = NULL, dict_id = NULL, tags = NULL, is_common = NULL"
            " WHERE language = 'ja'"
        )
        matched = 0
        for form, (_key, entry) in best.items():
            for lemma_id in wanted[form]:
                conn.execute(
                    "UPDATE lemma SET gloss = ?, dict_id = ?, tags = ?, is_common = ? WHERE id = ?",
                    (
                        entry_gloss(entry) or None,
                        int(entry["id"]),
                        entry_tags(entry),
                        int(entry_common(entry)),
                        lemma_id,
                    ),
                )
                matched += 1
        conn.execute(
            "INSERT OR REPLACE INTO dict_meta (name, version, source, sha256, entries, loaded_at)"
            " VALUES ('jmdict', ?, ?, ?, ?, ?)",
            (jmdict_version(text), path.name, sha, entries, time.time() if now is None else now),
        )
    return {"entries": entries, "forms": len(forms), "lemmas_matched": matched}


# --- JLPT lists --------------------------------------------------------------------------

_LEVEL = re.compile(r"[Nn]?([1-5])")
_EXPRESSION = ("expression", "kanji", "word", "lemma", "vocab", "japanese")
_READING = ("reading", "kana", "hiragana", "furigana")
_LEVEL_COLUMNS = ("level", "jlpt", "tags", "tag")


def _level_of(text: str) -> int | None:
    match = re.search(r"[Nn]([1-5])", text) or re.fullmatch(r"\s*([1-5])\s*", text)
    return int(match.group(1)) if match else None


def parse_jlpt(text: str, default_level: int | None = None) -> list[tuple[str, str, int]]:
    """Rows of ``(word, reading, level)`` from a CSV or TSV list, with or without a header.

    The word column is the first one named like expression, kanji or word, otherwise the
    first column; the level comes from a level or tags column, or ``default_level``.
    """
    sample = text[:2000]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    rows = [
        r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in r)
    ]
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]
    named = any(h in _EXPRESSION + _READING + _LEVEL_COLUMNS for h in header)
    body = rows[1:] if named else rows

    def column(names: tuple[str, ...], fallback: int | None) -> int | None:
        for index, name in enumerate(header):
            if named and name in names:
                return index
        return fallback

    word_col = column(_EXPRESSION, 0)
    read_col = column(_READING, 1 if len(header) > 1 else None)
    level_col = column(_LEVEL_COLUMNS, None)
    out = []
    for row in body:
        if word_col is None or word_col >= len(row):
            continue
        level = default_level
        if level_col is not None and level_col < len(row):
            level = _level_of(row[level_col]) or level
        if level is None:
            continue
        word = normalise(row[word_col].strip())
        reading = (
            normalise(row[read_col].strip()) if read_col is not None and read_col < len(row) else ""
        )
        if word:
            out.append((word, reading, level))
    return out


def load_jlpt(
    conn: sqlite3.Connection, files: list[tuple[Path, int | None]], now: float | None = None
) -> int:
    """Replace the JLPT lists with the given files; each is ``(path, level or None)``."""
    rows: dict[tuple[str, str], int] = {}
    for path, level in files:
        if level is None:
            level = _level_of(path.stem)
        for word, reading, found in parse_jlpt(path.read_text(encoding="utf-8-sig"), level):
            key = (word, reading)
            rows[key] = max(found, rows.get(key, found))  # a word in two lists keeps the easier
    if not rows:
        raise DictError("no JLPT words found; give a CSV with a word column and a level")
    with conn:
        conn.execute("DELETE FROM level_word WHERE language = 'ja'")
        conn.executemany(
            "INSERT INTO level_word (language, lemma, reading, level) VALUES ('ja', ?, ?, ?)",
            [(w, r, level) for (w, r), level in rows.items()],
        )
        conn.execute(
            "INSERT OR REPLACE INTO dict_meta (name, version, source, sha256, entries, loaded_at)"
            " VALUES ('jlpt', NULL, ?, NULL, ?, ?)",
            (", ".join(p.name for p, _ in files), len(rows), time.time() if now is None else now),
        )
    return len(rows)


# --- CC-CEDICT -----------------------------------------------------------------------------

_CEDICT_LINE = re.compile(r"^(\S+) (\S+) \[([^\]]*)\] /(.*)/\s*$")
_SYLLABLE = re.compile(r"([A-Za-z:]+?)([1-5])(?![0-9])")
_TONE_MARKS = {
    "a": "āáǎàa",
    "e": "ēéěèe",
    "i": "īíǐìi",
    "o": "ōóǒòo",
    "u": "ūúǔùu",
    "ü": "ǖǘǚǜü",
}
# Entries that only point at another entry make poor glosses for a word.
_POINTER_GLOSS = (
    "surname ",
    "variant of",
    "old variant of",
    "unofficial variant of",
    "japanese variant of",
    "erhua variant",
    "used in ",
    "see ",
    "abbr. for",
)
# Entries whose first sense is bound, literary, regional or dated: keep, but prefer another.
_MARKED_GLOSS = ("(bound form)", "(literary)", "(archaic)", "(old)", "(dialect)", "(tw)")


def _mark_syllable(match: re.Match) -> str:
    syllable, tone = match.group(1), int(match.group(2))
    lower = syllable.lower().replace("u:", "ü").replace("v", "ü")
    if "a" in lower:
        target = lower.index("a")
    elif "e" in lower:
        target = lower.index("e")
    elif "ou" in lower:
        target = lower.index("o")
    else:
        vowels = [i for i, c in enumerate(lower) if c in _TONE_MARKS]
        if not vowels:
            return lower
        target = vowels[-1]
    marked = lower[:target] + _TONE_MARKS[lower[target]][tone - 1] + lower[target + 1 :]
    return marked[0].upper() + marked[1:] if syllable[0].isupper() else marked


def pinyin_marks(numeric: str) -> str:
    """``ni3 hao3`` -> ``nǐ hǎo``; ``lu:e4`` -> ``lüè``. Anything without a tone stays."""
    return _SYLLABLE.sub(_mark_syllable, numeric)


def parse_cedict_line(line: str) -> dict | None:
    """One CC-CEDICT entry, or None for comments and lines that don't parse."""
    if line.startswith("#"):
        return None
    match = _CEDICT_LINE.match(line)
    if not match:
        return None
    traditional, simplified, pinyin, body = match.groups()
    meanings = [m for m in body.split("/") if m]
    return {
        "traditional": normalise(traditional),
        "simplified": normalise(simplified),
        "pinyin": pinyin_marks(pinyin),
        "meanings": meanings,
    }


def cedict_gloss(meanings: list[str]) -> str:
    """A short English gloss: the first three meanings, without classifier notes."""
    kept = [m for m in meanings if not m.startswith("CL:")][:3]
    text = "; ".join(kept)
    return text if len(text) <= GLOSS_MAX else text[: GLOSS_MAX - 1].rstrip(", ;") + "…"


def _weakness(meanings: list[str]) -> int:
    """0 for an ordinary entry, 1 for a marked first sense, 2 for a pointer to another entry."""
    first = meanings[0].lower() if meanings else ""
    if not first or first.startswith(_POINTER_GLOSS):
        return 2
    return 1 if first.startswith(_MARKED_GLOSS) else 0


def _read_text(path: Path) -> str:
    """The text of a CC-CEDICT file: plain, ``.gz`` or a ``.zip`` holding one text file."""
    name = path.name.lower()
    if name.endswith(".gz"):
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    if name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.namelist() if m.lower().endswith((".u8", ".txt"))]
            if not members:
                raise DictError(f"{path.name} contains no CC-CEDICT text file")
            return archive.read(members[0]).decode("utf-8")
    return path.read_text(encoding="utf-8")


def cedict_version(text: str) -> str:
    for line in text.splitlines()[:40]:
        if line.startswith("#!") and "date=" in line:
            return line.split("date=", 1)[1].strip()
    return ""


def load_cedict(conn: sqlite3.Connection, path: Path, now: float | None = None) -> dict:
    """Load CC-CEDICT: forms, then pinyin and glosses onto matching Chinese lemmas."""
    text = _read_text(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    wanted: dict[str, list[int]] = {}
    for row in conn.execute(
        "SELECT id, lemma FROM lemma WHERE language = 'zh' AND pos != ?",
        (languages.ZH.name_pos,),
    ):
        wanted.setdefault(row["lemma"], []).append(row["id"])

    best: dict[str, tuple[tuple, dict]] = {}
    forms: list[tuple[str, int]] = []
    entries = 0
    for line in text.splitlines():
        entry = parse_cedict_line(line)
        if entry is None:
            continue
        entries += 1
        forms.extend(
            (form, entries) for form in dict.fromkeys((entry["simplified"], entry["traditional"]))
        )
        word = entry["simplified"]
        if word in wanted:
            key = (_weakness(entry["meanings"]), entries)
            if word not in best or key < best[word][0]:
                best[word] = (key, {**entry, "id": entries})
    with conn:
        conn.execute("DELETE FROM dict_form WHERE language = 'zh'")
        conn.executemany(
            "INSERT OR IGNORE INTO dict_form (language, form, entry_id) VALUES ('zh', ?, ?)",
            forms,
        )
        conn.execute(
            "UPDATE lemma SET gloss = NULL, dict_id = NULL, tags = NULL, reading = NULL"
            " WHERE language = 'zh'"
        )
        matched = 0
        for word, (_key, entry) in best.items():
            tags = "idiom" if any("(idiom)" in m for m in entry["meanings"]) else ""
            for lemma_id in wanted[word]:
                conn.execute(
                    "UPDATE lemma SET gloss = ?, dict_id = ?, tags = ?, reading = ? WHERE id = ?",
                    (
                        cedict_gloss(entry["meanings"]) or None,
                        entry["id"],
                        tags,
                        entry["pinyin"],
                        lemma_id,
                    ),
                )
                matched += 1
        conn.execute(
            "INSERT OR REPLACE INTO dict_meta (name, version, source, sha256, entries, loaded_at)"
            " VALUES ('cedict', ?, ?, ?, ?, ?)",
            (cedict_version(text), path.name, sha, entries, time.time() if now is None else now),
        )
    return {"entries": entries, "forms": len(forms), "lemmas_matched": matched}


# --- HSK lists -------------------------------------------------------------------------------


def parse_hsk(text: str) -> list[tuple[str, str, int]]:
    """``(word, pinyin, level)`` for the HSK 3.0 levels in a complete-hsk-vocabulary JSON.

    Level 7 means HSK 7-9. A word in several levels keeps the easiest.
    """
    try:
        entries = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DictError(f"the HSK list is not valid JSON: {exc}") from exc
    out: dict[str, tuple[str, int]] = {}
    for entry in entries:
        levels = [
            int(level.split("-", 1)[1])
            for level in entry.get("level", [])
            if re.fullmatch(r"new-[1-7]", level)
        ]
        word = normalise(entry.get("simplified", "").strip())
        if not levels or not word:
            continue
        forms = entry.get("forms") or [{}]
        pinyin = forms[0].get("transcriptions", {}).get("pinyin", "")
        if word not in out or min(levels) < out[word][1]:
            out[word] = (pinyin, min(levels))
    return [(w, p, level) for w, (p, level) in out.items()]


def load_hsk(conn: sqlite3.Connection, path: Path, now: float | None = None) -> int:
    """Replace the HSK 3.0 list with the one in ``path`` (complete.json from the project)."""
    rows = parse_hsk(path.read_text(encoding="utf-8"))
    if not rows:
        raise DictError("no HSK 3.0 words found in the file")
    with conn:
        conn.execute("DELETE FROM level_word WHERE language = 'zh'")
        conn.executemany(
            "INSERT OR REPLACE INTO level_word (language, lemma, reading, level)"
            " VALUES ('zh', ?, ?, ?)",
            [(w, p, level) for w, p, level in rows],
        )
        conn.execute(
            "INSERT OR REPLACE INTO dict_meta (name, version, source, sha256, entries, loaded_at)"
            " VALUES ('hsk', NULL, ?, NULL, ?, ?)",
            (path.name, len(rows), time.time() if now is None else now),
        )
    return len(rows)


# --- downloading -------------------------------------------------------------------------


def dicts_dir(root: Path) -> Path:
    return root / "dicts"


def _download(client: httpx.Client, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with client.stream("GET", url, follow_redirects=True) as response:
        if response.status_code != 200:
            raise DictError(f"{url} answered HTTP {response.status_code}")
        with dest.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)


def fetch_jmdict(root: Path, client: httpx.Client, say=lambda _m: None) -> Path:
    """Download the newest full English JMdict JSON build from jmdict-simplified."""
    response = client.get(JMDICT_RELEASES, follow_redirects=True)
    if response.status_code != 200:
        raise DictError(f"the release list answered HTTP {response.status_code}")
    assets = response.json().get("assets", [])
    names = [a["name"] for a in assets]
    for asset in assets:
        name = asset["name"]
        if JMDICT_ASSET.fullmatch(name):
            dest = dicts_dir(root) / name
            say(f"downloading {name} ({asset.get('size', 0) // 1_000_000} MB)")
            _download(client, asset["browser_download_url"], dest)
            return dest
    raise DictError(
        "no jmdict-eng-*.json.zip asset in the latest release; found: " + ", ".join(names)
    )


def fetch_jlpt(root: Path, client: httpx.Client, say=lambda _m: None) -> list[tuple[Path, int]]:
    out = []
    for level, url in JLPT_URLS.items():
        dest = dicts_dir(root) / f"jlpt-n{level}.csv"
        say(f"downloading JLPT N{level}")
        _download(client, url, dest)
        out.append((dest, level))
    return out


def fetch_cedict(root: Path, client: httpx.Client, say=lambda _m: None) -> Path:
    """Download CC-CEDICT from MDBG."""
    dest = dicts_dir(root) / "cedict_1_0_ts_utf-8_mdbg.zip"
    say("downloading CC-CEDICT")
    _download(client, CEDICT_URL, dest)
    return dest


def fetch_hsk(root: Path, client: httpx.Client, say=lambda _m: None) -> Path:
    """Download the HSK vocabulary lists (complete.json, about 10 MB)."""
    dest = dicts_dir(root) / "hsk-complete.json"
    say("downloading the HSK lists")
    _download(client, HSK_URL, dest)
    return dest


def new_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60)


def status(conn: sqlite3.Connection, lang: str = "ja") -> dict:
    meta = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM dict_meta")}
    glossed = conn.execute(
        "SELECT COUNT(*) FROM lemma WHERE gloss IS NOT NULL AND corpus_rank IS NOT NULL"
        " AND language = ?",
        (lang,),
    ).fetchone()[0]
    ranked = conn.execute(
        "SELECT COUNT(*) FROM lemma WHERE corpus_rank IS NOT NULL AND language = ?", (lang,)
    ).fetchone()[0]
    return {"meta": meta, "ranked_lemmas": ranked, "glossed_lemmas": glossed}
