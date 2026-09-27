"""Okunabilirlik formülleri için ortak sayımlar."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from kolaymetin.models import Sentence

# Formüllerde sayılan sözcük birimleri. URL ve e-posta adresleri sayılmaz (bkz. KARARLAR.md).
COUNTED_KINDS = frozenset({"word", "number", "date", "time", "percent"})


@dataclass
class TextCounts:
    words: int = 0
    sentences: int = 0
    syllables: int = 0
    by_syllables: dict[int, int] = field(default_factory=dict)

    @property
    def words_per_sentence(self) -> float:
        return self.words / self.sentences if self.sentences else 0.0

    @property
    def syllables_per_word(self) -> float:
        return self.syllables / self.words if self.words else 0.0

    def with_syllables(self, n: int, or_more: bool = False) -> int:
        if or_more:
            return sum(c for k, c in self.by_syllables.items() if k >= n)
        return self.by_syllables.get(n, 0)


def count(sentences: Iterable[Sentence]) -> TextCounts:
    """Başlıklar hariç cümlelerden sayım yapar."""
    tc = TextCounts()
    for s in sentences:
        if s.is_heading:
            continue
        words = [t for t in s.tokens if t.kind in COUNTED_KINDS]
        if not words:
            continue
        tc.sentences += 1
        for t in words:
            syl = max(1, t.syllables)
            tc.words += 1
            tc.syllables += syl
            tc.by_syllables[syl] = tc.by_syllables.get(syl, 0) + 1
    return tc
