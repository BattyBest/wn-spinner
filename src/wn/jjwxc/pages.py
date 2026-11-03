"""jjwxc pages: where to fetch, and how to read rankings, book pages and chapters.

The site serves server-rendered HTML in GBK (declared as gb18030, its superset). A ranking
page lists 200 books in one table. A book page has the metadata, the content tags and one
row per chapter; a free chapter's row links to ``www.jjwxc.net/onebook.php``, a VIP row has
no link at all, only a ``rel`` pointing at my.jjwxc.net. Only free chapters are ever
requested: ``free_chapter_url`` is the one place a chapter URL is built, and it refuses
anything that is not a plain free chapter of that book.
"""

from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass, field

from selectolax.lexbor import LexborHTMLParser

from ..sampling import ParseError

HOST = "www.jjwxc.net"
BASE = f"https://{HOST}"
ENCODING = "gb18030"

# Ranking lists we read: our name for it, and jjwxc's ``orderstr``.
RANK_LISTS = {"monthly": 5, "quarterly": 4, "newcomers": 3}

_FREE_HREF = re.compile(
    r"^(?:https?:)?//www\.jjwxc\.net/onebook\.php\?novelid=(\d+)&chapterid=(\d+)$"
)
_NOVEL_HREF = re.compile(r"onebook\.php\?novelid=(\d+)$")
_MATURE_MARK = "18岁以上"  # 本文作者建议18岁以上读者观看: the author's advice for older readers
_STATUS = {"完结": "completed", "连载": "ongoing", "暂停": "hiatus"}
_HEADER_LINES = (
    re.compile(r"^《.*》$"),  # the book's title
    re.compile(r"^\d{4}[./-]\d{1,2}[./-]\d{1,2}"),  # date/author
    re.compile(r"^第.{1,9}[章回节卷]"),  # the chapter heading
)


def decode(body: bytes | str) -> str:
    """Page text. Sidebars are sometimes cut mid-character, so undecodable bytes are replaced."""
    return body if isinstance(body, str) else body.decode(ENCODING, errors="replace")


def rank_url(orderstr: int) -> str:
    return f"{BASE}/topten.php?orderstr={orderstr}&t=0"


def book_url(novel_id: str | int) -> str:
    return f"{BASE}/onebook.php?novelid={int(novel_id)}"


def free_chapter_url(novel_id: str | int, chapter_id: int) -> str:
    """The URL of a free chapter. The only constructor of chapter URLs."""
    return f"{BASE}/onebook.php?novelid={int(novel_id)}&chapterid={int(chapter_id)}"


def is_free_chapter_url(url: str) -> bool:
    """True for exactly the URLs ``free_chapter_url`` builds (no VIP, login or my.jjwxc.net)."""
    return bool(re.fullmatch(re.escape(BASE) + r"/onebook\.php\?novelid=\d+&chapterid=\d+", url))


def _int(text: str | None) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


# --- rankings -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RankEntry:
    novel_id: str
    rank: int
    title: str
    author: str
    type_line: str
    status: str | None
    words: int | None
    points: int | None


def parse_ranking(body: bytes | str) -> list[RankEntry]:
    """The books of a topten.php page, in rank order."""
    tree = LexborHTMLParser(decode(body))
    entries: dict[str, RankEntry] = {}
    for link in tree.css("a[href^='onebook.php?novelid=']"):
        match = _NOVEL_HREF.search(link.attributes.get("href") or "")
        row = link.parent
        while row is not None and row.tag != "tr":
            row = row.parent
        if not match or row is None or match.group(1) in entries:
            continue
        cells = [c.text(strip=True) for c in row.css("td")]
        if len(cells) < 8 or not cells[0].isdigit():
            continue
        entries[match.group(1)] = RankEntry(
            novel_id=match.group(1),
            rank=int(cells[0]),
            title=link.attributes.get("title") or link.text(strip=True),
            author=cells[1],
            type_line=cells[3],
            status=_STATUS.get(cells[4]),
            words=_int(cells[5]),
            points=_int(cells[6]),
        )
    return sorted(entries.values(), key=lambda e: e.rank)


def merge_rankings(lists: dict[str, list[RankEntry]], limit: int) -> list[str]:
    """Novel ids best first: take the entries of each list in turn, skipping repeats."""
    chosen: list[str] = []
    seen: set[str] = set()
    depth = max((len(entries) for entries in lists.values()), default=0)
    for place in range(depth):
        for entries in lists.values():
            if place < len(entries) and entries[place].novel_id not in seen:
                seen.add(entries[place].novel_id)
                chosen.append(entries[place].novel_id)
                if len(chosen) == limit:
                    return chosen
    return chosen


# --- book pages ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChapterRow:
    number: int
    chapter_id: int
    words: int | None
    free: bool


