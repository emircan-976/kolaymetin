from __future__ import annotations

import pytest

from kolaymetin.lexicon import load_lexicon
from kolaymetin.text.syllables import (
    count_vowels,
    number_to_words,
    number_to_words_builtin,
    read_date,
    read_number,
    read_time,
    spell_letters,
    syllable_count,
)
from kolaymetin.text.tokenize import tokenize


def toks(text: str) -> list[tuple[str, str]]:
    return [(t.text, t.kind) for t in tokenize(text, 0, len(text), load_lexicon().abbreviation_readings())]


def test_token_kinds() -> None:
    assert toks("Saat 14.30'da, 15.09.2026 tarihinde %35 indirim: 15.000 TL.") == [
        ("Saat", "word"), ("14.30'da", "time"), (",", "punct"), ("15.09.2026", "date"),
        ("tarihinde", "word"), ("%35", "percent"), ("indirim", "word"), (":", "punct"),
        ("15.000", "number"), ("TL", "word"), (".", "punct"),
    ]


def test_url_email_and_apostrophe() -> None:
    kinds = dict(toks("Karşıyaka'da https://yesilova.bel.tr/duyuru ve bilgi@yesilova.bel.tr'ye yazın"))
    assert kinds["Karşıyaka'da"] == "word"
    assert kinds["https://yesilova.bel.tr/duyuru"] == "url"
    assert kinds["bilgi@yesilova.bel.tr'ye"] == "email"


def test_abbreviation_detection() -> None:
    lex = load_lexicon().abbreviation_readings()
    t = {x.text: x for x in tokenize("SGK ve T.C. ile Dr. Ali", 0, 23, lex)}
    assert t["SGK"].is_abbreviation and t["T.C."].is_abbreviation and t["Dr"].is_abbreviation
    assert not t["Ali"].is_abbreviation
    heading = tokenize("SU KESİNTİSİ HAKKINDA DUYURU", 0, 28, lex)
    assert not any(x.is_abbreviation for x in heading)


def test_sentence_initial_flag() -> None:
    t = tokenize('"Belediye geldi', 0, 15, {})
    assert t[1].sentence_initial and not t[2].sentence_initial


# Altın liste: (kelime, beklenen hece sayısı)
GOLD = [
    ("belediye", 4), ("su", 1), ("kesinti", 3), ("başvuru", 3), ("vatandaşlarımızın", 7),
    ("müracaat", 4), ("ivedilikle", 5), ("aşı", 2), ("çocuk", 2), ("öğrenci", 3),
    ("İstanbul", 3), ("ışık", 2), ("üniversite", 5), ("değerlendirilmesinden", 8),
    ("kat", 1), ("ağaç", 2), ("saat", 2), ("kaide", 3), ("şiir", 2), ("mezkûr", 2),
    ("hâlâ", 2), ("elektrik", 3), ("sandalye", 3), ("gerekmektedir", 5), ("yapılacaktır", 5),
    ("bir", 1), ("seçmen", 2), ("sandık", 2), ("deprem", 2), ("toplanma", 3),
    ("alanı", 3), ("Karşıyaka'da", 5), ("e-posta", 3), ("kütüphane", 4), ("merdiven", 3),
    ("tren", 1), ("spor", 1), ("psikolog", 3), ("ilkyardım", 3), ("mahallemizde", 5),
    ("ödeyebilirsiniz", 7), ("Türkiye", 3),
]


@pytest.mark.parametrize(("word", "expected"), GOLD)
def test_syllables_gold(word: str, expected: int) -> None:
    assert syllable_count(word) == expected


def test_gold_list_size() -> None:
    assert len(GOLD) >= 40


@pytest.mark.parametrize(
    ("text", "kind", "expected"),
    [
        ("15", "number", 2),          # on beş
        ("15.000", "number", 3),      # on beş bin
        ("1996", "number", 8),        # bin dokuz yüz doksan altı
        ("3,5", "number", 4),         # üç virgül beş
        ("15'i", "number", 3),        # on beş-i
        ("15.09.2026", "date", 11),   # on beş eylül iki bin yirmi altı
        ("14.30", "time", 4),         # on dört otuz
        ("09.00", "time", 2),         # dokuz
        ("%35", "percent", 5),        # yüzde otuz beş
        ("bilgi@a.tr", "email", 3),
    ],
)
def test_syllables_numbers(text: str, kind: str, expected: int) -> None:
    assert syllable_count(text, kind) == expected


def test_abbreviation_syllables() -> None:
    readings = load_lexicon().abbreviation_readings()
    assert syllable_count("TBMM", "word", True, readings) == 4        # te-be-me-me
    assert syllable_count("ASELSAN", "word", True, {}) == 7           # sözlükte yok → harf harf
    assert syllable_count("AFAD", "word", True, readings) == 2        # a-fad
    assert syllable_count("SGK'ya", "word", True, readings) == 4
    assert syllable_count("km", "word") == 2
    assert spell_letters("ğ") == 3


@pytest.mark.parametrize("n", [0, 1, 7, 10, 15, 99, 100, 101, 999, 1000, 1001, 2026, 15000, 1_000_000, 2_500_300])
def test_builtin_number_reader_matches_num2words(n: int) -> None:
    assert number_to_words_builtin(n).replace(" ", "") == number_to_words(n).replace(" ", "")


def test_readers() -> None:
    assert number_to_words_builtin(-5) == "eksi beş"
    assert "eylül" in read_date("15.09.2026")
    assert read_date("1.2") == read_number("1.2")
    assert read_time("09.00") == "dokuz"
    assert read_number("abc") == "abc"
    assert count_vowels("IŞIK") == 2
