"""Clients for Syosetu's official Ranking API and Novel API.

Both return JSON. Metadata only ever comes from here; HTML is fetched for chapter text
alone. Adult works live on separate domains with their own APIs and are never requested.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import urlencode

API_HOST = "api.syosetu.com"
RANK_URL = f"https://{API_HOST}/rank/rankget/"
NOVEL_URL = f"https://{API_HOST}/novelapi/api/"
NOVEL_BATCH = 100

# Ranking lists: API suffix, and how many entries each returns.
RANK_LISTS = {"daily": "d", "weekly": "w", "monthly": "m", "quarterly": "q"}


class ApiError(Exception):
    pass


def normalise_ncode(ncode: str) -> str:
    return ncode.strip().lower()


# --- ranking -----------------------------------------------------------------------


def rank_dates(kind: str, today: date, *, tries: int = 2) -> list[date]:
    """Candidate dates for a ranking list, newest first.

    Syosetu publishes daily lists for any day, weekly lists only for Tuesdays, monthly
    lists for the 1st and quarterly lists for the 1st of Jan, Apr, Jul and Oct. A list is
    published a little after its period ends, so the newest candidate may still be empty
    and the caller falls back to the next one.
    """
    if kind == "daily":
        return [today - timedelta(days=1 + i) for i in range(tries)]
    if kind == "weekly":
        last = today - timedelta(days=1)
        last -= timedelta(days=(last.weekday() - 1) % 7)  # back to a Tuesday
        return [last - timedelta(weeks=i) for i in range(tries)]
    if kind == "monthly":
        first = today.replace(day=1)
        return [_months_back(first, i) for i in range(tries)]
    if kind == "quarterly":
        first = today.replace(day=1, month=1 + 3 * ((today.month - 1) // 3))
        return [_months_back(first, 3 * i) for i in range(tries)]
    raise ValueError(f"unknown ranking list: {kind}")


def _months_back(first: date, months: int) -> date:
    index = first.year * 12 + first.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def rank_url(kind: str, when: date) -> str:
    return RANK_URL + "?" + urlencode({"out": "json", "rtype": f"{when:%Y%m%d}-{RANK_LISTS[kind]}"})


@dataclass(frozen=True)
class RankEntry:
    ncode: str
    rank: int
    points: int


def parse_ranking(body: bytes) -> list[RankEntry]:
    """Entries of one ranking list, best first. An empty list means "not published yet"."""
    data = _json(body)
    if not isinstance(data, list):
        raise ApiError("ranking response is not a list")
    entries = []
    for item in data:
        if not isinstance(item, dict) or "ncode" not in item:
            continue
        entries.append(
            RankEntry(
                normalise_ncode(item["ncode"]), int(item.get("rank", 0)), int(item.get("pt", 0))
            )
        )
    entries.sort(key=lambda e: e.rank)
    return entries


def merge_rankings(lists: dict[str, list[RankEntry]], limit: int) -> list[str]:
    """Pick the ``limit`` best ncodes across lists: best single position, then most lists."""
    best: dict[str, tuple[int, int]] = {}
    for entries in lists.values():
        for entry in entries:
            top, seen = best.get(entry.ncode, (entry.rank, 0))
            best[entry.ncode] = (min(top, entry.rank), seen + 1)
    order = sorted(best, key=lambda n: (best[n][0], -best[n][1], n))
    return order[:limit]


# --- novel metadata ----------------------------------------------------------------


def novel_url(ncodes: list[str]) -> str:
    if not 0 < len(ncodes) <= NOVEL_BATCH:
        raise ValueError(f"ask for 1 to {NOVEL_BATCH} ncodes at a time")
    query = {"out": "json", "lim": len(ncodes), "ncode": "-".join(sorted(ncodes))}
    return NOVEL_URL + "?" + urlencode(query, safe="-")


@dataclass
class NovelMeta:
    ncode: str
    title: str
    author: str | None = None
    synopsis: str | None = None
    keywords: str | None = None
    genre: str | None = None
    kind: str = "serial"  # serial or short
    status: str | None = None  # ongoing, completed or hiatus
    chapter_count: int | None = None
    length_chars: int | None = None
    is_r15: bool = False
    points: int | None = None
    bookmarks: int | None = None
    site_dialogue_pct: int | None = None
    first_up: str | None = None
    last_up: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def url(self) -> str:
        return f"https://ncode.syosetu.com/{self.ncode}/"


# The API's own genre numbers, kept so a genre is never blank if the site adds one.
GENRES = {
    101: "異世界〔恋愛〕",
    102: "現実世界〔恋愛〕",
    201: "ハイファンタジー〔ファンタジー〕",
    202: "ローファンタジー〔ファンタジー〕",
    301: "純文学〔文芸〕",
    302: "ヒューマンドラマ〔文芸〕",
    303: "歴史〔文芸〕",
    304: "推理〔文芸〕",
    305: "ホラー〔文芸〕",
    306: "アクション〔文芸〕",
    307: "コメディー〔文芸〕",
    401: "VRゲーム〔SF〕",
    402: "宇宙〔SF〕",
    403: "空想科学〔SF〕",
    404: "パニック〔SF〕",
    9901: "童話〔その他〕",
    9902: "詩〔その他〕",
    9903: "エッセイ〔その他〕",
    9904: "リプレイ〔その他〕",
    9999: "その他〔その他〕",
    9801: "ノンジャンル〔ノンジャンル〕",
}


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_novels(body: bytes) -> list[NovelMeta]:
    """Parse a Novel API response: ``[{"allcount": N}, {novel}, ...]``."""
    data = _json(body)
    if not isinstance(data, list):
        raise ApiError("novel response is not a list")
    novels = []
    for item in data:
        if not isinstance(item, dict) or "ncode" not in item:
            continue  # the leading {"allcount": N} record
        kind = "short" if _int(item.get("novel_type")) == 2 else "serial"
        if _int(item.get("isstop")) == 1:
            status = "hiatus"
        elif kind == "short" or _int(item.get("end")) == 0:
            status = "completed"
        else:
            status = "ongoing"
        chapters = _int(item.get("general_all_no"))
        novels.append(
            NovelMeta(
                ncode=normalise_ncode(item["ncode"]),
                title=str(item.get("title") or item["ncode"]),
                author=item.get("writer"),
                synopsis=item.get("story"),
                keywords=item.get("keyword"),
                genre=GENRES.get(_int(item.get("genre")) or 0) or None,
                kind=kind,
                status=status,
                chapter_count=1 if kind == "short" else chapters,
                length_chars=_int(item.get("length")),
                is_r15=_int(item.get("isr15")) == 1,
                points=_int(item.get("global_point")),
                bookmarks=_int(item.get("fav_novel_cnt")),
                site_dialogue_pct=_int(item.get("kaiwaritu")),
                first_up=item.get("general_firstup"),
                last_up=item.get("general_lastup"),
                raw=item,
            )
        )
    return novels


def _json(body: bytes):
    try:
        return json.loads(body)
    except ValueError as exc:
        raise ApiError(f"response is not JSON: {exc}") from exc
