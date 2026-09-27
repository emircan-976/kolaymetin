from __future__ import annotations

import pytest

from kolaymetin import analyze
from kolaymetin.text.normalize import (
    fold_circumflex,
    is_upper_word,
    normalize,
    turkish_capitalize,
    turkish_lower,
    turkish_upper,
)


@pytest.mark.parametrize(
    ("upper", "lower"),
    [("IŞIK", "ışık"), ("İSTANBUL", "istanbul"), ("ÇİÇEK", "çiçek"), ("IĞDIR", "ığdır"),
     ("İzmir", "izmir"), ("ÖĞRENCİ", "öğrenci"), ("Işıl", "ışıl")],
)
def test_turkish_lower(upper: str, lower: str) -> None:
    assert turkish_lower(upper) == lower


@pytest.mark.parametrize(
    ("lower", "upper"),
    [("istanbul", "İSTANBUL"), ("ışık", "IŞIK"), ("çiçek", "ÇİÇEK"), ("iğne", "İĞNE"), ("ılık", "ILIK")],
)
def test_turkish_upper(lower: str, upper: str) -> None:
    assert turkish_upper(lower) == upper


def test_str_lower_is_wrong_but_ours_is_right() -> None:
    assert "I".lower() == "i"  # Python'un varsayılanı Türkçe için yanlış
    assert turkish_lower("I") == "ı"
    assert len(turkish_lower("İ")) == 1


def test_capitalize_and_helpers() -> None:
    assert turkish_capitalize("iSTANBUL") == "İstanbul"
    assert turkish_capitalize("") == ""
    assert fold_circumflex("mezkûr kâğıt") == "mezkur kağıt"
    assert is_upper_word("SGK'YA")
    assert not is_upper_word("Sgk")
    assert not is_upper_word("123")


def test_quotes_dashes_spaces() -> None:
    nt = normalize("“Merhaba” – dedi…  tamam​.")
    assert nt.text == '"Merhaba" - dedi… tamam.'


def test_crlf_and_offsets() -> None:
    original = "Bir.\r\nİki   üç."
    nt = normalize(original)
    assert nt.text == "Bir.\nİki üç."
    start = nt.text.index("üç")
    o_start, o_end = nt.to_original(start, start + 2)
    assert original[o_start:o_end] == "üç"


def test_combining_characters_nfc() -> None:
    original = "Açık kapı"  # c + birleşik çengel
    nt = normalize(original)
    assert nt.text == "Açık kapı"
    s = nt.text.index("kapı")
    a, b = nt.to_original(s, s + 4)
    assert original[a:b] == "kapı"
    a, b = nt.to_original(0, 4)
    assert original[a:b] == "Açık"


def test_to_original_edges() -> None:
    nt = normalize("abc")
    assert nt.to_original(3, 3) == (3, 3)
    assert nt.to_original(1, 1) == (1, 1)
    assert nt.to_original(-5, 99) == (0, 3)


def test_findings_point_to_original_text() -> None:
    original = "“Müracaatınızı”  ivedilikle​ yapın.\r\n"
    report = analyze(original)
    hits = [f for f in report.findings if f.rule_id == "KD-K01"]
    assert {f.text for f in hits} == {"Müracaatınızı", "ivedilikle"}
    for f in hits:
        assert original[f.start : f.end] == f.text
