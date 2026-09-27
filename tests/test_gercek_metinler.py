"""Gerçek kamu duyurularında (valilik, belediye, AFAD, Sağlık Bakanlığı) bulunan hataların
regresyon testleri."""

from __future__ import annotations

import datetime as dt

import pytest

from conftest import rule_hits
from kolaymetin import analyze
from kolaymetin.lexicon import load_lexicon
from kolaymetin.rules.sentence import active_form
from kolaymetin.text.morphology import WordContext, best
from kolaymetin.text.segment import segment


def _segment(text: str):  # type: ignore[no-untyped-def]
    return segment(text, load_lexicon().dotted_abbreviations())


# --- Edilgenden etken biçim üretimi


@pytest.mark.parametrize(
    ("passive", "active"),
    [
        ("bekleniyor", "bekliyor"),  # "bekleyiyor" değil
        ("okunuyor", "okuyor"),
        ("sağlanıyor", "sağlıyor"),
        ("ödeniyor", "ödüyor"),
        ("edildiği", "ettiği"),  # "etdiği" değil
        ("edildikten", "ettikten"),
        ("yapıldı", "yaptı"),
        ("kesildi", "kesti"),
    ],
)
def test_active_form_phonology(passive: str, active: str) -> None:
    assert active_form(best(passive)) == active


def test_active_form_irregular_short_stem() -> None:
    assert active_form(best("yeniliyor")) is None  # ye-n-iyor → "yiyor": düzensiz


# --- Büyük harfle vurgulanan kelimeler kısaltma değildir


def test_capitalized_words_are_not_abbreviations() -> None:
    text = (
        "BUZLANMA VE DON UYARISI: Yollar kayabilir. "
        "Deprem olursa ÇÖK, KAPAN, TUTUN. Asansörü KULLANMAYIN. ACİL durumda 112'yi arayın."
    )
    flagged = {f.text for f in rule_hits(text, "KD-K03")}
    assert not flagged & {"VE", "DON", "ÇÖK", "KAPAN", "TUTUN", "ACİL"}


def test_real_abbreviations_still_flagged() -> None:
    assert rule_hits("Başvurunuzu SGK'ya yapın.", "KD-K03")
    assert rule_hits("Bilgi için İBB'yi arayın.", "KD-K03")


def test_lowercase_word_is_not_abbreviation() -> None:
    doc = analyze("Evde bir ilk yardım kit bulundurun.")
    assert not [f for f in doc.findings if f.rule_id == "KD-K03"]


# --- Addan türeyen -lık, eylem isimleştirmesi değildir


@pytest.mark.parametrize("word", ["Müdürlüğü", "sıcaklıklarının", "güvenlik", "sağlık", "yağışlı"])
def test_noun_derivations_are_not_nominalized(word: str) -> None:
    assert not best(word).is_nominalized


@pytest.mark.parametrize("word", ["alanda", "sandık", "çakmak", "düğmelerine"])
def test_plain_nouns_get_no_verbal_flags(word: str) -> None:
    a = best(word)
    assert not (a.is_participle or a.is_converb or a.is_nominalized)


def test_c07_not_triggered_by_ness_nouns() -> None:
    assert not rule_hits("Sağlık Müdürlüğü güvenlik kartı dağıtacak.", "KD-C07")


def test_c07_still_triggered_by_verbal_nouns() -> None:
    assert rule_hits("Belgelerin teslim edilmesi ve formun doldurulması gerekmektedir.", "KD-C07")


# --- Sözlükleşmiş edilgen biçimler


@pytest.mark.parametrize("word", ["DOKUNMAYIN", "kaynaklanmaktadır", "buzlanma", "yaralanmaya"])
def test_lexicalized_passives(word: str) -> None:
    assert not best(word).is_passive


# --- Yüklem sanılan kelimeler


def test_gore_is_postposition_before_comma() -> None:
    hits = rule_hits("Son verilere göre, yarın hava çok ısınacak.", "KD-C02")
    assert not hits


def test_reduplication_is_not_a_predicate() -> None:
    hits = rule_hits("Yarın yer yer ve zaman zaman yağmur yağacak.", "KD-C02")
    assert not hits


def test_plural_noun_before_comma_is_not_a_predicate() -> None:
    hits = rule_hits("Yaşlılar, bebekler ve hastalar evde kalsın.", "KD-C02")
    assert not hits


# --- Bölme önerisi


def test_split_hint_keeps_case_and_skips_noun_commas() -> None:
    text = (
        "Çorum Belediyesi, içme suyu altyapı yenileme çalışmaları kapsamında kentte bazı "
        "bölgelerde su kesintisi yapılacağını duyurdu."
    )
    hint = rule_hits(text, "KD-C01")[0].suggestion or ""
    assert "belediyesi" not in hint  # küçük harfe çevrilmiş özel ad önerilmez


# --- Satır sonuyla ayrılmış paragraflar ve ara başlıklar


