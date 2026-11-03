"""The learner: placement test, profile, word marks, domain fixes and novel feedback."""

from __future__ import annotations

import math
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ...learner import LANGUAGE, placement
from ...learner.coverage import (
    domain_strengths,
    jlpt_estimate,
    vocabulary_size,
    weakest_domain,
)
from ...learner.domains import DOMAIN_KEYS
from ...learner.model import MODEL_VERSION, refit
from ..personal import Context, open_context

router = APIRouter()


def _context(request: Request) -> Context:
    return open_context(request)


# --- test ---------------------------------------------------------------------------------


class StartBody(BaseModel):
    kind: Literal["full", "quick"] = "full"


class AnswerBody(BaseModel):
    known: bool | None = None  # word or fake
    choice: int | None = None  # meaning
    tapped: list[int] = []  # passage: token indexes
    rating: str | None = None
    cloze_choice: int | None = None


@router.get("/test/status")
def test_status(request: Request) -> dict:
    ctx = _context(request)
    try:
        pool = ctx.pool()
        excerpts = ctx.catalog.execute("SELECT COUNT(*) FROM excerpt").fetchone()[0]
        unfinished = ctx.profile.execute(
            "SELECT id, kind FROM test_session WHERE language = ? AND finished_at IS NULL"
            " ORDER BY id DESC LIMIT 1",
            (LANGUAGE,),
        ).fetchone()
        last = ctx.profile.execute(
            "SELECT id, kind, finished_at FROM test_session WHERE language = ?"
            " AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1",
            (LANGUAGE,),
        ).fetchone()
        ranked = ctx.catalog.execute(
            "SELECT COUNT(*) FROM lemma WHERE corpus_rank IS NOT NULL"
        ).fetchone()[0]
        problems = []
        if len(pool.words) < 200:
            problems.append(
                "Too few glossed words to test with. Collect novels (`wn syosetu run`), then "
                "load JMdict (`wn dict fetch`) and run `wn analyse --domains`."
            )
        return {
            "ready": not problems,
            "problems": problems,
            "test_words": len(pool.words),
            "ranked_words": ranked,
            "excerpts": excerpts,
            "answers": ctx.learner.params.answers,
            "unfinished": dict(unfinished) if unfinished else None,
            "last": dict(last) if last else None,
        }
    finally:
        ctx.close()


@router.post("/test/start")
def test_start(body: StartBody, request: Request) -> dict:
    ctx = _context(request)
    try:
        if len(ctx.pool().words) < 200:
            raise HTTPException(
                409, "not enough glossed words to run the test; see /api/test/status"
            )
        session = placement.start(ctx.profile, body.kind)
        return {"session": session, **_current(ctx, session)}
    finally:
        ctx.close()


def _current(ctx: Context, session: int) -> dict:
    try:
        return placement.current(ctx.profile, ctx.catalog, session, ctx.learner.lexicon, ctx.pool())
    except placement.PlacementError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/test/{session}/next")
def test_next(session: int, request: Request) -> dict:
    ctx = _context(request)
    try:
        return _current(ctx, session)
    finally:
        ctx.close()


@router.post("/test/{session}/answer")
def test_answer(session: int, body: AnswerBody, request: Request) -> dict:
    ctx = _context(request)
    try:
        payload = body.model_dump()
        return placement.answer(
            ctx.profile, ctx.catalog, session, payload, ctx.learner.lexicon, ctx.pool()
        )
    except placement.PlacementError as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        ctx.close()


# --- profile ------------------------------------------------------------------------------


@router.get("/profile")
def get_profile(request: Request) -> dict:
    ctx = _context(request)
    try:
        params = ctx.learner.params
        strengths = domain_strengths(ctx.catalog, ctx.learner)
        passages = ctx.profile.execute(
            "SELECT predicted, rating FROM passage_result ORDER BY id DESC LIMIT 20"
        ).fetchall()
        feedback = ctx.profile.execute(
            "SELECT id, novel, title, felt, predicted, note, at FROM novel_feedback"
            " ORDER BY id DESC LIMIT 50"
        ).fetchall()
        marked = ctx.profile.execute(
            "SELECT SUM(known), SUM(1 - known) FROM word_status WHERE language = ?", (LANGUAGE,)
        ).fetchone()
        return {
            "tested": ctx.tested,
            "answers": params.answers,
            "vocabulary": vocabulary_size(params),
            "vocabulary_range": [
                round(math.exp(params.theta - params.theta_sd)),
                round(math.exp(params.theta + params.theta_sd)),
            ],
            "guess_rate": params.guess_rate,
            "jlpt": jlpt_estimate(ctx.catalog, ctx.learner),
            "domains": strengths,
            "weakest_domain": weakest_domain(strengths),
            "marked": {"known": marked[0] or 0, "unknown": marked[1] or 0},
            "passages": [dict(p) for p in passages],
            "feedback": [dict(f) for f in feedback],
            "model_version": MODEL_VERSION,
        }
    finally:
        ctx.close()


# --- words --------------------------------------------------------------------------------


class StatusBody(BaseModel):
    lemma_id: int
    known: bool | None  # None clears the mark


class DomainBody(BaseModel):
    lemma_id: int
    domain: str
    action: Literal["add", "remove", "clear"]


def _lemma(ctx: Context, lemma_id: int):
    row = ctx.catalog.execute(
        "SELECT id, lemma, pos FROM lemma WHERE id = ? AND language = ?", (lemma_id, LANGUAGE)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "no such word")
    return row


