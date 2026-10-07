"""Otomatik düzeltmeler (Finding.fix, apply_fixes, CLI --duzelt, web, raporlar).

Bütün denetimler analyze() yolundan geçer: normalleştirme tırnakları ve kesmeleri değiştirir,
düzeltmenin ofsetleri kullanıcının yazdığı metne aittir.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kolaymetin import Finding, Fix, analyze, apply_fixes
from kolaymetin.cli import main
from kolaymetin.web.app import app


def fixes(text: str, rule_id: str) -> list[tuple[str, str]]:
    """Kuralın düzeltmeleri: (özgün metindeki aralık, yeni metin)."""
    r = analyze(text)
    return [
        (text[f.fix.start : f.fix.end], f.fix.text)
        for f in r.findings if f.rule_id == rule_id and f.fix is not None
    ]


@pytest.mark.parametrize(
    ("text", "rule_id", "expected"),
    [
        ("Yirmi beş kişi geldi.", "KD-B01", ("Yirmi beş", "25")),
        ("Toplantıya iki bin kişi geldi.", "KD-B01", ("iki bin", "2.000")),
        ("Bütçe 1250000 lira oldu.", "KD-B01", ("1250000", "1.250.000")),
        ("Okul XV. yüzyılda kuruldu.", "KD-B02", ("XV.", "15.")),
        ("Fiyat 2.5 milyon lira oldu.", "KD-B03", ("2.5", "2,5")),
        ("Başvurular 01.12.2026 günü başlar.", "KD-B04", ("01.12.2026", "1 Aralık 2026 Salı")),
        ("Başvurular 01.12.2026'da başlar.", "KD-B04", ("01.12.2026'da", "1 Aralık 2026'da")),
        ("Başvurular 01.12.2026’da başlar.", "KD-B04", ("01.12.2026’da", "1 Aralık 2026’da")),
        ("01.12.2026 (Salı) günü gelin.", "KD-B04", ("01.12.2026", "1 Aralık 2026")),
        ("Bayram 25 Aralık 2026 günü başlar.", "KD-B04", ("25 Aralık 2026", "25 Aralık 2026 Cuma")),
        ("Toplantı 14.30'da başlar.", "KD-B05", ("14.30'da", "saat 14.30'da")),
        ("14:30 itibarıyla su kesilecek.", "KD-B05", ("14:30", "Saat 14.30")),
        ("Okul kapandı; öğrenciler evde kaldı.", "KD-B06", ("; ö", ". Ö")),
        (
            "LÜTFEN SUYU BOŞA HARCAMAYIN ANKARA'DA SGK BİNASI KAPALI.", "KD-B07",
            ("LÜTFEN SUYU BOŞA HARCAMAYIN ANKARA'DA SGK BİNASI KAPALI",
             "Lütfen suyu boşa harcamayın Ankara'da SGK binası kapalı"),
        ),
        ("Lütfen SUYU BOŞA HARCAMAYIN ARTIK.", "KD-B07",
         ("SUYU BOŞA HARCAMAYIN ARTIK", "suyu boşa harcamayın artık")),
    ],
)
def test_rule_fix(text: str, rule_id: str, expected: tuple[str, str]) -> None:
    assert expected in fixes(text, rule_id)


@pytest.mark.parametrize(
    ("text", "rule_id"),
    [
        # "beşi" sayı sayılmazsa "Yirmi" tek başına "20" olur: "20 beşi geldi".
        ("Yirmi beşi geldi.", "KD-B01"),
        # Ekli sayının eki rakama ünlü uyumuyla bağlanmalı: düzeltme yok.
        ("Yirmi beşinde geldi.", "KD-B01"),
        # Tarih ile gün tutmuyor: hangisinin yanlış olduğunu yazar bilir.
        ("01.12.2026 Pazartesi günü gelin.", "KD-B04"),
        # Sıralamadaki noktalı virgül nokta olursa yarım cümleler çıkar.
        ("Getirin: kimlik; fatura; dilekçe.", "KD-B06"),
        # Yüzdenin açıklaması yazara kalır.
        ("Halkın yüzde 35'i katıldı.", "KD-B03"),
    ],
)
def test_no_fix_when_unsure(text: str, rule_id: str) -> None:
    assert fixes(text, rule_id) == []


def test_quoted_number_is_not_a_bare_million() -> None:
    """'"2.5" milyon': tırnak sayıyı ayırmaz, "milyon" tek başına yazıyla sayı değildir."""
    r = analyze("Fiyat “2,5” milyon lira oldu.")
    assert not [f for f in r.findings if f.rule_id == "KD-B01"]


def test_fixed_text_example() -> None:
    text = (
        "Müracaatların 01.12.2026 tarihinden itibaren yapılması gerekmektedir. Toplantı 14.30'da "
        "başlar.\r\nOkul kapandı; öğrenciler evde kaldı."
    )
    assert analyze(text).fixed_text() == (
        "Müracaatların 1 Aralık 2026 Salı tarihinden itibaren yapılması gerekmektedir. Toplantı "
        "saat 14.30'da başlar.\r\nOkul kapandı. Öğrenciler evde kaldı."
    )


def test_fixes_converge_in_one_pass() -> None:
    """Düzeltilmiş metin yeniden denetlenince yeni bir otomatik düzeltme önerilmez."""
    text = (
        "SU KESİNTİSİ DUYURUSU\n\nSu 01.12.2026 günü 09.00 ile 17.00 arasında kesilecek. "
        "Kesinti yirmi beş mahalleyi etkileyecek; 1250000 lira harcandı. XV. yüzyıl."
    )
    fixed = analyze(text).fixed_text()
    assert fixed != text
    assert [f.rule_id for f in analyze(fixed).findings if f.fix is not None] == []


def test_offsets_follow_the_original_text() -> None:
    """Emoji, CRLF ve art arda boşluk normalleştirmede kayar; düzeltme özgün metne oturur."""
    text = "Dikkat 😀\r\n\r\nBaşvurular   01.12.2026 günü başlar."
    r = analyze(text)
    (f,) = [f for f in r.findings if f.rule_id == "KD-B04"]
    assert f.fix is not None and text[f.fix.start : f.fix.end] == "01.12.2026"
    assert r.fixed_text() == "Dikkat 😀\r\n\r\nBaşvurular   1 Aralık 2026 Salı günü başlar."


def _finding(start: int, end: int, new: str) -> Finding:
    return Finding(
        rule_id="KD-X", rule_name="", category="biçim", severity="uyarı", message="",
        explanation="", start=start, end=end, fix=Fix(start=start, end=end, text=new),
    )


def test_apply_fixes_skips_overlaps() -> None:
    text = "abcdef"
    found = [_finding(3, 5, "X"), _finding(0, 2, "Y"), _finding(1, 4, "Z")]
    assert apply_fixes(text, found) == "YcXf"


def test_ignored_findings_are_not_fixed() -> None:
    text = "Başvurular 01.12.2026 günü başlar."
    r = analyze(text, ignored=[{"rule_id": "KD-B04", "text": "01.12.2026"}])
    assert r.fixed_text() == text


def test_cli_duzelt(tmp_path: Path) -> None:
    source = tmp_path / "metin.txt"
    source.write_text("Başvurular 01.12.2026 günü başlar.", encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    assert main(["denetle", str(source), "--duzelt"], out=out, err=err) == 0
    assert out.getvalue() == "Başvurular 1 Aralık 2026 Salı günü başlar.\n"
    assert "1 otomatik düzeltme uygulandı" in err.getvalue()


def test_cli_text_report_mentions_fixes(tmp_path: Path) -> None:
    source = tmp_path / "metin.txt"
    source.write_text("Başvurular 01.12.2026 günü başlar.", encoding="utf-8")
    out = io.StringIO()
    main(["denetle", str(source)], out=out, err=io.StringIO())
    assert "1 bulgu otomatik düzeltilebilir" in out.getvalue()


def test_web_fix_offsets_are_utf16() -> None:
    """Tarayıcı UTF-16 sayar: emojiden sonraki düzeltme de bir birim kaymalı."""
    text = "😀 Başvurular 01.12.2026 günü başlar."
    data = TestClient(app).post("/api/analyze", json={"text": text}).json()
    (f,) = [f for f in data["findings"] if f["rule_id"] == "KD-B04"]
    assert f["fix"] == {"start": 14, "end": 24, "text": "1 Aralık 2026 Salı"}
    assert text.encode("utf-16-le")[28:48].decode("utf-16-le") == "01.12.2026"


def test_exports_include_fixed_text() -> None:
    r = analyze("Başvurular 01.12.2026 günü başlar.")
    assert "## Otomatik düzeltilmiş metin" in r.to_markdown()
    assert "> Başvurular 1 Aralık 2026 Salı günü başlar." in r.to_markdown()
    assert "Otomatik düzeltilmiş metin</h2>" in r.to_html()
    clean = analyze("Başvurular 1 Aralık 2026 Salı günü başlar.")
    assert "Otomatik düzeltilmiş metin" not in clean.to_markdown()
