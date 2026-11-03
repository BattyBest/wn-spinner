"""Chinese text analysis with jieba (Simplified Chinese).

Text is normalised (NFKC) and segmented with jieba's part-of-speech tagger. Words are kept
as they are written (Chinese has no inflection), part-of-speech tags are reduced to one
letter (n, v, a, d, i for idioms, ...), and proper nouns (jieba's nr, ns, nt, nz) become
``name`` so they stay out of coverage. Pinyin is not computed here: it comes from CC-CEDICT
when the dictionary is loaded.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import warnings
from dataclasses import dataclass
from functools import lru_cache

from .japanese import TextAnalysis

ANALYSER_VERSION = 1
NAME_POS = "name"
IDIOM_POS = "i"

_NAME_FLAGS = {"nr", "ns", "nt", "nz"}
_FUNCTION_POS = {"u", "p", "c", "y", "e", "o", "h", "k"}  # particles, prepositions, conjunctions...
_SKIP_FLAGS = {"x", "w", "eng", "m", "mq", "un"}  # punctuation, numbers, foreign text
_HANZI = re.compile(r"[㐀-䶿一-鿿]")
_SENTENCE_END = re.compile(r"[。！？!?…]+[”’」』）)]*|\n")
_OPEN, _CLOSE = "“「『", "”」』"


@dataclass(frozen=True)
class Word:
    lemma: str
    pos: str  # one letter, or ``name``
    reading: str | None  # always None here; pinyin is added from CC-CEDICT
    oov: bool  # not in jieba's dictionary: found by its statistical model

    @property
    def is_name(self) -> bool:
        return self.pos == NAME_POS

    @property
    def is_function(self) -> bool:
        return self.pos in _FUNCTION_POS


@lru_cache(maxsize=1)
def _jieba():
    """Load jieba once, quietly (it logs to stderr and its regexes warn on newer Pythons)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        import jieba
        import jieba.posseg as posseg
    jieba.setLogLevel(logging.WARNING)
    jieba.dt.initialize()
    return jieba, posseg


def coarse(flag: str) -> str:
    """jieba's tag reduced to the one letter this app keeps."""
    if flag in _NAME_FLAGS:
        return NAME_POS
    return flag[:1]


def normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _word_of(surface: str, flag: str) -> Word | None:
    if flag in _SKIP_FLAGS or not _HANZI.search(surface):
        return None
    jieba, _ = _jieba()
    oov = jieba.dt.FREQ.get(surface, 0) == 0
    return Word(surface, coarse(flag), None, oov)


def iter_tokens(text: str):
    """Yield ``(surface, word)`` in reading order; ``word`` is None where nothing is counted.

    This is the one place that decides what a word is, so analysis, excerpts and the test
    all agree.
    """
    _, posseg = _jieba()
    for line in normalise(text).split("\n"):
        for pair in posseg.cut(line):
            yield pair.word, _word_of(pair.word, pair.flag)
        yield "\n", None


def dialogue_chars(text: str) -> int:
    """Characters (not counting whitespace) inside “” or 「」."""
    depth = inside = 0
    for ch in text:
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        elif depth and not ch.isspace():
            inside += 1
    return inside


def analyse_text(text: str) -> TextAnalysis:
    text = normalise(text)
    result = TextAnalysis()
    result.chars = len(re.sub(r"\s", "", text))
    result.dialogue_chars = dialogue_chars(text)
    result.sentences = sum(1 for s in _SENTENCE_END.split(text) if s.strip())
    for _surface, word in iter_tokens(text):
        if word is not None:
            result.counts[word] += 1
    return result
