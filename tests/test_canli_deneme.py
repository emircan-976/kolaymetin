"""Çalışan uygulamaya alışılmadık metinler gönderilerek yapılan denemede (2026-09-30) bulunan
hataların regresyon testleri.

Denenenler: boş ve tek karakterlik metin, emoji, Arapça, Rusça ve İngilizce metin, kod, HTML,
şiir, Osmanlıca, Anayasa maddesi, yemek tarifi, masal, SMS dili, geçersiz tarih, IBAN, boşluksuz
100.000 karakter, UTF-16 dosya.
"""

from __future__ import annotations

import time

from conftest import rule_hits
from kolaymetin import analyze
from kolaymetin.io.readers import read_bytes
from kolaymetin.lexicon import load_lexicon
from kolaymetin.text.segment import _protected_spans, segment
from kolaymetin.text.tokenize import tokenize


def _kinds(text: str) -> list[tuple[str, str]]:
    report = analyze(text)
    return [("başlık" if s.is_heading else "cümle", s.text) for s in report.sentences]


def _rules(text: str) -> set[str]:
    return {f.rule_id for f in analyze(text).findings}


# --------------------------------------------------------------- noktası unutulmuş cümle


def test_single_line_without_period_is_a_sentence_not_a_heading() -> None:
    text = "Müracaatların 01.12.2026 tarihinden itibaren ivedilikle yapılması gerekmektedir"
    assert _kinds(text) == [("cümle", text)]
    assert {"KD-B04", "KD-C03", "KD-C07", "KD-C11"} <= _rules(text)
    assert analyze(text).scores.atesman.value is not None


def test_trailing_emoji_quote_or_parenthesis_does_not_make_a_heading() -> None:
    for text in (
        "Yarın su kesilecek 😱💧 Lütfen su biriktirin 🙏",
        "Başvurular 01.12.2026 tarihinde yapılacaktır (Pazartesi)",
        'Müdürlüğümüzce "ivedilikle müracaat edilmesi gerekmektedir"',
    ):
        assert all(k == "cümle" for k, _ in _kinds(text)), text


def test_real_headings_stay_headings() -> None:
    # Fiilli Kolay Dil başlığı: altında metin var.
    kinds = _kinds("Suyunuz 1 gün gelmeyecek\n\nYarın sular kesilecek. Akşam sular gelecek.")
    assert kinds[0] == ("başlık", "Suyunuz 1 gün gelmeyecek")
    # Fiilsiz başlık ve kapanış satırı metnin sonunda da başlık kalır.
    assert _kinds("Su Kesintisi Hakkında Duyuru") == [("başlık", "Su Kesintisi Hakkında Duyuru")]
    kinds = _kinds("Yarın sular kesilecek. Su biriktirin.\n\nSaygılarımızla")
    assert kinds[-1] == ("başlık", "Saygılarımızla")


def test_inner_sentence_end_before_quote_is_not_a_heading() -> None:
    text = "“Yarın” sular kesilecek — dedi. ‘Su’ biriktirin – lütfen… «Teşekkürler»"
    assert [k for k, _ in _kinds(text)] == ["cümle", "cümle", "cümle"]


# --------------------------------------------------------------- küçük harfle yazılmış metin


def test_lowercase_text_is_split_into_sentences() -> None:
    text = "yarın su kesilecek. lütfen su biriktirin. kesinti akşam bitecek."
    assert [t for _, t in _kinds(text)] == [
        "yarın su kesilecek.", "lütfen su biriktirin.", "kesinti akşam bitecek.",
    ]
    assert "KD-C01" not in _rules(text)


def test_lowercase_split_keeps_abbreviations_and_ordinals() -> None:
    assert len(_kinds("kimlik, pasaport vb. belgeler getirin.")) == 1
    assert len(_kinds("başvuru için 3. kata çıkın.")) == 1
    # Büyük harfle başlayan metinde ". küçük harf" cümleyi bitirmez (eski davranış).
    assert len(_kinds("Formu doldurun. sonra imzalayın.")) == 1


# --------------------------------------------------------------- tarih


def test_invalid_date_is_an_error_without_a_made_up_date() -> None:
    for text, shown in (
        ("Ödeme 31.02.2026 tarihinde yapılacak.", "31.02.2026"),
        ("Başvurular 32.13.2026 tarihinde başlayacak.", "32.13.2026"),
        ("Başvurular 31 Şubat 2026 günü başlayacak.", "31 Şubat 2026"),
    ):
        hits = rule_hits(text, "KD-B04")
        assert len(hits) == 1, text
        assert hits[0].severity == "hata"
        assert hits[0].message == f"'{shown}' gerçek bir tarih değil. Günü ve ayı denetleyin."


def test_wrong_weekday_is_an_error() -> None:
    for text in (
        "Başvurular 1 Aralık 2026 Pazartesi günü başlayacak.",
        "Başvurular 01.12.2026 (Pazartesi) günü başlayacak.",
    ):
        hits = rule_hits(text, "KD-B04")
        assert len(hits) == 1, text
        assert hits[0].severity == "hata"
        assert "bir Salı günü" in hits[0].message
        assert hits[0].suggestion == "Günü düzeltin: '1 Aralık 2026 Salı'."
    assert rule_hits("Başvurular 1 Aralık 2026 Salı günü başlayacak.", "KD-B04") == []


def test_wrong_weekday_is_checked_even_without_weekday_suggestions() -> None:
    profile = {"extends": "kolay-dil", "rules": {"KD-B04": {"params": {"suggest_weekday": False}}}}
    report = analyze("Başvurular 1 Aralık 2026 Pazartesi günü başlayacak.", profile=profile)
    assert [f.severity for f in report.findings if f.rule_id == "KD-B04"] == ["hata"]


