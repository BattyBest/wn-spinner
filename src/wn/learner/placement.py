"""The placement test: an adaptive word check, then short passages.

The server runs the test. Each answer is stored, the model is refitted from every stored
answer, and the next item is chosen where the model is least sure. A session keeps its
state in profile.db, so a test can be left and resumed. See the plan for the rules.

Part A: words, one at a time. About one in five is a made-up word; every tenth word you
claim to know is followed by a 4-way meaning check. Part B: passages (full test only) where
you tap the words you don't know, rate your understanding and answer one cloze question.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import time
from dataclasses import dataclass, field

from ..analysis.japanese import NAME_POS, iter_tokens
from . import LANGUAGE
from .domains import DOMAIN_KEYS
from .model import (
    DELTA_PRIOR_SD,
    THETA_PRIOR,
    Learner,
    Lexicon,
    load_fixes,
    load_params,
    load_status,
    p_know,
    refit,
)

PART_A_ITEMS = {"full": 60, "quick": 20}
PASSAGES = {"full": 5, "quick": 0}
FAKE_SHARE = 0.2
MEANING_EVERY = 10  # claimed known words
CONTENT_POS = ("名詞", "動詞", "形容詞", "形状詞", "副詞")
MIN_NOVELS = 3  # a test word must appear in this many novels
NEAREST = 5  # pick at random among this many words closest to a 50% chance
PASSAGE_RANGE = (0.85, 0.97)
PASSAGE_WIDE = (0.70, 0.995)
PASSAGE_TARGET = 0.92

_KANJI = re.compile(r"^[一-鿿]+$")
_KATAKANA = re.compile(r"^[ァ-ヶー]+$")
_MORAE = "カキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモラリルレロ"


class PlacementError(Exception):
    pass


@dataclass
class Candidate:
    lemma_id: int
    lemma: str
    pos: str
    reading: str | None
    gloss: str
    rank: int


@dataclass
class Pool:
    """The words the test may ask about, and the forms it must not invent."""

    words: dict[int, Candidate] = field(default_factory=dict)
    forms: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, catalog: sqlite3.Connection) -> Pool:
        pool = cls()
        marks = ",".join("?" * len(CONTENT_POS))
        rows = catalog.execute(
            "SELECT l.id, l.lemma, l.pos, l.reading, l.gloss, l.corpus_rank FROM lemma l"
            " WHERE l.language = ? AND l.gloss IS NOT NULL AND l.corpus_rank IS NOT NULL"
            f" AND l.is_function = 0 AND l.pos IN ({marks})"
            " AND (SELECT COUNT(*) FROM novel_lemma nl"
            "      WHERE nl.lemma_id = l.id AND nl.is_name = 0) >= ?",
            (LANGUAGE, *CONTENT_POS, MIN_NOVELS),
        )
        for r in rows:
            if len(r["lemma"]) < 2 and not _KANJI.match(r["lemma"]):
                continue
            pool.words[r["id"]] = Candidate(
                r["id"], r["lemma"], r["pos"], r["reading"], r["gloss"], r["corpus_rank"]
            )
        pool.forms = {r[0] for r in catalog.execute("SELECT form FROM dict_form")}
        return pool


# --- state ---------------------------------------------------------------------------------


def start(profile: sqlite3.Connection, kind: str = "full", now: float | None = None) -> int:
    """Begin a session, or return the unfinished one of the same kind."""
    row = profile.execute(
        "SELECT id FROM test_session WHERE language = ? AND kind = ? AND finished_at IS NULL"
        " ORDER BY id DESC LIMIT 1",
        (LANGUAGE, kind),
    ).fetchone()
    if row:
        return row[0]
    seed = random.SystemRandom().randrange(1 << 30)
    items = PART_A_ITEMS[kind]
    rng = random.Random(seed)
    fake_slots = sorted(rng.sample(range(items), round(items * FAKE_SHARE)))
    state = {
        "kind": kind,
        "seed": seed,
        "part": "A",
        "done_a": 0,
        "fake_slots": fake_slots,
        "claims": 0,
        "queue": [],
        "pending": None,
        "asked": [],
        "passages": 0,
        "used_excerpts": [],
        "used_novels": [],
    }
    with profile:
        cursor = profile.execute(
            "INSERT INTO test_session (language, kind, state, started_at) VALUES (?, ?, ?, ?)",
            (LANGUAGE, kind, json.dumps(state), time.time() if now is None else now),
        )
    return cursor.lastrowid


def _load(profile: sqlite3.Connection, session_id: int) -> tuple[dict, bool]:
    row = profile.execute(
        "SELECT state, finished_at FROM test_session WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise PlacementError("no such test session")
    return json.loads(row["state"]), row["finished_at"] is not None


def _save(profile: sqlite3.Connection, session_id: int, state: dict, finished: float | None = None):
    with profile:
        profile.execute(
            "UPDATE test_session SET state = ?, finished_at = COALESCE(?, finished_at)"
            " WHERE id = ?",
            (json.dumps(state, ensure_ascii=False), finished, session_id),
        )


def progress(state: dict) -> dict:
    total_a = PART_A_ITEMS[state["kind"]]
    return {
        "kind": state["kind"],
        "part": state["part"],
        "words_done": state["done_a"],
        "words_total": total_a,
        "passages_done": state["passages"],
        "passages_total": PASSAGES[state["kind"]],
    }


# --- choosing items ----------------------------------------------------------------------


def _learner(profile: sqlite3.Connection, lexicon: Lexicon) -> Learner:
    return Learner(load_params(profile), lexicon, load_status(profile))


def _asked_ids(state: dict) -> set[int]:
    return {a["lemma_id"] for a in state["asked"] if a.get("lemma_id")}


def _visible_word(c: Candidate, domain: str | None) -> dict:
    return {
        "type": "word",
        "lemma_id": c.lemma_id,
        "lemma": c.lemma,
        "pos": c.pos,
        "reading": c.reading,
        "domain": domain,
    }


def choose_word(state: dict, learner: Learner, pool: Pool, rng: random.Random) -> dict:
    """The word where an answer teaches the model most: least certain target, chance near 50%."""
    params = learner.params
    lex = learner.lexicon
    targets: dict[str | None, float] = {None: params.theta_sd / THETA_PRIOR[1]}
    for key in DOMAIN_KEYS:
        targets[key] = params.delta_sds[key] / DELTA_PRIOR_SD
    asked = _asked_ids(state)
    in_domain: dict[str | None, list[Candidate]] = {}
    for c in pool.words.values():
        if c.lemma_id in asked:
            continue
        weights = lex.weights.get(c.lemma_id, [])
        strong = [d for d, w in weights if w >= 0.5]
        for key in strong or [None]:
            in_domain.setdefault(key, []).append(c)
    order = sorted(
        (k for k in targets if in_domain.get(k)),
        key=lambda k: -(targets[k] + rng.random() * 0.05),
    )
    if not order:
        raise PlacementError(
            "no words are available to test; run the collection and `wn dict fetch`"
        )
    key = order[0]
    chosen = sorted(
        in_domain[key],
        key=lambda c: abs(p_know(params, c.rank, lex.weights.get(c.lemma_id, [])) - 0.5),
    )[:NEAREST]
    return _visible_word(rng.choice(chosen), key)


def make_fake(pool: Pool, rng: random.Random) -> dict:
    """A plausible non-word: two real two-kanji words recombined, or a katakana word changed."""
    kanji = [c.lemma for c in pool.words.values() if len(c.lemma) == 2 and _KANJI.match(c.lemma)]
    kata = [
        c.lemma for c in pool.words.values() if 4 <= len(c.lemma) <= 7 and _KATAKANA.match(c.lemma)
    ]
    for _ in range(200):
        if kanji and (not kata or rng.random() < 0.6):
            a, b = rng.sample(kanji, 2)
            text = a[0] + b[1]
        elif kata:
            word = rng.choice(kata)
            at = rng.randrange(1, len(word) - 1)
            if word[at] not in _MORAE:
                continue
            text = word[:at] + rng.choice(_MORAE.replace(word[at], "")) + word[at + 1 :]
        else:
            break
        if text in pool.forms or any(c.lemma == text for c in pool.words.values()):
            continue
        tokens = [w for _s, w in iter_tokens(text) if w is not None]
        if len(tokens) == 1 and not tokens[0].oov and tokens[0].lemma == text:
            continue  # the tokenizer knows it as one word
        return {"type": "fake", "text": text}
    raise PlacementError("could not make a test word; is JMdict loaded?")


def make_meaning(pool: Pool, asked_word: dict, rng: random.Random) -> dict:
    """Pick the English meaning of a word you said you know, from four."""
    target = pool.words[asked_word["lemma_id"]]
    same = [c for c in pool.words.values() if c.lemma_id != target.lemma_id and c.pos == target.pos]
    for spread in (2.0, 4.0, 1e9):
        near = [
            c
            for c in same
            if target.rank / spread <= c.rank <= target.rank * spread and c.gloss != target.gloss
        ]
        if len(near) >= 3:
            break
    else:
        raise PlacementError("not enough words for a meaning check")
    options = [target.gloss] + [c.gloss for c in rng.sample(near, 3)]
    rng.shuffle(options)
    return {
        "type": "meaning",
        "lemma_id": target.lemma_id,
        "lemma": target.lemma,
        "pos": target.pos,
        "reading": target.reading,
        "choices": options,
        "correct": options.index(target.gloss),
    }


def _content_tokens(tokens: list[list], lexicon: Lexicon) -> list[int]:
    return [
        i
        for i, (_surface, lemma_id, pos) in enumerate(tokens)
        if lemma_id is not None
        and pos != NAME_POS
        and lemma_id not in lexicon.function
        and lemma_id not in lexicon.names
    ]


def passage_coverage(tokens: list[list], learner: Learner) -> float | None:
    counted = [learner.p(t[1]) for t in tokens if t[1] is not None and t[2] != NAME_POS]
    return sum(counted) / len(counted) if counted else None


def choose_passage(
    state: dict, learner: Learner, pool: Pool, catalog: sqlite3.Connection, rng: random.Random
) -> dict | None:
    """A passage near your level from a domain the model is still unsure about."""
    params = learner.params
    lex = learner.lexicon
    unsure = max(DOMAIN_KEYS, key=lambda k: params.delta_sds[k])
    best: list[tuple[float, dict]] = []
    for low, high in (PASSAGE_RANGE, PASSAGE_WIDE):
        for row in catalog.execute("SELECT id, novel_id, text, tokens FROM excerpt"):
            if row["id"] in state["used_excerpts"] or row["novel_id"] in state["used_novels"]:
                continue
            tokens = json.loads(row["tokens"])
            cov = passage_coverage(tokens, learner)
            if cov is None or not low <= cov <= high:
                continue
            ids = [t[1] for t in tokens if t[1] is not None]
            share = sum(
                1 for i in ids if any(d == unsure and w >= 0.3 for d, w in lex.weights.get(i, []))
            ) / max(len(ids), 1)
            score = -abs(cov - PASSAGE_TARGET) + 0.5 * share + rng.random() * 0.01
            best.append((score, {"row": row, "tokens": tokens, "cov": cov}))
        if best:
            break
    if not best:
        return None
    _score, pick = max(best, key=lambda b: b[0])
    row, tokens = pick["row"], pick["tokens"]
    cloze = _make_cloze(tokens, pool, rng)
    return {
        "type": "passage",
        "excerpt_id": row["id"],
        "novel_id": row["novel_id"],
        "tokens": tokens,
        "predicted": pick["cov"],
        "tappable": _content_tokens(tokens, lex),
        "cloze": cloze,
    }


def _make_cloze(tokens: list[list], pool: Pool, rng: random.Random) -> dict | None:
    spots = [
        i
        for i, (surface, lemma_id, pos) in enumerate(tokens)
        if lemma_id in pool.words and pos == "名詞" and pool.words[lemma_id].lemma == surface
    ]
    rng.shuffle(spots)
    for index in spots:
        target = pool.words[tokens[index][1]]
        near = [
            c
            for c in pool.words.values()
            if c.pos == "名詞"
            and c.lemma != target.lemma
            and target.rank / 3 <= c.rank <= target.rank * 3
        ]
        if len(near) >= 3:
            options = [target.lemma] + [c.lemma for c in rng.sample(near, 3)]
            rng.shuffle(options)
            return {"index": index, "choices": options, "correct": options.index(target.lemma)}
    return None


# --- the session loop ---------------------------------------------------------------------


def _public(item: dict | None) -> dict | None:
    """The item without its answers."""
    if item is None:
        return None
    hidden = {"correct", "lemma_id", "novel_id", "predicted"}
    out = {k: v for k, v in item.items() if k not in hidden}
    if item["type"] == "passage":
        tappable = set(item["tappable"])
        out["tokens"] = [[t[0], i in tappable] for i, t in enumerate(item["tokens"])]
        out.pop("tappable")
        if item.get("cloze"):
            out["cloze"] = {"index": item["cloze"]["index"], "choices": item["cloze"]["choices"]}
    return out


def current(
    profile: sqlite3.Connection,
    catalog: sqlite3.Connection,
    session_id: int,
    lexicon: Lexicon,
    pool: Pool,
) -> dict:
    """The item waiting for an answer, chosen now if there is none."""
    state, finished = _load(profile, session_id)
    if finished:
        return {"item": None, "progress": progress(state), "done": True}
    if state["pending"] is None:
        _advance(profile, catalog, session_id, state, lexicon, pool)
    done = state["part"] == "done"
    return {"item": _public(state["pending"]), "progress": progress(state), "done": done}


def _advance(profile, catalog, session_id, state, lexicon, pool) -> None:
    learner = _learner(profile, lexicon)
    rng = random.Random(state["seed"] * 1000 + len(state["asked"]) + state["passages"])
    item = None
    if state["queue"]:
        item = state["queue"].pop(0)
    elif state["part"] == "A":
        if state["done_a"] >= PART_A_ITEMS[state["kind"]]:
            state["part"] = "B"
        elif state["done_a"] in state["fake_slots"]:
            item = make_fake(pool, rng)
        else:
            item = choose_word(state, learner, pool, rng)
    if item is None and state["part"] == "B":
        if state["passages"] < PASSAGES[state["kind"]]:
            item = choose_passage(state, learner, pool, catalog, rng)
        if item is None:
            state["part"] = "done"
    state["pending"] = item
    finished = time.time() if state["part"] == "done" else None
    _save(profile, session_id, state, finished)


def _record(profile, session_id, kind, lemma, pos, known, weight, now) -> None:
    profile.execute(
        "INSERT INTO answer (session_id, language, kind, lemma, pos, known, weight, at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, LANGUAGE, kind, lemma, pos, int(known), weight, now),
    )


def answer(
    profile: sqlite3.Connection,
    catalog: sqlite3.Connection,
    session_id: int,
    payload: dict,
    lexicon: Lexicon,
    pool: Pool,
    now: float | None = None,
) -> dict:
    """Store the answer to the pending item, refit the model and report progress."""
    now = time.time() if now is None else now
    state, finished = _load(profile, session_id)
    item = state["pending"]
    if finished or item is None:
        raise PlacementError("there is no question waiting for an answer")
    rng = random.Random(state["seed"] + 7 * len(state["asked"]))
    with profile:
        kind = item["type"]
        if kind in ("word", "fake"):
            known = bool(payload.get("known"))
            if kind == "fake":
                _record(profile, session_id, "fake", None, None, known, 1.0, now)
            else:
                _record(profile, session_id, "word", item["lemma"], item["pos"], known, 1.0, now)
                if known:
                    state["claims"] += 1
                    if state["claims"] % MEANING_EVERY == 0:
                        state["queue"].append(make_meaning(pool, item, rng))
            state["done_a"] += 1
        elif kind == "meaning":
            choice = payload.get("choice")
            right = choice == item["correct"]
            _record(profile, session_id, "meaning", item["lemma"], item["pos"], right, 2.0, now)
            if not right:
                profile.execute(
                    "INSERT OR REPLACE INTO word_status (language, lemma, pos, known, at)"
                    " VALUES (?, ?, ?, 0, ?)",
                    (LANGUAGE, item["lemma"], item["pos"], now),
                )
        elif kind == "passage":
            _record_passage(profile, session_id, item, payload, lexicon, now)
            state["passages"] += 1
            state["used_excerpts"].append(item["excerpt_id"])
            state["used_novels"].append(item["novel_id"])
        state["asked"].append(
            {"type": kind, "lemma_id": item.get("lemma_id"), "text": item.get("text")}
        )
        state["pending"] = None
    _save(profile, session_id, state)
    refit(profile, lexicon)
    return current(profile, catalog, session_id, lexicon, pool)


def _record_passage(profile, session_id, item, payload, lexicon, now) -> None:
    tapped = {int(i) for i in payload.get("tapped", [])}
    seen: set[int] = set()
    for index in _content_tokens(item["tokens"], lexicon):
        surface, lemma_id, pos = item["tokens"][index]
        if lemma_id in seen:
            continue
        seen.add(lemma_id)
        lemma, lpos = lexicon.keys[lemma_id]
        if index in tapped:
            _record(profile, session_id, "tap", lemma, lpos, False, 1.0, now)
        else:
            _record(profile, session_id, "untapped", lemma, lpos, True, 0.3, now)
    rating = payload.get("rating")
    if rating not in ("almost_all", "most", "gist", "lost"):
        raise PlacementError("rating must be almost_all, most, gist or lost")
    cloze_ok = None
    cloze = item.get("cloze")
    if cloze and payload.get("cloze_choice") is not None:
        cloze_ok = payload["cloze_choice"] == cloze["correct"]
        lemma_id = item["tokens"][cloze["index"]][1]
        lemma, lpos = lexicon.keys[lemma_id]
        _record(profile, session_id, "meaning", lemma, lpos, cloze_ok, 2.0, now)
    profile.execute(
        "INSERT INTO passage_result (session_id, excerpt_id, predicted, rating, cloze_ok, at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, item["excerpt_id"], item["predicted"], rating, cloze_ok, now),
    )


def lexicon_for(profile: sqlite3.Connection, catalog: sqlite3.Connection) -> Lexicon:
    return Lexicon.load(catalog, load_fixes(profile))
