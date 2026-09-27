"""Yirmi farklı kaynaktan metinle yapılan denemede (2026-09-27) bulunan hataların regresyon
testleri.

Kaynaklar: cuma hutbesi, merkez bankası faiz kararı, sınav duyurusu, hastane blogu, klasik öykü,
ansiklopedi maddeleri, kanun maddeleri, yemek tarifi ve yorumları, spor haberi, ulaşım duyurusu,
iş kurumu tanıtımı, e-ticaret iade koşulları, banka bilgilendirmesi, çerez politikası, makale
özeti, ilaç kullanma talimatı (PDF), çamaşır makinesi kılavuzu (PDF) ve kolay okunur bir
sözleşme metni. Örnek cümleler bu metinlerdeki yapıları taklit eder.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from conftest import rule_hits
from kolaymetin import analyze
from kolaymetin.io.readers import _SYMBOL_BULLET_RE
from kolaymetin.lexicon import load_lexicon
from kolaymetin.text.morphology import best
from kolaymetin.text.segment import segment

LEXICON_DIR = Path(__file__).resolve().parents[1] / "src" / "kolaymetin" / "data" / "lexicon"


def _kind(s: object) -> str:
    return "başlık" if s.is_heading else "madde" if s.is_list_item else "cümle"  # type: ignore[attr-defined]


def _sentences(text: str) -> list[tuple[str, str]]:
    """analyze() yolu: normalize() tırnakları '"', tireleri "-" yapar; bölücü ikisini de tanımalı."""
    report = analyze(text)
    raw = segment(text, load_lexicon().dotted_abbreviations())
    via_segment = [(_kind(s), raw.text[s.start : s.end]) for s in raw.sentences]
    via_analyze = [(_kind(s), s.text) for s in report.sentences]
    assert [k for k, _ in via_segment] == [k for k, _ in via_analyze]
    assert len(via_segment) == len(via_analyze)
    return via_segment


def _suggestions(text: str, rule_id: str) -> list[str]:
    return [f.suggestion or "" for f in rule_hits(text, rule_id)]


# --------------------------------------------------------------- cümle bölme


def test_exclamation_inside_embedded_quote_does_not_end_sentence() -> None:
    text = (
        "Bununla beraber, “Ey insanlar! Kendinizi ateşten koruyun”[2] sözü gereğince "
        "çocuklarımızı korumalıyız. Sonra eve döneriz."
    )
    assert [t for _k, t in _sentences(text)] == [
        "Bununla beraber, “Ey insanlar! Kendinizi ateşten koruyun”[2] sözü gereğince "
        "çocuklarımızı korumalıyız.",
        "Sonra eve döneriz.",
    ]


def test_dialogue_dash_starts_a_new_sentence() -> None:
    text = "Babam dedi ki: — Yalan söylersen seni döverim! — Söylemem. — Peki, bunu kim kırdı?"
    assert len(_sentences(text)) == 3


def test_citation_marker_after_full_stop_ends_sentence() -> None:
    text = "Karbondioksit şekere dönüştürülür.[1] Daha sonra ATP kullanılır.[kaynak belirtilmeli] Son."
    assert len(_sentences(text)) == 3


def test_numbered_section_headings() -> None:
    text = (
        "1. Bu Sözleşme\nBu sözleşme hakları açıklar.\n"
        "2. Kelime Anlamları\nİletişim bir yöntemdir.\nDil de bir yöntemdir."
    )
    kinds = _sentences(text)
    assert kinds[0] == ("başlık", "Bu Sözleşme")
    assert kinds[2] == ("başlık", "Kelime Anlamları")
    # Başlık olunca "Bu metinde başlık yok" denmez.
    long_text = text + "\n" + " ".join(["Engelliler herkesle aynı haklara sahiptir."] * 30)
    assert not rule_hits(long_text, "KD-M02")


def test_consecutive_numbered_lines_stay_a_list() -> None:
    kinds = _sentences("Getirmeniz gerekenler:\n1. Kimlik kartı\n2. Fotoğraf\n3. Dilekçe")
    assert [k for k, _t in kinds[1:]] == ["madde", "madde", "madde"]


def test_roman_ordinal_before_a_name_is_not_a_sentence_end() -> None:
    text = "Sinan, Kanuni, II. Selim ve III. Murad dönemlerinde çalıştı. Sonra öldü."
    assert len(_sentences(text)) == 2


def test_footnote_asterisk_starts_a_new_sentence() -> None:
    assert len(_sentences("Ürünü 14 gün içinde iade edebilirsiniz. *Bazı ürünlerde geçerlidir.")) == 2


def test_unpunctuated_line_with_a_sentence_inside_is_not_a_heading() -> None:
    kinds = _sentences("Tam istediğim gibi oldu kıvamı lezzeti. Tşk ederim\n\nSelamlar.")
    assert ("başlık", "Tam istediğim gibi oldu kıvamı lezzeti. Tşk ederim") not in kinds
    assert ("cümle", "Tam istediğim gibi oldu kıvamı lezzeti.") in kinds


def test_pdf_symbol_font_bullets_become_bullets() -> None:
    raw = "Aksi durumda su kaçağı riski vardır.\nu Ürünün içinde su varken kapağı açmayın."
    assert _SYMBOL_BULLET_RE.sub("• ", raw).endswith("\n• Ürünün içinde su varken kapağı açmayın.")


# --------------------------------------------------------------- biçimbilim


@pytest.mark.parametrize("word", ["yendi", "bayılma", "eğilirdim", "Siyanobakteriler", "bakteriler"])
def test_words_that_only_look_passive(word: str) -> None:
    assert not best(word).is_passive


def test_real_passives_still_found() -> None:
    assert best("silinir").is_passive
    assert best("yapılan").is_passive


def test_sports_result_is_not_eating() -> None:
    text = "Erzurumspor, konuk ettiği Samsunspor'u 1-0 yendi."
    assert not rule_hits(text, "KD-C03")


# --------------------------------------------------------------- sözlük eşleşmesi


def test_having_rights_is_not_beneficiary() -> None:
    assert not rule_hits("Engelliler herkesle aynı haklara sahiptir.", "KD-K01")
    assert not rule_hits("Çocuklar düşüncelerini söyleme hakkına sahiptir.", "KD-K01")
    assert rule_hits("Hak sahipleri başvurabilir.", "KD-K01")


def test_idiom_case_must_match() -> None:
    assert not rule_hits("Dadaruh onu kendi önüne alırdı.", "KD-K05")  # "önünü almak" değil
    assert rule_hits("Bu sorunun önünü almak gerek.", "KD-K05")
    assert not rule_hits("İlacı eli altında tutun.", "KD-K05")  # "el altından" değil
    assert rule_hits("Parayı el altından verdi.", "KD-K05")


def test_verb_does_not_match_participle_synonym() -> None:
    text = "Bu örneklerde testler çalışılır. Sorunu kan merkezi personeline bildirin."
    assert not rule_hits(text, "KD-K08")


def test_price_amount_and_fee_are_not_synonyms() -> None:
    text = "İade edilecek bedelden kargo ücreti düşülür. Asgari ödeme tutarı değişebilir."
    assert not rule_hits(text, "KD-K08")


def test_duration_with_number_word_and_modifier_is_not_vague() -> None:
    assert not rule_hits("Özet beş iş günü içinde yayımlanacak.", "KD-K07")


def test_instruction_style_jargon_suggestion() -> None:
    (f,) = rule_hits("Bu iş belediye tarafından yapılacak.", "KD-K01")
    assert "(" not in f.message and "İşi yapanı" in f.message


def test_jargon_inside_a_proper_name_is_ignored() -> None:
    assert not rule_hits("Takım, Amed Sportif Faaliyetler karşısında yenildi.", "KD-K01")


def test_lexicon_yaml_has_no_comma_split_entries() -> None:
    """Tırnaksız virgül YAML akış eşlemesini böler: acilim: Ölçme, Seçme … → "Ölçme"."""
    allowed = {
        "kisaltma", "acilim", "okunus", "bilinir", "ifade", "oneri", "anlam", "not", "aciklama",
        "bicimler", "iki_anlamli", "gercek", "kelime", "grup", "tercih", "desen", "ad",
    }
    for path in LEXICON_DIR.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict):
                assert set(item) <= allowed, (path.name, item)


def test_abbreviation_expansion_is_complete() -> None:
    (f,) = rule_hits("Adaylar ÖSYM sitesinden başvurur.", "KD-K03")
    assert "Ölçme, Seçme ve Yerleştirme Merkezi (ÖSYM)" in (f.suggestion or "")


def test_arabic_script_is_not_an_abbreviation() -> None:
    assert not rule_hits("Mimar Sinan (Osmanlıca: معمار سينان) büyük bir mimardı.", "KD-K03")


def test_religious_abbreviation_is_one_token() -> None:
    hits = rule_hits("Peygamber Efendimiz (s.a.s) şöyle buyurdu.", "KD-K03")
    assert [f.text for f in hits] == ["s.a.s"]
    assert "sayfa" not in (hits[0].suggestion or "")


# --------------------------------------------------------------- cümle kuralları


def test_passive_with_agent_names_the_agent() -> None:
    (f,) = rule_hits("Bu süre, kan merkezi hekimi tarafından düzenlenebilir.", "KD-C03")
    assert "hekimi" in f.message and "belli değil" not in f.message
    assert "düzenleyebilir" in (f.suggestion or "")


def test_agent_applies_only_to_the_nearby_verb() -> None:
    text = (
        "Danışmanlar, işveren tarafından beğenilmeyen davranışların anlatıldığı bir eğitim "
        "vermektedir."
    )
    messages = {f.text: f.message for f in rule_hits(text, "KD-C03")}
    assert "işveren" in messages["beğenilmeyen"]
    assert "işveren" not in messages.get("anlatıldığı", "")


@pytest.mark.parametrize(
    "text",
    [
        "Engelli çocuklar büyürken birey olarak saygı görmelidir.",
        "Ülkeler bu şeyleri mümkün olabildiğince hızlı yaparlar.",
    ],
)
def test_lexicalized_adverbs_are_not_clauses(text: str) -> None:
    assert not rule_hits(text, "KD-C06")


def test_purpose_infinitive_and_fixed_phrase_are_not_nominalizations() -> None:
    assert not rule_hits("İşaret dili de dâhil olmak üzere konuşmak için yöntemler var.", "KD-C07")
    assert rule_hits("Belgelerin teslim edilmesi gerekmektedir.", "KD-C07")


def test_semicolon_split_needs_a_predicate_before_it() -> None:
    for text in (
        "Bağış aralığı ortalama; erkeklerde 90 gün, kadınlarda 120 gün, çocuklarda başka bir gündür.",
        "Değerli yolcularımız; 17 Aralık gününden itibaren; yeni hattımız Donanma Caddesi "
        "üzerinden hizmet verecektir.",
    ):
        for s in _suggestions(text, "KD-C01"):
            assert "'ortalama' kelimesinden" not in s and "'itibaren' kelimesinden" not in s


def test_postposition_before_comma_is_not_a_predicate() -> None:
    text = "Bu bakımdan, iyi bir eğitim için, öncelikle evlatlarımızı iyi tanımak zorundayız."
    assert all("'için'" not in s for s in _suggestions(text, "KD-C01"))


def test_no_split_before_ki() -> None:
    text = "Unutmayalım ki, ebedi bir âlemin varlığına inananlar için asıl başarı, rızaya ulaşmaktır."
    assert all("'ki'" not in s for s in _suggestions(text, "KD-C01"))
    assert not rule_hits(text, "KD-C02")


def test_no_full_stop_after_a_converb() -> None:
    text = "Web sitemiz ziyaret edildiğinde, kişisel verilerin saklanması için hiçbir çerez kullanılmaz."
    assert all("nokta koyun" not in s for s in _suggestions(text, "KD-C01"))


def test_sentence_initial_noun_is_not_a_clause() -> None:
    text = "Astım ve akciğerde nefes darlığına yol açacak astım benzeri belirtiler görülebilir."
    assert all("'ve'" not in s for s in _suggestions(text, "KD-C01"))


@pytest.mark.parametrize(
    "text",
    [
        "Dadaruh, tımarı ben yapacağım, derdim.",
        "Yalan çok fenadır, dedi.",
        "Yok, yok!",
        "Soruları doğru cevaplamış ve uygun bulunmuş kişiler kan verebilir.",
        "Daha önce kan vermiş ve bir sorun yaşamış ise bunu görevliye söyleyin.",
    ],
)
def test_single_information(text: str) -> None:
    assert not rule_hits(text, "KD-C02")


def test_two_predicates_still_found() -> None:
    assert rule_hits("Adam eve gelmiş ve oturmuş.", "KD-C02")


def test_parallel_negatives_are_not_double_negation() -> None:
    assert not rule_hits("Bir yıl içinde ameliyat olmamış, dövme yaptırmamış kişiler.", "KD-C05")
    assert rule_hits("Doktor önermedikçe 3 günden fazla kullanılmamalıdır.", "KD-C05")


def test_quoted_scripture_is_not_the_writers_negation() -> None:
    text = "Bilginin değerini, “Hiç bilenlerle bilmeyenler bir olur mu?” ayeti güzel anlatır."
    assert not rule_hits(text, "KD-C04")


# --------------------------------------------------------------- biçim ve metin kuralları


def test_decimal_percent_example() -> None:
    (f,) = rule_hits("Kurul faiz oranını yüzde 35,5'te sabit tuttu.", "KD-B03")
    assert "35,5 lira" in (f.suggestion or "")


def test_question_style_subheadings_count_as_headings() -> None:
    body = " ".join(["Kartınızın borcunu her ay zamanında ödeyin."] * 12)
    text = (
        f"Asgari ödeme nedir?\n\n{body}\n\nAsgari ödeme nasıl hesaplanır?\n\n{body}\n\n"
        f"Faiz işler mi?\n\n{body}"
    )
    assert analyze(text).stats.word_count > 150
    assert not rule_hits(text, "KD-M02")
