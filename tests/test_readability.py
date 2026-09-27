"""Okunabilirlik formülleri: elle hesaplanmış değerlerle."""

from __future__ import annotations

import math

import pytest

from kolaymetin import analyze
from kolaymetin.readability import atesman, bezirci_yilmaz, cetinkaya_uzun, compliance
from kolaymetin.readability.base import TextCounts


def test_atesman_formula_by_hand() -> None:
    # 2,5 hece/kelime, 10 kelime/cümle → 198,825 − 100,4375 − 26,1 = 72,2875
    assert atesman.formula(2.5, 10) == pytest.approx(72.2875)
    assert atesman.level(95) == "çok kolay"
    assert atesman.level(70) == "kolay"
    assert atesman.level(50) == "orta güçlükte"
    assert atesman.level(30) == "zor"
    assert atesman.level(5) == "çok zor"
    assert atesman.level(-20) == "çok zor"


def test_cetinkaya_formula_by_hand() -> None:
    # 118,823 − 25,987 × 2,5 − 0,971 × 10 = 118,823 − 64,9675 − 9,71 = 44,1455
    assert cetinkaya_uzun.formula(2.5, 10) == pytest.approx(44.1455)
    assert cetinkaya_uzun.level(60)[0] == "bağımsız okuma düzeyi"
    assert cetinkaya_uzun.level(40)[1] == "8 ve 9. sınıf"
    assert cetinkaya_uzun.level(10)[1] == "10, 11 ve 12. sınıf"


def test_bezirci_formula_by_hand() -> None:
    # OKS=10, H3=2, H4=1, H5=0,5, H6=0,1 → √(10 × (1,68 + 1,5 + 1,75 + 2,625)) = √75,55
    assert bezirci_yilmaz.formula(10, 2, 1, 0.5, 0.1) == pytest.approx(math.sqrt(75.55))
    assert bezirci_yilmaz.level(5) == "ilköğretim düzeyi"
    assert bezirci_yilmaz.level(10) == "lise düzeyi"
    assert bezirci_yilmaz.level(14) == "lisans düzeyi"
    assert bezirci_yilmaz.level(20) == "akademik düzey"


def test_scores_from_counts() -> None:
    tc = TextCounts(words=10, sentences=2, syllables=25, by_syllables={1: 2, 2: 3, 3: 3, 4: 1, 6: 1})
    assert atesman.score(tc).value == pytest.approx(round(atesman.formula(2.5, 5), 1))
    bz = bezirci_yilmaz.score(tc)
    expected = bezirci_yilmaz.formula(5, 3 / 2, 1 / 2, 0, 1 / 2)
    assert bz.value == pytest.approx(round(expected, 1))
    empty = TextCounts()
    for mod in (atesman, cetinkaya_uzun, bezirci_yilmaz):
        s = mod.score(empty)
        assert s.value is None and s.level == "hesaplanamadı"


def test_end_to_end_counts() -> None:
    # "Su gelecek." → 2 kelime, 1+3 = 4 hece, 1 cümle; başlık sayılmaz.
    r = analyze("Uzun bir başlık satırı\n\nSu gelecek.")
    assert r.stats.word_count == 6
    assert r.stats.sentence_count == 1
    assert r.scores.atesman.value == pytest.approx(round(atesman.formula(2.0, 2.0), 1))


def test_compliance_formula() -> None:
    from kolaymetin.models import Finding

    def f(sev: str, cat: str = "cümle", conf: float = 1.0) -> Finding:
        return Finding(rule_id="KD-X", rule_name="x", category=cat, severity=sev,  # type: ignore[arg-type]
                       message="m", explanation="e", start=0, end=1, confidence=conf)

    weights = {"hata": 3.0, "uyarı": 1.0, "bilgi": 0.25}
    c = compliance.compute([f("hata"), f("uyarı", "kelime"), f("bilgi", "biçim", 0.8)], 4, 0.6, weights)
    penalty = 3 + 1 + 0.2
    assert c.penalty == pytest.approx(penalty)
    assert c.value == round(100 * math.exp(-0.6 * penalty / 4))
    cats = {x.category: x for x in c.by_category}
    assert cats["metin"].score == 100 and cats["cümle"].finding_count == 1
    assert c.contributions[0].rule_id == "KD-X" and c.contributions[0].count == 3
    assert c.reliable
    short = compliance.compute([], 2, 0.6, weights)
    assert short.value == 100 and not short.reliable and short.note


def test_perfect_text_scores_100() -> None:
    r = analyze("Su gelecek. Belediye çalışıyor. Ekipler hazır.")
    assert r.scores.compliance.value == 100
