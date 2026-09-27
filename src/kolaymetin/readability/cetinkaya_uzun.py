"""Çetinkaya-Uzun (2010) okunabilirlik formülü.

Çetinkaya, G. (2010). Türkçe metinlerin okunabilirlik düzeylerinin tanımlanması ve
sınıflandırılması (Doktora tezi). Çukurova Üniversitesi.

    ÇOİ = 118,823 − 25,987 × (hece / kelime) − 0,971 × (kelime / cümle)

Düzeyler: 0–34 engellenmiş okuma (10–12. sınıf), 35–50 eğitsel okuma (8–9. sınıf),
51 ve üstü bağımsız okuma (5–7. sınıf).
"""

from __future__ import annotations

from kolaymetin.models import ReadabilityScore
from kolaymetin.readability.base import TextCounts

A, B, C = 118.823, 25.987, 0.971


def formula(syllables_per_word: float, words_per_sentence: float) -> float:
    return A - B * syllables_per_word - C * words_per_sentence


def level(value: float) -> tuple[str, str]:
    if value >= 51:
        return "bağımsız okuma düzeyi", "5, 6 ve 7. sınıf"
    if value >= 35:
        return "eğitsel okuma düzeyi", "8 ve 9. sınıf"
    return "engellenmiş okuma düzeyi (zor)", "10, 11 ve 12. sınıf"


def score(tc: TextCounts) -> ReadabilityScore:
    if not tc.words or not tc.sentences:
        return ReadabilityScore(
            name="Çetinkaya-Uzun", value=None, level="hesaplanamadı",
            description="Metinde sayılacak kelime yok.",
        )
    value = formula(tc.syllables_per_word, tc.words_per_sentence)
    name, grade = level(value)
    return ReadabilityScore(
        name="Çetinkaya-Uzun",
        value=round(value, 1),
        level=name,
        grade=grade,
        description="Yüksek puan daha kolay metin demektir; 51 ve üstü bağımsız okumaya uygundur.",
    )
