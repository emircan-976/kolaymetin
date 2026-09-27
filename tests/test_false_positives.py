"""Yanlış pozitif testleri: özel adlar, adresler, telefonlar, e-posta ve URL uyarı üretmemeli."""

from __future__ import annotations

import pytest

from kolaymetin import analyze

WORD_RULES = {"KD-K01", "KD-K02", "KD-K03", "KD-K04", "KD-K05", "KD-K06", "KD-K07", "KD-B01",
              "KD-B02", "KD-B05", "KD-B06", "KD-B07", "KD-C09"}


@pytest.mark.parametrize(
    ("text", "span"),
    [
        ("Karşıyaka Belediyesi yarın açık.", "Karşıyaka Belediyesi"),
        ("Yeşilova Belediyesi Başkanı konuştu.", "Yeşilova Belediyesi Başkanı"),
        ("Adres: Atatürk Cad. No: 12 Karşıyaka/İzmir", "Atatürk Cad. No: 12 Karşıyaka/İzmir"),
        ("Cumhuriyet Mah. 1203 Sok. No. 5 adresine gelin.", "Cumhuriyet Mah. 1203 Sok. No. 5"),
        ("Bizi arayın: 0232 555 12 34", "0232 555 12 34"),
        ("Bizi arayın: (0232) 555 12 34", "(0232) 555 12 34"),
        ("Çağrı merkezi: 444 35 35", "444 35 35"),
        ("Bize yazın: bilgi@yesilova.bel.tr", "bilgi@yesilova.bel.tr"),
        ("Ayrıntılar: https://www.yesilova.bel.tr/duyurular", "https://www.yesilova.bel.tr/duyurular"),
        ("Ayrıntılar: www.yesilova.bel.tr", "www.yesilova.bel.tr"),
        ("Mustafa Kemal Atatürk Parkı açık.", "Mustafa Kemal Atatürk Parkı"),
        ("Ücret 10 TL.", "10 TL"),
    ],
)
def test_no_warning_on_names_addresses_contacts(text: str, span: str) -> None:
    report = analyze(text)
    start = text.index(span)
    end = start + len(span)
    bad = [
        f"{f.rule_id}: {f.text}" for f in report.findings
        if f.rule_id in WORD_RULES and f.start < end and start < f.end
    ]
    assert not bad, bad


def test_phone_numbers_are_not_times_or_dates() -> None:
    report = analyze("Telefon: 0232 555 12 34. Faks: 0232 555 12 35.")
    assert not [f for f in report.findings if f.rule_id in ("KD-B04", "KD-B05")]


def test_easy_text_has_no_findings() -> None:
    text = "Su kesintisi\n\nYarın su gelecek.\nBelediye çalışıyor.\nSorunuz var mı?\nBizi arayın: 185"
    assert analyze(text).findings == []
