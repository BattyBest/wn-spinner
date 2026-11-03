"""Japanese text analysis with SudachiPy.

Text is normalised (NFKC), tokenised in Sudachi's middle split mode and reduced to
lemmas using the normalised form, so 食べた and たべた both count as 食べる. Proper nouns
are marked as names so they stay out of coverage.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from sudachipy import Dictionary, SplitMode

ANALYSER_VERSION = 1
MAX_CHUNK = 10_000  # characters per tokenizer call; Sudachi rejects very long inputs

NAME_POS = "固有名詞"
_SKIP_POS = {"補助記号", "記号", "空白"}
_FUNCTION_POS = {"助詞", "助動詞"}
_KANJI = re.compile(r"[㐀-䶿一-鿿々〆]")
_WORDY = re.compile(r"\w")
_SENTENCE_END = re.compile(r"[。！？!?]+[」』）)]*|\n")
_OPEN, _CLOSE = "「『", "」』"


@dataclass(frozen=True)
class Word:
    lemma: str
    pos: str  # first Sudachi POS level, or 固有名詞 for proper nouns
    reading: str | None  # hiragana, of the lemma in dictionary form when it can be found
    oov: bool

    @property
    def is_name(self) -> bool:
        return self.pos == NAME_POS

    @property
    def is_function(self) -> bool:
        return self.pos in _FUNCTION_POS


@dataclass
class TextAnalysis:
    counts: Counter[Word] = field(default_factory=Counter)
    chars: int = 0  # characters excluding whitespace
    sentences: int = 0
    kanji_chars: int = 0
    dialogue_chars: int = 0

    def merge(self, other: TextAnalysis) -> None:
        self.counts.update(other.counts)
        self.chars += other.chars
        self.sentences += other.sentences
        self.kanji_chars += other.kanji_chars
        self.dialogue_chars += other.dialogue_chars


@lru_cache(maxsize=1)
def _tokenizer():
    return Dictionary(dict="core").tokenizer(SplitMode.B)


@lru_cache(maxsize=50_000)
def _lemma_reading(lemma: str) -> str | None:
    """Reading of a lemma in dictionary form, found by tokenising the lemma on its own."""
    parts = _tokenizer().tokenize(lemma)
    if len(parts) != 1:
        return None
    return katakana_to_hiragana(parts[0].reading_form()) or None


def katakana_to_hiragana(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _chunks(text: str):
    for line in text.split("\n"):
        while len(line) > MAX_CHUNK:
            cut = line.rfind("。", 0, MAX_CHUNK) + 1 or MAX_CHUNK
            yield line[:cut]
            line = line[cut:]
        if line:
            yield line


def dialogue_chars(text: str) -> int:
    """Characters (not counting whitespace) inside 「」 or 『』."""
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
    squashed = re.sub(r"\s", "", text)
    result.chars = len(squashed)
    result.kanji_chars = len(_KANJI.findall(squashed))
    result.dialogue_chars = dialogue_chars(text)
    result.sentences = sum(1 for s in _SENTENCE_END.split(text) if s.strip())

    for _surface, word in iter_tokens(text):
        if word is not None:
            result.counts[word] += 1
    return result


def _word_of(morpheme) -> Word | None:
    """The countable word for a morpheme, or None for punctuation, numbers and symbols."""
    pos = morpheme.part_of_speech()
    if pos[0] in _SKIP_POS or pos[1] == "数詞":
        return None
    lemma = morpheme.normalized_form()
    if not _WORDY.search(lemma):
        return None
    if morpheme.surface() in (morpheme.dictionary_form(), lemma):
        reading = katakana_to_hiragana(morpheme.reading_form()) or None
    else:
        reading = _lemma_reading(lemma)
    kind = NAME_POS if pos[1] == NAME_POS else pos[0]
    return Word(lemma, kind, reading, morpheme.is_oov())


def iter_tokens(text: str):
    """Yield ``(surface, word)`` in reading order; ``word`` is None where nothing is counted.

    The text is normalised first, so surfaces are NFKC forms. This is the one place that
    decides what a word is, so analysis, excerpts and the test all agree.
    """
    tokenizer = _tokenizer()
    for chunk in _chunks(normalise(text)):
        for morpheme in tokenizer.tokenize(chunk):
            yield morpheme.surface(), _word_of(morpheme)
        yield "\n", None
