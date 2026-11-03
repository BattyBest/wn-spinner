"""Chapter pages: where to fetch, how to read the body, and which chapter comes next."""

from __future__ import annotations

import re
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser

# Character targets for the two passes (see the milestone 2 plan).
FIRST_PASS_CHARS = 10_000
DEEP_PASS_CHARS = 20_000
MAX_PAGES = 12  # a safety stop per novel and run, whatever the chapters' lengths


class ParseError(Exception):
    """The page has no chapter body we recognise. Fail loudly rather than return nothing."""


def chapter_url(ncode: str, number: int, kind: str) -> str:
    if kind == "short":
        return f"https://ncode.syosetu.com/{ncode}/"
    return f"https://ncode.syosetu.com/{ncode}/{number}/"


@dataclass
class Chapter:
    title: str | None
    text: str  # body paragraphs, ruby readings removed, one paragraph per line

    @property
    def chars(self) -> int:
        return len(re.sub(r"\s", "", self.text))


def parse_chapter(html: bytes | str) -> Chapter:
    """Read the story text from a chapter page.

    The current layout puts the story in ``div.js-novel-text`` blocks, with the author's
    preface and afterword as separate blocks carrying their own modifier classes; the
    older layout used ``#novel_honbun``. Only the story body is returned. Ruby is split so
    the base text stays and the furigana (``rt`` and ``rp``) is dropped.
    """
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    tree = LexborHTMLParser(html)
    body = None
    for block in tree.css("div.js-novel-text"):
        classes = block.attributes.get("class") or ""
        if "p-novel__text--preface" in classes or "p-novel__text--afterword" in classes:
            continue
        body = block
        break
    if body is None:
        body = tree.css_first("#novel_honbun")
    if body is None:
        raise ParseError("no chapter body found; Syosetu may have changed its page layout")
    for node in body.css("rt, rp"):
        node.decompose()
    lines = [p.text().strip() for p in body.css("p")]
    while lines and not lines[-1]:
        lines.pop()
    text = "\n".join(lines)
    if not text.strip():
        raise ParseError("the chapter body is empty")
    title_node = tree.css_first("h1.p-novel__title--rensai, h1.p-novel__title, .novel_subtitle")
    title = title_node.text().strip() if title_node else None
    return Chapter(title or None, text)


def next_chapter(
    kind: str, chapter_count: int | None, done: dict[int, int], target_chars: int
) -> int | None:
    """The next chapter number to fetch, or None when the sample is complete.

    ``done`` maps chapter number to its length in characters. Chapters are read in order
    from chapter 1; once half the target is reached, one chapter from near the middle of
    a long serial is taken too, since vocabulary drifts as a story goes on.
    """
    if sum(done.values()) >= target_chars or len(done) >= MAX_PAGES:
        return None
    if kind == "short":
        return None if done else 1
    last = chapter_count or 1
    middle = last // 2
    if last >= 12 and middle not in done and sum(done.values()) >= target_chars / 2:
        return middle
    for number in range(1, last + 1):
        if number not in done:
            return number
    return None
