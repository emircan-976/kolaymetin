from __future__ import annotations

import pytest

from kolaymetin import analyze
from kolaymetin.lexicon import load_lexicon
from kolaymetin.text.segment import segment


def sentences(text: str) -> list[str]:
    seg = segment(text, load_lexicon().dotted_abbreviations())
    return [seg.text[s.start : s.end] for s in seg.sentences]


@pytest.mark.parametrize(
    "text",
    [
        "Dr. Ayşe Yılmaz yarın gelecek.",
        "Prof. Dr. Ali Kaya konuşacak.",
        "Kalem, silgi vb. getirin.",
        "Atatürk Cad. No. 5 adresine gelin.",
        "T.C. Yeşilova Belediyesi duyurur.",
        "Doç. Dr. Can Er ve Av. Deniz Ak katılacak.",
        "Faiz oranı 3.5 oldu.",
        "Toplantı 15.09.2026 günü yapılacak.",
        "Bize bilgi@yesilova.bel.tr adresinden yazın.",
        "Ayrıntılar www.yesilova.bel.tr sitesinde.",
        "Kanunun 51. Maddesi uyarınca ödeyin.",
        "Saat 14.30'da gelin.",
        "Sn. Başkan konuşacak.",
        "Örn. kimlik kartı getirin.",
        "Bkz. Madde 5.",
        "A. Yılmaz imzaladı.",
    ],
)
def test_no_split(text: str) -> None:
    assert len(sentences(text)) == 1, sentences(text)


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Su kesilecek. Belediye boruyu onaracak.", 2),
        ("Neden? Boru bozuldu! Hemen gelin…", 3),
        ("Kalem, silgi vb. Bunları getirin.", 2),
        ("Toplam 15. Bu çok iyi.", 2),
        ('Muhtar "Gelin." dedi. Herkes geldi.', 2),
        ("Tarih 2026. 15 Eylül'de başlıyor.", 2),
        ("Su kesilecek.\n\"Önemli\" bir duyuru.", 2),
        ("Şunları yapın:\nSu biriktirin.", 2),
    ],
)
def test_split(text: str, count: int) -> None:
    assert len(sentences(text)) == count, sentences(text)


def test_list_items_are_sentences() -> None:
    text = "Şunları getirin:\n- Kimlik kartı\n- Adres belgesi\n* Fotoğraf\n1. Dilekçe\n2) Form"
    seg = segment(text, load_lexicon().dotted_abbreviations())
    items = [s for s in seg.sentences if s.is_list_item]
    assert [seg.text[s.start : s.end] for s in items] == [
        "Kimlik kartı", "Adres belgesi", "Fotoğraf", "Dilekçe", "Form"
    ]


def test_list_item_continuation() -> None:
    text = "- Kimlik kartı ve\n  adres belgesi\n- Fotoğraf"
    seg = segment(text, frozenset())
    assert [seg.text[s.start : s.end] for s in seg.sentences] == [
        "Kimlik kartı ve\n  adres belgesi", "Fotoğraf"
    ]


def test_headings() -> None:
    text = "Su kesintisi\n\nYarın su kesilecek.\n\n# Ne yapmalı\n\nSU KESİNTİSİ\nSu gidecek. Su gelecek."
    seg = segment(text, frozenset())
    heads = [seg.text[s.start : s.end] for s in seg.sentences if s.is_heading]
    assert heads == ["Su kesintisi", "Ne yapmalı", "SU KESİNTİSİ"]


@pytest.mark.parametrize(
    "text",
    ["Sayın Vatandaşlarımız,", "Telefon: 185", "bilgi@yesilova.bel.tr", "küçük harfle başlayan satır",
     "- Madde işareti"],
)
def test_not_heading(text: str) -> None:
    seg = segment(text, frozenset())
    assert not any(s.is_heading for s in seg.sentences)


def test_hard_wrapped_lines_join() -> None:
    text = "Belediyemiz yarın mahallenin bütün\nsokaklarında temizlik yapacak."
    assert len(sentences(text)) == 1


def test_paragraphs() -> None:
    seg = segment("Bir.\n\nİki.\n   \n\nÜç.", frozenset())
    assert len(seg.paragraphs) == 3
    assert [s.paragraph_index for s in seg.sentences] == [0, 1, 2]


def test_inline_suppression() -> None:
    text = (
        "<!-- kolaymetin: yoksay KD-K01 -->\nMüracaatınızı yapın.\n\n"
        "Müracaatınızı yapın."
    )
    report = analyze(text)
    hits = [f for f in report.findings if f.rule_id == "KD-K01"]
    assert len(hits) == 1 and hits[0].paragraph_index == 1


def test_inline_suppression_separate_paragraph_and_all_rules() -> None:
    text = "<!-- kolaymetin: yoksay -->\n\nMüracaatınızı ivedilikle yapın.\n\nMüracaat edin."
    report = analyze(text)
    assert all(f.paragraph_index != 0 for f in report.findings)
    assert any(f.rule_id == "KD-K01" for f in report.findings)


def test_comments_do_not_become_words() -> None:
    report = analyze("<!-- bir not -->Su gelecek.")
    assert report.stats.word_count == 2
