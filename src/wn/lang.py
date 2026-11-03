"""What differs between the languages wn-spinner handles: Japanese ('ja') and Chinese ('zh').

Everything else (the learner model, coverage, the placement flow, the screens) is the same
for both and takes a language code. This module is the one place that knows the differences:
which analyser to use, what counts as a content word or a name, which level list applies
and which site the novels come from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name: str  # in English
    html_lang: str  # the lang="" attribute for text in this language
    source: str  # the name of its source in catalog.db
    hosts: tuple[str, ...]  # hosts the collector talks to for this language
    dictionary: str  # name of the dictionary in dict_meta
    level_name: str  # JLPT or HSK
    levels: tuple[int, ...]  # easiest first
    content_pos: tuple[str, ...]  # parts of speech the placement test may ask about
    name_pos: str  # the part of speech given to proper nouns
    name_like: re.Pattern  # an unknown word of this shape, seen often in one novel, is a name


JA = Language(
    code="ja",
    name="Japanese",
    html_lang="ja",
    source="syosetu",
    hosts=("api.syosetu.com", "ncode.syosetu.com", "yomou.syosetu.com"),
    dictionary="jmdict",
    level_name="JLPT",
    levels=(5, 4, 3, 2, 1),
    content_pos=("名詞", "動詞", "形容詞", "形状詞", "副詞"),
    name_pos="固有名詞",
    name_like=re.compile(r"^[ァ-ヶー]+$"),
)

ZH = Language(
    code="zh",
    name="Chinese",
    html_lang="zh-Hans",
    source="jjwxc",
    hosts=("www.jjwxc.net",),
    dictionary="cedict",
    level_name="HSK",
    levels=(1, 2, 3, 4, 5, 6, 7),  # 7 stands for HSK 7-9
    content_pos=("n", "v", "a", "d", "i", "l"),
    name_pos="name",
    name_like=re.compile(r"^[㐀-䶿一-鿿]+$"),
)

LANGUAGES: dict[str, Language] = {JA.code: JA, ZH.code: ZH}
CODES = tuple(LANGUAGES)


def get(code: str) -> Language:
    try:
        return LANGUAGES[code]
    except KeyError:
        raise ValueError(f"unknown language {code!r}") from None


def iter_tokens(code: str, text: str):
    """``(surface, word or None)`` in reading order, from the language's own analyser."""
    if code == "zh":
        from .analysis import chinese

        return chinese.iter_tokens(text)
    from .analysis import japanese

    return japanese.iter_tokens(text)


def analyse_text(code: str, text: str):
    if code == "zh":
        from .analysis import chinese

        return chinese.analyse_text(text)
    from .analysis import japanese

    return japanese.analyse_text(text)


def normalise(code: str, text: str) -> str:
    from .analysis import japanese

    return japanese.normalise(text)  # NFKC for both


def sentence_pattern(code: str) -> re.Pattern:
    """Splits a passage into sentences, keeping closing quotes with their sentence."""
    if code == "zh":
        return re.compile(r"[^。！？!?…\n]*(?:[。！？!?]+|…+)[”’」』）)]*|[^。！？!?…\n]+")
    return re.compile(r"[^。！？!?\n]*[。！？!?]+[」』）)]*|[^。！？!?\n]+")


def has_script(code: str, text: str) -> bool:
    """True when the text has the language's main script (kanji, or hanzi)."""
    return bool(re.search(r"[㐀-䶿一-鿿々〆]", text))