def test_subheading_between_lines_is_separate() -> None:
    text = (
        "Depremde sakin olun.\nBina içindeyseniz\nKesinlikle panik yapmayınız.\n"
        "Dolaplardan uzak durun."
    )
    seg = _segment(text)
    heads = [seg.text[s.start : s.end] for s in seg.sentences if s.is_heading]
    assert heads == ["Bina içindeyseniz"]
    assert len(seg.sentences) == 4


def test_single_newline_paragraphs_from_web_paste() -> None:
    lines = [f"Belediye {i}. sokağı yarın temizleyecek. Araçları çekin." for i in range(1, 7)]
    doc = analyze("\n".join(lines))
    assert not [f for f in doc.findings if f.rule_id == "KD-M01"]


def test_hard_wrapped_paragraph_stays_together() -> None:
    text = (
        "Belediyemiz yarın mahallenin bütün\nsokaklarında temizlik yapacak. Araçlarınızı\n"
        "sabah erkenden çekin. Çöpleri\nakşam çıkarın."
    )
    assert len(_segment(text).paragraphs) == 1


def test_comma_ended_line_continues_sentence() -> None:
    text = "Vatandaşların dikkatli olması;\nBu doğrultuda araçların hazır tutulması önemlidir.\nDuyurulur."
    seg = _segment(text)
    assert len(seg.sentences) == 2


def test_dash_without_space_is_list_item() -> None:
    seg = _segment("Önlemler:\n-Güneşe çıkmayın.\n-Su için.")
    assert [s.is_list_item for s in seg.sentences] == [False, True, True]


# --- Dolaylı hitap ve sözlük


def test_kamuoyunun_bilgisine_sunulur_is_indirect() -> None:
    assert rule_hits("Kamuoyunun bilgisine sunulur.", "KD-C11")


def test_suretiyle_suggestion() -> None:
    hit = rule_hits("Terleme suretiyle vücut ısısı düşer.", "KD-K01")[0]
    assert "yoluyla" in (hit.suggestion or "")


# =====================================================================================
# 2. tur: kolaydil.tr Kolay Dil metinleri, belediye/e-Devlet KVKK aydınlatma metinleri,
# MEB kayıt duyurusu ve Vikipedi makaleleriyle yapılan denemede bulunan hatalar.
# =====================================================================================


# --- Sezgisel çözümleyici


def test_necessitative_is_not_negative() -> None:
    assert not best("olmalıyım").is_negative  # "-malı" gereklilik, olumsuzluk değil
    assert best("olmamalıyım").is_negative


@pytest.mark.parametrize("word", ["Valdivia", "kontinü", "travertensert", "sintió"])
def test_heuristic_passive_needs_valid_ending(word: str) -> None:
    ctx = WordContext(capitalized=word[0].isupper())
    assert not best(word, ctx).is_passive


def test_proper_noun_is_not_passive() -> None:
    hits = rule_hits("Deprem en çok Valdivia kentinde hissedildi.", "KD-C03")
    assert "Valdivia" not in [f.text for f in hits]


# --- Bağlama göre çözümleme


def test_negative_imperative_at_sentence_end() -> None:
    assert not rule_hits("Zarfını kapatmayı unutma.", "KD-C07")
    assert rule_hits("Zarfını kapatmayı unutma.", "KD-C04")


def test_verbal_noun_before_necessity_is_not_negative() -> None:
    text = "Mahremiyetimi korumam gerekiyor."
    assert not rule_hits(text, "KD-C04")
    assert not rule_hits(text, "KD-C05")


def test_negative_verbal_noun_inside_word_still_clause_end() -> None:
    # "ısınma ve gıda yardımı": "ısınma" olumsuz emir değildir
    text = "Isınma ve gıda yardımı başvuruları alınmaya başlanacaktır."
    assert not rule_hits(text, "KD-C02")


# --- KD-C07: yalnızca yan cümle taşıyan ad-fiiller


@pytest.mark.parametrize(
    "text",
    [
        "Temizleme işlemi damıtma ve ağartma ile yapılır.",
        "Kişisel Verileri Koruma Kurulu ve Aydınlatma Metni yayımlandı.",
        "Yeni düzenlemeler ve gelişmeler duyuruldu.",
        "Sessizce yardım istemek ne demek?",
    ],
)
def test_c07_ignores_lexicalized_nouns(text: str) -> None:
    assert not rule_hits(text, "KD-C07")


def test_c07_flags_passive_start_pattern() -> None:
    assert rule_hits("Müracaatlar yarından itibaren alınmaya başlanacaktır.", "KD-C07")


# --- KD-C02 / KD-C10: gömülü yüklemler


