"""Ateşman (1997) okunabilirlik formülü.

Ateşman, E. (1997). Türkçede okunabilirliğin ölçülmesi. Dil Dergisi, 58, 71–74.
Flesch Okuma Kolaylığı formülünün Türkçeye uyarlamasıdır.

    OS = 198,825 − 40,175 × (hece / kelime) − 2,610 × (kelime / cümle)
"""

from __future__ import annotations

from kolaymetin.models import ReadabilityScore
from kolaymetin.readability.base import TextCounts

A, B, C = 198.825, 40.175, 2.610

LEVELS = [
    (90.0, "çok kolay"),
    (70.0, "kolay"),
    (50.0, "orta güçlükte"),
    (30.0, "zor"),
    (float("-inf"), "çok zor"),
]


def formula(syllables_per_word: float, words_per_sentence: float) -> float:
    return A - B * syllables_per_word - C * words_per_sentence


def level(value: float) -> str:
    for threshold, name in LEVELS:
        if value >= threshold:
            return name
    return LEVELS[-1][1]  # pragma: no cover


def score(tc: TextCounts) -> ReadabilityScore:
    if not tc.words or not tc.sentences:
        return ReadabilityScore(
            name="Ateşman", value=None, level="hesaplanamadı",
            description="Metinde sayılacak kelime yok.",
        )
    value = formula(tc.syllables_per_word, tc.words_per_sentence)
    return ReadabilityScore(
        name="Ateşman",
        value=round(value, 1),
        level=level(value),
        description=(
            "Yüksek puan daha kolay metin demektir. Puan çoğu metinde 0 ile 100 arasındadır. "
            "Çok uzun kelime ve cümlede puan 0'ın altına iner."
        ),
    )
