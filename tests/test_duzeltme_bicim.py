"""Biçim kurallarının otomatik düzeltmeleri: sayı, yıl, tarih/saat ve noktalı virgül."""

from __future__ import annotations

import pytest

from kolaymetin.api import analyze


@pytest.mark.parametrize(
    "text",
    [
        "Yirmi otuz kişi geldi.",
        "Yedi sekiz yıl önce geldi.",
        "Üç dört yüz kişi geldi.",
    ],
)
def test_yaklasik_aralik_toplanmaz(text: str) -> None:
    assert analyze(text).fixed_text() == text


@pytest.mark.parametrize(
    ("text", "beklenen"),
    [
        ("Yirmi beş kişi geldi.", "25 kişi geldi."),
        ("İki yüz otuz kişi geldi.", "230 kişi geldi."),
        ("Üç bin beş yüz kişi geldi.", "3.500 kişi geldi."),
        ("Bin dokuz yüz seksen dört kişi geldi.", "1.984 kişi geldi."),
    ],
)
def test_gecerli_sayi_duzelir(text: str, beklenen: str) -> None:
    assert analyze(text).fixed_text() == beklenen


@pytest.mark.parametrize(
    ("text", "beklenen"),
    [
        ("İki bin yirmi altı yılında başlar.", "2026 yılında başlar."),
        ("Bin dokuz yüz seksen dört yılında doğdu.", "1984 yılında doğdu."),
    ],
)
def test_yil_ayiracsiz(text: str, beklenen: str) -> None:
    assert analyze(text).fixed_text() == beklenen


@pytest.mark.parametrize(
    "text",
    [
        "Madde 12.30 uyarınca yapılır.",
        "Sürüm 1.12.2026 çıktı.",
        "Sürüm 1.12.26 çıktı.",
    ],
)
def test_numara_tarih_ya_da_saat_degildir(text: str) -> None:
    assert analyze(text).fixed_text() == text


def test_saat_ve_tarih_duzelir() -> None:
    assert analyze("Toplantı 14.30 başlar.").fixed_text() == "Toplantı saat 14.30 başlar."


def test_noktali_virgul_onundeki_bosluk() -> None:
    assert analyze("Gitti ;geldi.").fixed_text() == "Gitti. Geldi."
    assert analyze("Gitti; geldi.").fixed_text() == "Gitti. Geldi."
