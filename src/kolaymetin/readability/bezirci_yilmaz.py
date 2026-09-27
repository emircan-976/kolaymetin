"""Bezirci-Yılmaz (2010) okunabilirlik formülü (YOD).

Bezirci, B. ve Yılmaz, A. E. (2010). Metinlerin okunabilirliğinin ölçülmesi üzerine bir
yazılım kütüphanesi ve Türkçe için yeni bir okunabilirlik ölçütü. Dokuz Eylül Üniversitesi
Mühendislik Fakültesi Fen ve Mühendislik Dergisi, 12(3), 49–62.

    YOD = √( OKS × (H3 × 0,84 + H4 × 1,5 + H5 × 3,5 + H6 × 26,25) )

OKS: cümle başına ortalama kelime sayısı. H3…H6: cümle başına ortalama 3, 4, 5 ve 6+ heceli
kelime sayısı. Sonuç yaklaşık eğitim yılıdır: 1–8 ilköğretim, 9–12 lise, 12–16 lisans,
16 ve üstü akademik düzey.
"""

from __future__ import annotations

import math

from kolaymetin.models import ReadabilityScore
from kolaymetin.readability.base import TextCounts

W3, W4, W5, W6 = 0.84, 1.5, 3.5, 26.25


def formula(oks: float, h3: float, h4: float, h5: float, h6: float) -> float:
    return math.sqrt(oks * (h3 * W3 + h4 * W4 + h5 * W5 + h6 * W6))


def level(value: float) -> str:
    if value <= 8:
        return "ilköğretim düzeyi"
    if value <= 12:
        return "lise düzeyi"
    if value <= 16:
        return "lisans düzeyi"
    return "akademik düzey"


def score(tc: TextCounts) -> ReadabilityScore:
    if not tc.words or not tc.sentences:
        return ReadabilityScore(
            name="Bezirci-Yılmaz", value=None, level="hesaplanamadı",
            description="Metinde sayılacak kelime yok.",
        )
    n = tc.sentences
    value = formula(
        tc.words_per_sentence,
        tc.with_syllables(3) / n,
        tc.with_syllables(4) / n,
        tc.with_syllables(5) / n,
        tc.with_syllables(6, or_more=True) / n,
    )
    years = max(1, round(value))
    return ReadabilityScore(
        name="Bezirci-Yılmaz",
        value=round(value, 1),
        level=level(value),
        grade=f"yaklaşık {years}. eğitim yılı",
        description="Düşük değer daha kolay metin demektir; yaklaşık eğitim yılını gösterir.",
    )
