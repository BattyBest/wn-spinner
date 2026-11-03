"""Vocabulary domains and which words belong to them.

A word gets domain weights from two sources, both rebuilt by ``wn analyse --domains``:

* dictionary: JMdict field and usage tags map to a domain with weight 1;
* learned: words much more common in the novels of one genre or keyword group than in the
  rest of the catalog join that domain, with a weight that grows with the evidence but
  never reaches a dictionary tag's.

Corrections the learner makes are kept in profile.db (``domain_fix``) and applied on top
when the model reads weights, so they survive a rebuild.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from ..analysis.store import is_name

DOMAIN_KEYS = (
    "fantasy",
    "games",
    "court",
    "combat",
    "romance",
    "school",
    "speech",
    "crime",
    "medicine",
    "science",
    "money",
    "formal",
)

# JMdict tag -> domains. Field tags (chem, med, ...) and usage tags (col, hon, ...).
TAG_DOMAINS: dict[str, tuple[str, ...]] = {
    "myth": ("fantasy",),
    "Buddh": ("fantasy",),
    "Shinto": ("fantasy",),
    "Christn": ("fantasy",),
    "mil": ("combat",),
    "MA": ("combat",),
    "law": ("crime",),
    "med": ("medicine",),
    "anat": ("medicine",),
    "physiol": ("medicine",),
    "chem": ("science",),
    "physics": ("science",),
    "math": ("science",),
    "comp": ("science",),
    "biol": ("science",),
    "astron": ("science",),
    "geol": ("science",),
    "engr": ("science",),
    "elec": ("science",),
    "geom": ("science",),
    "stat": ("science",),
    "finc": ("money",),
    "econ": ("money",),
    "bus": ("money",),
    "col": ("speech",),
    "sl": ("speech",),
    "fam": ("speech",),
    "vulg": ("speech",),
    "hon": ("formal",),
    "hum": ("formal",),
    "pol": ("formal",),
    "arch": ("formal",),
    "form": ("formal",),
}


@dataclass(frozen=True)
class Group:
    """Which novels stand for a domain: by Syosetu genre, or a keyword in the novel's tags."""

    genres: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


# Genre names are the ones stored in novel.genre (see syosetu/api.py).
GROUPS_JA: dict[str, Group] = {
    "fantasy": Group(
        ("ハイファンタジー〔ファンタジー〕", "ローファンタジー〔ファンタジー〕"),
        ("魔法", "魔王", "異世界", "剣と魔法", "魔物", "エルフ"),
    ),
    "games": Group(("VRゲーム〔SF〕",), ("ゲーム", "ステータス", "チート", "スキル", "レベル")),
    "court": Group(("異世界〔恋愛〕",), ("悪役令嬢", "貴族", "王族", "婚約破棄", "内政", "王子")),
    "combat": Group(("アクション〔文芸〕",), ("戦闘", "戦争", "戦記", "騎士", "バトル")),
    "romance": Group(("異世界〔恋愛〕", "現実世界〔恋愛〕"), ("恋愛", "ラブコメ", "溺愛")),
    "school": Group((), ("学園", "学校", "青春", "部活", "高校")),
    "speech": Group(
        ("現実世界〔恋愛〕", "コメディー〔文芸〕", "ヒューマンドラマ〔文芸〕"), ("日常", "コメディ")
    ),
    "crime": Group(("推理〔文芸〕",), ("推理", "ミステリー", "警察", "事件", "探偵")),
    "medicine": Group((), ("医者", "医療", "病院", "薬師", "ポーション")),
    "science": Group(
        ("宇宙〔SF〕", "空想科学〔SF〕", "パニック〔SF〕"), ("SF", "科学", "研究", "錬金術")
    ),
    "money": Group((), ("商人", "経営", "経済", "商会", "領地経営", "金融")),
    "formal": Group(("歴史〔文芸〕",), ("時代小説", "戦国", "江戸", "武士")),
}

# jjwxc has no genre list of its own: ``genre`` holds the era and type from the type line
# (such as 古色古香-爱情) and ``keywords`` holds the content tags and the type line, so words
# match as substrings. These groups are a first guess, to be tuned against real catalogs.
GROUPS_ZH: dict[str, Group] = {
    "fantasy": Group((), ("仙侠", "修真", "玄幻", "奇幻", "魔法", "神话", "灵异神怪", "神仙")),
    "games": Group((), ("游戏", "网游", "系统", "无限流", "电竞", "副本")),
    "court": Group((), ("宫廷", "侯爵", "宫斗", "宅斗", "权谋", "朝堂", "世家", "架空历史")),
    "combat": Group((), ("武侠", "江湖", "战争", "军旅", "格斗", "热血")),
    "romance": Group((), ("爱情", "甜文", "虐恋", "破镜重圆", "青梅竹马", "天作之合")),
    "school": Group((), ("校园", "青春", "学生", "高中", "大学")),
    "speech": Group((), ("轻松", "日常", "沙雕", "欢喜冤家", "娱乐圈", "都市")),
    "crime": Group((), ("悬疑", "推理", "刑侦", "探案", "犯罪", "律师", "法医")),
    "medicine": Group((), ("医生", "医术", "医疗", "医学")),
    "science": Group((), ("科幻", "星际", "科技", "机甲", "末世")),
    "money": Group((), ("商战", "职场", "商业", "经商", "种田", "创业", "金融")),
    "formal": Group((), ("历史", "古色古香", "民国", "古代")),
}
GROUPS: dict[str, dict[str, Group]] = {"ja": GROUPS_JA, "zh": GROUPS_ZH}