@router.get("/words")
def list_words(
    request: Request,
    q: str | None = Query(None, description="Part of the word or its reading."),
    status: Literal["known", "unknown", "marked", "any"] = "any",
    domain: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    ctx = _context(request)
    try:
        where, args = (
            ["l.language = ?", "l.corpus_rank IS NOT NULL", "l.is_function = 0"],
            [LANGUAGE],
        )
        where.append("l.pos != '固有名詞'")
        if q:
            like = f"%{q.replace('%', '').replace('_', '')}%"
            where.append("(l.lemma LIKE ? OR l.reading LIKE ?)")
            args += [like, like]
        rows = ctx.catalog.execute(
            "SELECT l.id, l.lemma, l.pos, l.reading, l.gloss, l.corpus_rank FROM lemma l WHERE "
            + " AND ".join(where)
            + " ORDER BY l.corpus_rank",
            args,
        ).fetchall()
        status_map = ctx.learner.status
        weights = ctx.learner.lexicon.weights  # includes the learner's own domain fixes
        items = []
        for r in rows:
            if domain and not any(d == domain and w >= 0.3 for d, w in weights.get(r["id"], [])):
                continue
            mark = status_map.get((r["lemma"], r["pos"]))
            if status == "known" and mark is not True:
                continue
            if status == "unknown" and mark is not False:
                continue
            if status == "marked" and mark is None:
                continue
            items.append((r, mark))
        total = len(items)
        page = items[offset : offset + limit]
        lex = ctx.learner.lexicon
        return {
            "total": total,
            "items": [
                {
                    "lemma_id": r["id"],
                    "lemma": r["lemma"],
                    "pos": r["pos"],
                    "reading": r["reading"],
                    "gloss": r["gloss"],
                    "rank": r["corpus_rank"],
                    "marked": mark,
                    "p": round(ctx.learner.p(r["id"]), 3),
                    "domains": [
                        {"domain": d, "weight": w} for d, w in lex.weights.get(r["id"], [])
                    ],
                }
                for r, mark in page
            ],
        }
    finally:
        ctx.close()


@router.put("/words/status", status_code=204)
def set_word_status(body: StatusBody, request: Request) -> None:
    ctx = _context(request)
    try:
        word = _lemma(ctx, body.lemma_id)
        now = time.time()
        with ctx.profile:
            if body.known is None:
                ctx.profile.execute(
                    "DELETE FROM word_status WHERE language = ? AND lemma = ? AND pos = ?",
                    (LANGUAGE, word["lemma"], word["pos"]),
                )
            else:
                ctx.profile.execute(
                    "INSERT OR REPLACE INTO word_status (language, lemma, pos, known, at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (LANGUAGE, word["lemma"], word["pos"], int(body.known), now),
                )
                ctx.profile.execute(
                    "INSERT INTO answer (session_id, language, kind, lemma, pos, known, weight, at)"
                    " VALUES (NULL, ?, 'mark', ?, ?, ?, 1.0, ?)",
                    (LANGUAGE, word["lemma"], word["pos"], int(body.known), now),
                )
        refit(ctx.profile, ctx.learner.lexicon)
    finally:
        ctx.close()


@router.put("/words/domains", status_code=204)
def set_word_domain(body: DomainBody, request: Request) -> None:
    if body.domain not in DOMAIN_KEYS:
        raise HTTPException(422, "unknown domain")
    ctx = _context(request)
    try:
        word = _lemma(ctx, body.lemma_id)
        with ctx.profile:
            if body.action == "clear":
                ctx.profile.execute(
                    "DELETE FROM domain_fix WHERE language = ? AND lemma = ? AND pos = ?"
                    " AND domain = ?",
                    (LANGUAGE, word["lemma"], word["pos"], body.domain),
                )
            else:
                ctx.profile.execute(
                    "INSERT OR REPLACE INTO domain_fix (language, lemma, pos, domain, action)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (LANGUAGE, word["lemma"], word["pos"], body.domain, body.action),
                )
    finally:
        ctx.close()


@router.get("/domains")
def list_domains(request: Request) -> list[dict]:
    ctx = _context(request)
    try:
        return [
            dict(r)
            for r in ctx.catalog.execute(
                "SELECT key, name_en, name_ja FROM domain ORDER BY position"
            )
        ]
    finally:
        ctx.close()


# --- feedback -----------------------------------------------------------------------------


class FeedbackBody(BaseModel):
    felt: Literal["easier", "right", "harder"]
    note: str | None = None


@router.post("/novels/{novel_id}/feedback", status_code=204)
def post_feedback(novel_id: int, body: FeedbackBody, request: Request) -> None:
    ctx = _context(request)
    try:
        novel = ctx.catalog.execute(
            "SELECT n.external_id, n.title, s.name FROM novel n JOIN source s ON s.id = n.source_id"
            " WHERE n.id = ?",
            (novel_id,),
        ).fetchone()
        if novel is None:
            raise HTTPException(404, "no such novel")
        fit = ctx.fits().get(novel_id) if ctx.tested else None
        with ctx.profile:
            ctx.profile.execute(
                "INSERT INTO novel_feedback (source, novel, title, felt, predicted, note, at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    novel["name"],
                    novel["external_id"],
                    novel["title"],
                    body.felt,
                    fit.coverage if fit else None,
                    (body.note or "").strip()[:500] or None,
                    time.time(),
                ),
            )
    finally:
        ctx.close()