def test_iso_and_dashed_dates_are_dates() -> None:
    text = "Son gün 2026/10/01. Kayıt 01-10-2026 günü. Ödeme 2026-10-05 günü."
    suggestions = [f.suggestion for f in rule_hits(text, "KD-B04")]
    assert suggestions == [
        "'2026/10/01' → '1 Ekim 2026 Perşembe'",
        "'01-10-2026' → '1 Ekim 2026 Perşembe'",
        "'2026-10-05' → '5 Ekim 2026 Pazartesi'",
    ]


def test_date_range_with_dash_is_still_two_dates() -> None:
    toks = tokenize("01.11.2026-15.11.2026", 0, 21)
    assert [t.kind for t in toks] == ["date", "punct", "date"]


# --------------------------------------------------------------- performans


def test_long_run_of_letters_is_linear() -> None:
    text = "a" * 50_000
    started = time.perf_counter()
    assert _protected_spans(text, 0, len(text)) == []
    assert time.perf_counter() - started < 0.5
    started = time.perf_counter()
    analyze("a" * 99_999 + ".")
    assert time.perf_counter() - started < 5


def test_email_is_still_protected() -> None:
    text = "Yazın: bilgi.masasi@ornek.bel.tr adresine. Sonra arayın."
    seg = segment(text, load_lexicon().dotted_abbreviations())
    assert len(seg.sentences) == 2


# --------------------------------------------------------------- dosya okuma


def test_utf16_text_file_is_decoded() -> None:
    text = "Yarın sular kesilecek."
    assert read_bytes(text.encode("utf-16"), "not.txt") == text  # BOM'lu (Not Defteri)
    assert read_bytes(text.encode("utf-16-le"), "not.txt") == text
    assert read_bytes(text.encode("utf-16-be"), "not.txt") == text
    assert read_bytes("Yarın".encode("cp1254"), "eski.txt") == "Yarın"


# --------------------------------------------------------------- kelime kuralları


def test_number_with_bare_suffix_is_one_token() -> None:
    toks = tokenize("Saat 9dan 5e kadar.", 0, 19)
    assert [(t.text, t.kind, t.base) for t in toks[1:3]] == [
        ("9dan", "number", "9"), ("5e", "number", "5"),
    ]
    assert toks[1].syllables == 3  # do-kuz-dan
    assert not any(f.text == "dan" for f in rule_hits("Saat 9dan sonra gelin.", "KD-K06"))


def test_iban_country_code_is_not_an_abbreviation() -> None:
    text = "Parayı TR12 0006 1005 1978 6457 8413 26 hesabına yatırın."
    assert rule_hits(text, "KD-K03") == []


def test_formal_imperative_is_flagged() -> None:
    hits = rule_hits("Lütfen formu doldurunuz. Belgeleri teslim ediniz.", "KD-K01")
    assert [h.suggestion for h in hits] == ["'doldurunuz' → 'doldurun'", "'ediniz' → 'edin'"]
    for text in ("Başvurunuz alındı.", "Kapınız açık.", "Formu doldurun."):
        assert rule_hits(text, "KD-K01") == [], text


def test_tarafimizca_is_jargon() -> None:
    hits = rule_hits("Evraklar tarafımızca incelenecek.", "KD-K01")
    assert [h.text for h in hits] == ["tarafımızca"]


def test_dot_decimal_is_flagged() -> None:
    hits = rule_hits("Ödemeler 2.5 milyon liraya ulaştı.", "KD-B03")
    assert [h.suggestion for h in hits] == ["'2.5' → '2,5'"]
    assert rule_hits("Ödemeler 15.000 liraya ulaştı.", "KD-B03") == []


def test_question_agent_is_not_named_as_the_doer() -> None:
    hits = rule_hits("Form kim tarafından imzalanacak?", "KD-C03")
    assert hits and all("('kim')" not in h.message.lower() for h in hits)
    assert "doğrudan sorun" in hits[0].message


def test_common_words_are_not_rare() -> None:
    for text in ("Afiyet olsun.", "Aynen öyle.", "Mobil uygulamayı açın.", "İdare bunu biliyor."):
        assert rule_hits(text, "KD-K06") == [], text


# --------------------------------------------------------------- notlar ve skorlar


def test_non_turkish_text_gets_a_note() -> None:
    note = "Bu metin Türkçe görünmüyor."
    arabic = analyze("سيتم قطع المياه غدا من الساعة التاسعة صباحا.")
    assert any(n.startswith(note) for n in arabic.notes)
    assert not [f for f in arabic.findings if f.rule_id in ("KD-K04", "KD-K06")]
    english = analyze("The water will be cut tomorrow. Please store water for the day.")
    assert any(n.startswith(note) for n in english.notes)
    turkish = analyze("Yarın sular kesilecek. Lütfen su biriktirin. Akşam sular gelecek.")
    assert not any(n.startswith(note) for n in turkish.notes)


def test_reliability_note_counts_sentences() -> None:
    long_sentence = "Belediyemiz " + "ve ".join(["yarın sabah su kesecek "] * 8) + "."
    assert analyze(long_sentence).scores.compliance.note == (
        "Metinde 1 cümle var. Skor en az 3 cümlede güvenilir olur."
    )
    assert analyze("Su Kesintisi").scores.compliance.note == (
        "Metinde denetlenecek bir cümle yok. Skor hesaplanamadı."
    )


def test_atesman_is_clamped_to_0_100() -> None:
    assert analyze("a.").scores.atesman.value == 100
    long_sentence = " ".join(["sorumluluklarımızdan"] * 60) + "."
    assert analyze(long_sentence).scores.atesman.value == 0