MIN_GROUP_NOVELS = 3
MIN_NOVELS_WITH_WORD = 3
MIN_Z = 3.0
LEARNED_BASE = 0.3
LEARNED_STEP = 0.1
LEARNED_MAX = 0.8
PRIOR_STRENGTH = 500.0  # the informative prior's total pseudo-count (Monroe et al. 2008)


@dataclass
class DomainReport:
    dictionary: int = 0
    learned: int = 0
    groups: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


def tag_domains(tags: str | None) -> set[str]:
    out: set[str] = set()
    for tag in (tags or "").split():
        out.update(TAG_DOMAINS.get(tag, ()))
    return out


def novel_in_group(group: Group, genre: str | None, keywords: str | None) -> bool:
    if genre and genre in group.genres:
        return True
    words = keywords or ""
    return any(k in words for k in group.keywords)


def _z_score(y_g: int, n_g: int, y_r: int, n_r: int, prior: float) -> float:
    """Log-odds ratio with an informative Dirichlet prior, as a z-score (Monroe et al.)."""
    a = max(prior * PRIOR_STRENGTH, 1e-6)
    a0 = PRIOR_STRENGTH
    if n_g + a0 - y_g - a <= 0 or n_r + a0 - y_r - a <= 0:
        return 0.0
    delta = math.log((y_g + a) / (n_g + a0 - y_g - a)) - math.log((y_r + a) / (n_r + a0 - y_r - a))
    variance = 1 / (y_g + a) + 1 / (y_r + a)
    return delta / math.sqrt(variance)


def rebuild_domains(conn: sqlite3.Connection, lang: str = "ja") -> DomainReport:
    """Recompute one language's word domain weights from dictionary tags and the catalog."""
    report = DomainReport()
    rows: dict[tuple[int, str], tuple[float, str]] = {}

    for row in conn.execute(
        "SELECT id, tags FROM lemma WHERE tags IS NOT NULL AND tags != '' AND language = ?",
        (lang,),
    ):
        for domain in tag_domains(row["tags"]):
            rows[(row["id"], domain)] = (1.0, "dictionary")
    report.dictionary = len(rows)

    novels = conn.execute(
        "SELECT n.id, n.genre, n.keywords FROM novel n"
        " JOIN source s ON s.id = n.source_id"
        " WHERE s.language = ? AND n.id IN (SELECT novel_id FROM novel_stats)",
        (lang,),
    ).fetchall()
    usable = {r["id"] for r in novels}
    per_novel: dict[int, dict[int, int]] = defaultdict(dict)
    for row in conn.execute(
        "SELECT nl.novel_id, nl.lemma_id, nl.count, nl.is_name, l.lemma, l.oov, l.is_function"
        " FROM novel_lemma nl JOIN lemma l ON l.id = nl.lemma_id WHERE l.language = ?",
        (lang,),
    ):
        if row["novel_id"] in usable and not row["is_function"] and not is_name(row, lang):
            per_novel[row["novel_id"]][row["lemma_id"]] = row["count"]
    totals = {nid: sum(c.values()) for nid, c in per_novel.items()}
    overall: dict[int, int] = defaultdict(int)
    for counts in per_novel.values():
        for lemma_id, n in counts.items():
            overall[lemma_id] += n
    grand = sum(overall.values()) or 1

    for key, group in GROUPS[lang].items():
        members = {r["id"] for r in novels if novel_in_group(group, r["genre"], r["keywords"])}
        members &= per_novel.keys()
        rest = per_novel.keys() - members
        report.groups[key] = len(members)
        if len(members) < MIN_GROUP_NOVELS or len(rest) < MIN_GROUP_NOVELS:
            report.skipped.append(key)
            continue
        y_g: dict[int, int] = defaultdict(int)
        docs: dict[int, int] = defaultdict(int)
        for nid in members:
            for lemma_id, n in per_novel[nid].items():
                y_g[lemma_id] += n
                docs[lemma_id] += 1
        n_g = sum(totals[nid] for nid in members)
        n_r = sum(totals[nid] for nid in rest)
        for lemma_id, count_g in y_g.items():
            if docs[lemma_id] < MIN_NOVELS_WITH_WORD or (lemma_id, key) in rows:
                continue
            count_r = overall[lemma_id] - count_g
            if count_g / n_g <= count_r / max(n_r, 1):
                continue
            z = _z_score(count_g, n_g, count_r, n_r, overall[lemma_id] / grand)
            if z >= MIN_Z:
                weight = min(LEARNED_MAX, LEARNED_BASE + LEARNED_STEP * (z - MIN_Z))
                rows[(lemma_id, key)] = (round(weight, 3), "learned")
                report.learned += 1

    with conn:
        conn.execute(
            "DELETE FROM lemma_domain WHERE lemma_id IN (SELECT id FROM lemma WHERE language = ?)",
            (lang,),
        )
        conn.executemany(
            "INSERT INTO lemma_domain (lemma_id, domain, weight, source) VALUES (?, ?, ?, ?)",
            [(lid, d, w, s) for (lid, d), (w, s) in rows.items()],
        )
    return report


def domain_names(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute("SELECT key, name_en, name_ja, name_zh FROM domain ORDER BY position")
    ]
