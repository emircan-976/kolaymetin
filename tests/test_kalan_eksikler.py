"""Gerçek dünya denemesinden (2026-10-08) kalan eksiklerin regresyon testleri.

Denenenler: ders sunumu (slayt) PDF'i, emojili sosyal medya duyurusu, ilaç prospektüsü, Rusça
ve İngilizce metin, birleşik adların çoğulu.
"""

from __future__ import annotations

from conftest import rule_hits
from kolaymetin import analyze
from kolaymetin.io.readers import _tidy_pdf_pages


def _sentences(text: str) -> list[tuple[str, bool]]:
    return [(s.text, s.is_heading) for s in analyze(text).sentences]


# --------------------------------------------------------------- kelimeler
def test_compound_noun_plural_is_known() -> None:
    # Çoğulda tamlama eki düşer: "huzurev-ler-i". zeyrek kök olarak "huzurev" veriyordu.
    for text in ("Öğrenciler huzurevlerini ziyaret eder.", "Buzdolaplarını temizleyin.",
                 "Anaokullarına kayıt başladı."):
        assert not rule_hits(text, "KD-K06"), text


def test_mazlik_noun_is_not_a_clause() -> None:
    # "-mAzlIk" sözlükleşmiş ad kurar: "böbrek yetmezliği" yan cümle ya da adlaşmış eylem değil.
    text = "Böbrek yetmezliği olan hastalarda doz ayarlaması gerekebilir."
    assert not rule_hits(text, "KD-C06")
    assert not rule_hits(text, "KD-C07")
    assert not rule_hits("Aralarında anlaşmazlık çıktı.", "KD-C07")


def test_opening_is_reflexive_like_closing() -> None:
    # "Mağaza açılıyor" kendiliğinden olmadır; "kapanmak" gibi yalnızca bilgi verir.
    findings = [f for f in analyze("Kütüphane pazartesi yine açılacak.").findings
                if f.rule_id == "KD-C03"]
    assert findings and all(f.severity == "bilgi" for f in findings)


# --------------------------------------------------------------- emoji
def test_emoji_ends_a_sentence_before_a_capital() -> None:
    assert _sentences("Etkinliğimize hepinizi bekliyoruz 🎉🎈 Ücretsiz! 😊") == [
        ("Etkinliğimize hepinizi bekliyoruz 🎉🎈", False), ("Ücretsiz! 😊", False)]
    assert _sentences("Yarın su kesilecek ⚠️ Lütfen su biriktirin.") == [
        ("Yarın su kesilecek ⚠️", False), ("Lütfen su biriktirin.", False)]


def test_emoji_after_punctuation_does_not_block_the_split() -> None:
    assert _sentences("Harika bir gün! 🎉 Hepinizi bekliyoruz.") == [
        ("Harika bir gün! 🎉", False), ("Hepinizi bekliyoruz.", False)]


def test_emoji_inside_a_sentence_does_not_split_it() -> None:
    assert _sentences("Bugün 😊 güzel bir gün.") == [("Bugün 😊 güzel bir gün.", False)]
    assert _sentences("🎉 Bayram Kutlaması 🎉\n\nHepinizi bekliyoruz.") == [
        ("🎉 Bayram Kutlaması 🎉", True), ("Hepinizi bekliyoruz.", False)]


# --------------------------------------------------------------- Türkçe olmayan metin
def test_non_turkish_text_has_no_score() -> None:
    for text in ("Привет мир. Как дела у тебя сегодня?",
                 "Hello world. The water will be cut tomorrow. Please store water."):
        report = analyze(text)
        assert report.scores.compliance.value is None, text
        assert any("Türkçe görünmüyor" in n for n in report.notes)
    assert analyze("Yarın su kesilecek. Lütfen su biriktirin.").scores.compliance.value is not None


# --------------------------------------------------------------- slayt PDF'i
def test_pdf_letter_spaced_labels_are_joined() -> None:
    page = "E G E  Ü N İ V E R S İ T E S İ   |   M Ü T E R C İ M- T E R C Ü M A N L I K\nB U  Y I L"
    out = _tidy_pdf_pages([page])[0]
    assert out.startswith("EGE ÜNİVERSİTESİ | MÜTERCİM-TERCÜMANLIK")
    assert "BU YIL" in out
    # Sıradan tek harfli kelimeler birleşmez.
    assert _tidy_pdf_pages(["O gün o da geldi."]) == ["O gün o da geldi."]


def test_pdf_page_footers_and_numbers_are_dropped() -> None:
    pages = [f"Konu {i}\nBu sayfada bir cümle var.\nTopluma Hizmet Uygulamaları {i}" for i in range(2, 8)]
    pages += ["Adım 1\nİlk adım.", "Adım 2\nİkinci adım.", "Adım 3\nÜçüncü adım."]
    out = _tidy_pdf_pages(pages)
    assert all("Topluma Hizmet" not in p for p in out)
    # Her sayfada geçen cümle ve yalnızca bazı sayfalarda geçen numaralı başlık kalır.
    assert all("Bu sayfada bir cümle var." in p for p in out[:6])
    assert [p.split("\n")[0] for p in out[6:]] == ["Adım 1", "Adım 2", "Adım 3"]


def test_pdf_space_before_punctuation_is_removed() -> None:
    assert _tidy_pdf_pages(["Bir insana dokunur . Bu ders , o buluşmayı ister ."]) == [
        "Bir insana dokunur. Bu ders, o buluşmayı ister."]


def test_pdf_short_unpunctuated_lines_do_not_merge() -> None:
    page = (
        "Ege Üniversitesi Senatosu'nun kararı ile öğrencilerimiz bu dersi zorunlu olarak alır.\n"
        "Uygulamalı bir derstir\n"
        "Sınavla değil, gerçek bir toplumsal\n"
        "ihtiyaca yönelik proje yürüterek\n"
        "tamamlanır.\n"
        "Ekip işidir\n"
        "Projeler ekipler hâlinde planlanır."
    )
    report = analyze(_tidy_pdf_pages([page])[0])
    assert max(s.word_count for s in report.sentences) <= 13
    assert ("Uygulamalı bir derstir", True) in [(s.text, s.is_heading) for s in report.sentences]


def test_pdf_prose_wrapped_before_a_proper_name_is_not_split() -> None:
    # Düzyazıda satır özel adla başlayabilir; uzun satır kaydırmadır, bölünmez.
    page = (
        "Belediyemiz tarafından yürütülen sosyal yardım programı kapsamında başvurular\n"
        "Sosyal Yardım İşleri Müdürlüğüne yapılabilecek ve sonuçlar ilan edilecektir."
    )
    assert "\n\n" not in _tidy_pdf_pages([page])[0]


def test_vague_time_followed_by_a_number_is_precise() -> None:
    # "akşam saatleri" kök eşlemesiyle "akşam saat 8'den" ifadesini de yakalıyordu.
    assert not rule_hits("Çöpünüzü akşam saat 8'den sonra dışarı koyun.", "KD-K07")
    assert not rule_hits("Akşam saat 20.00'de su gelecek.", "KD-K07")
    assert rule_hits("Akşam saatlerinde su kesilecek.", "KD-K07")