@pytest.mark.parametrize(
    "text",
    [
        "Kimse beni görmesin diye kapıyı kilitlerim.",
        'Yine "UZAK DUR" derim.',
        "Resmi uygulamayı seç (Emniyet Genel Müdürlüğü yazsın).",
    ],
)
def test_embedded_predicates_are_not_separate_information(text: str) -> None:
    assert not rule_hits(text, "KD-C02")
    assert not rule_hits(text, "KD-C10")


# --- KD-C03


def test_agentive_noun_is_not_passive() -> None:
    assert not rule_hits("Belediye yüklenicilere ödeme yaptı.", "KD-C03")


# --- Sözlük eşleşmeleri


@pytest.mark.parametrize(
    ("text", "rule_id"),
    [
        ("Dosya yükleme ekranı açıldı.", "KD-K01"),  # "yüklenici" girdisi
        ("Kanun hükümleri uygulanır.", "KD-K01"),  # "hükmünde" girdisi
        ("Sistem log kayıtlarını saklar.", "KD-K02"),  # "login" girdisi
    ],
)
def test_inflected_entries_do_not_match_other_forms(text: str, rule_id: str) -> None:
    hits = rule_hits(text, rule_id)
    assert not [f for f in hits if "firma" in (f.suggestion or "") or "yerine geçer" in (f.suggestion or "")
                or "giriş" in (f.suggestion or "")]


def test_inflected_entry_still_matches_itself() -> None:
    assert rule_hits("Bu belge kimlik hükmündedir.", "KD-K01") or rule_hits(
        "Bu belge kimlik hükmünde sayılır.", "KD-K01"
    )


def test_foreign_suggestions_are_plain_words() -> None:
    hit = rule_hits("Kolay Dil standart dilin türü.", "KD-K02")[0]
    assert "ölçün" not in (hit.suggestion or "")


# --- KD-K06


@pytest.mark.parametrize(
    "text",
    [
        "Resimdeki yer Beyoğlu.",
        "Aşağıdaki kutuya yaz.",
        "Kalemi bul. Düğmeye bas.",
        "Evden çıktığımda güvende olmalıyım.",
        "Yani şöyle yaptım, yine geldim.",
    ],
)
def test_common_words_are_not_rare(text: str) -> None:
    assert not rule_hits(text, "KD-K06")


# --- KD-K03


def test_all_caps_city_is_not_abbreviation() -> None:
    assert not rule_hits("Adres: Cumhuriyet Cad. No:1 Keçiören/ANKARA.", "KD-K03")


def test_abbreviation_explained_in_next_sentence() -> None:
    text = "TBMM'yi Tanıyalım\n\nTBMM: Türkiye Büyük Millet Meclisi demek.\n\nTBMM Ankara'da."
    assert not rule_hits(text, "KD-K03")


def test_bay_is_not_abbreviation() -> None:
    assert not rule_hits("Bay Ahmet toplantıya geldi.", "KD-K03")


# --- Biçim kuralları


def test_scale_word_after_digits_is_fine() -> None:
    assert not rule_hits("Türkiye'de 100 milyon zeytin ağacı var.", "KD-B01")
    assert rule_hits("Yüz milyon kişi izledi.", "KD-B01")


@pytest.mark.parametrize("text", ["Robert M. Nadeau yazdı.", "Filmi CD olarak aldık.", "El Universal (México, D. F.) yazdı."])
def test_initials_and_acronyms_are_not_roman(text: str) -> None:
    assert not rule_hits(text, "KD-B02")


def test_roman_numerals_still_flagged() -> None:
    assert len(rule_hits("XX. yüzyılda II. Dünya Savaşı oldu.", "KD-B02")) == 2


def test_no_weekday_for_historic_or_named_dates() -> None:
    assert not rule_hits("TBMM 23 Nisan 1920'de açıldı.", "KD-B04")
    assert not rule_hits("Saray 1 Kasım İlkokulu öğrencileri yazdı.", "KD-B04")
    next_year = dt.date.today().year + 1
    assert rule_hits(f"Toplantı 12 Ekim {next_year} günü yapılacak.", "KD-B04")


def test_direct_speech_quotes_are_not_scare_quotes() -> None:
    assert not rule_hits("Milletvekilleri “evet” veya “hayır” der.", "KD-B08")
    assert not rule_hits("Çoğu kişi “evet” dediğinde yasa çıkar.", "KD-B08")
    assert rule_hits("Bu “ücretsiz” hizmet çok pahalı.", "KD-B08")


def test_discourse_marker_is_not_list_item() -> None:
    assert not rule_hits("Örneğin, AKP, MHP veya CHP partidir.", "KD-M03")


def test_source_line_is_not_key_information() -> None:
    text = (
        "KADES bir telefon uygulaması.\nDevlet kadınları korumak için yaptı.\n"
        "Acil durumda yardım çağır.\nUygulamayı telefonuna indir.\n"
        "Kaynak: https://www.icisleri.gov.tr/kadin-destek-uygulamasi-kades"
    )
    assert not rule_hits(text, "KD-M04")