@dataclass
class BookMeta:
    novel_id: str
    title: str
    author: str
    type_line: str
    genre: str  # era and type from the type line, e.g. 近代现代-爱情
    perspective: str | None
    status: str | None
    length_chars: int | None
    tags: list[str]
    synopsis: str | None
    favourites: int | None
    points: int | None
    last_up: str | None
    is_mature: bool
    chapters: list[ChapterRow] = field(default_factory=list)

    @property
    def url(self) -> str:
        return book_url(self.novel_id)

    @property
    def keywords(self) -> str:
        """Content tags plus the type line and perspective, for matching domain groups."""
        return " ".join([*self.tags, self.type_line, self.perspective or ""]).strip()

    @property
    def free(self) -> list[ChapterRow]:
        return [c for c in self.chapters if c.free]


def _text(tree: LexborHTMLParser, selector: str) -> str | None:
    node = tree.css_first(selector)
    return node.text(strip=True) or None if node else None


def genre_of(type_line: str) -> str:
    """原创-言情-近代现代-爱情 -> 近代现代-爱情 (era and type); other shapes are kept whole."""
    parts = type_line.split("-")
    return "-".join(parts[2:]) if len(parts) >= 4 else type_line


def _chapter_row(row, novel_id: str) -> ChapterRow | None:
    cells = row.css("td")
    if not cells or not cells[0].text(strip=True).isdigit():
        return None
    link = row.css_first("a[itemprop='url']")
    href = (link.attributes.get("href") or "") if link else ""
    match = _FREE_HREF.match(href)
    words = _int(_text_of(row.css_first("td[itemprop='wordCount']")))
    number = int(cells[0].text(strip=True))
    if match and match.group(1) == novel_id and "VIP" not in row.text() and "锁" not in row.text():
        return ChapterRow(number, int(match.group(2)), words, True)
    return ChapterRow(number, number, words, False)


def _text_of(node) -> str | None:
    return node.text(strip=True) if node else None


def parse_book(body: bytes | str, novel_id: str | int) -> BookMeta:
    """Metadata and the chapter list of a book page."""
    novel_id = str(int(novel_id))
    tree = LexborHTMLParser(decode(body))
    title = _text(tree, "h1[itemprop='name'] [itemprop='articleSection']") or _text(
        tree, "h1[itemprop='name']"
    )
    if not title:
        raise ParseError("no book title found; jjwxc may have changed its page layout")
    type_line = _text(tree, "[itemprop='genre']") or ""
    perspective = None
    for item in tree.css("ul.rightul li"):
        if item.text(strip=True).startswith("作品视角"):
            perspective = item.text(strip=True).split("：", 1)[-1].strip() or None
    intro = tree.css_first("#novelintro")
    synopsis = None
    if intro is not None:
        synopsis = re.sub(r"<br\s*/?>", "\n", intro.html or "")
        synopsis = htmllib.unescape(re.sub(r"<[^>]+>", "", synopsis)).strip() or None
    modified = tree.css_first("meta[itemprop='dateModified']")
    mature = any(_MATURE_MARK in node.text() for node in tree.css("div[style*='color:red']"))
    chapters = []
    for row in tree.css("#oneboolt tr[itemprop='chapter']"):
        parsed = _chapter_row(row, novel_id)
        if parsed:
            chapters.append(parsed)
    status_text = _text(tree, "[itemprop='updataStatus']") or ""
    return BookMeta(
        novel_id=novel_id,
        title=title,
        author=_text(tree, "[itemprop='author']") or "",
        type_line=type_line,
        genre=genre_of(type_line),
        perspective=perspective,
        status=_STATUS.get(status_text),
        length_chars=_int(_text(tree, "[itemprop='wordCount']")),
        tags=[a.text(strip=True) for a in tree.css(".smallreadbody a[href*='bookbase.php?bq=']")],
        synopsis=synopsis,
        favourites=_int(_text(tree, "[itemprop='collectedCount']")),
        points=_int(_text(tree, "[itemprop='scoreCount']")),
        last_up=(modified.attributes.get("content") or None) if modified else None,
        is_mature=mature,
        chapters=chapters,
    )


# --- chapters ----------------------------------------------------------------------------


def parse_chapter(body: bytes | str) -> str:
    """The text of a free chapter, one paragraph per line, without the title lines."""
    tree = LexborHTMLParser(decode(body))
    node = tree.css_first("#paragraph_comment_content")
    if node is None:
        raise ParseError("no chapter body found; the chapter may be locked or the layout changed")
    raw = re.sub(r"<br\s*/?>", "\n", node.html or "")
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", raw))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    while lines and any(p.match(lines[0]) for p in _HEADER_LINES) and len(lines) > 1:
        lines.pop(0)
    text = "\n".join(lines)
    if not text:
        raise ParseError("the chapter body is empty")
    if "�" in text:
        raise ParseError("the chapter text is garbled; it was not decoded as GBK")
    return text
