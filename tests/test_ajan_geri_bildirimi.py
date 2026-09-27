"""Dört bağımsız deneme raporunda (2026-09-26) bulunan hataların regresyon testleri.

Her test bir raporun bir maddesine karşılık gelir: yanlış pozitifler, bozuk öneriler,
Windows'a özgü hatalar, web arayüzü kilitlenmesi ve profil/sözlük sınır durumları.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import rule_hits
from kolaymetin import analyze
from kolaymetin.api import EmptyInput
from kolaymetin.io.readers import ReaderError, read_file
from kolaymetin.profiles import load_profile
from kolaymetin.readability.compliance import FORMULA
from kolaymetin.text.segment import segment
from kolaymetin.web.app import app

client = TestClient(app)


def _rules(text: str, profile: str = "kolay-dil") -> set[str]:
    return {f.rule_id for f in analyze(text, profile=profile).findings}


# --------------------------------------------------------------- altyapı


def test_ignoring_a_long_sentence_does_not_lock_the_web_ui() -> None:
    long_sentence = " ".join(["Belediyemiz tarafından yürütülen çalışmalar"] * 40) + "."
    assert len(long_sentence) > 500
    body = {"text": long_sentence, "ignored": [{"rule_id": "KD-C01", "text": long_sentence}]}
    res = client.post("/api/analyze", json=body)
    assert res.status_code == 200
    assert "KD-C01" not in {f["rule_id"] for f in res.json()["findings"]}


def test_oversized_ignore_list_gets_a_clear_message() -> None:
    big = "a" * 100_000
    body = {"text": "Su yarın gelecek.", "ignored": [{"rule_id": "KD-C01", "text": big}] * 5}
    res = client.post("/api/analyze", json=body)
    assert res.status_code == 422
    assert "Yoksayılanları geri al" in res.json()["detail"]


@pytest.mark.parametrize(
    "text", ["15. yüzyılda Osmanlı devleti büyüdü.", "1. maddeye göre işlem yapıldı.", "3. Madde uyarınca bakıldı."]
)
def test_ordinal_at_line_start_is_not_a_list_marker(text: str) -> None:
    seg = segment(text, frozenset())
    assert len(seg.sentences) == 1
    s = seg.sentences[0]
    assert not s.is_list_item
    assert seg.text[s.start : s.end] == text  # sıra sayısı kırpılmıyor


def test_numbered_list_still_works() -> None:
    seg = segment("1. Kimliğinizi getirin.\n2. Formu doldurun.", frozenset())
    assert [s.is_list_item for s in seg.sentences] == [True, True]
    seg = segment("1. kimlik kartı\n2. adres belgesi", frozenset())
    assert [s.is_list_item for s in seg.sentences] == [True, True]


def test_formula_and_summary_are_cp1254_safe() -> None:
    FORMULA.encode("cp1254")
    report = analyze("Başvurular alınacaktır. Müracaatınızı ivedilikle yapınız.")
    str(report).encode("cp1254")  # print(report) Türkçe Windows konsolunda çökmemeli
    assert "Uyum skoru" in str(report)


def test_directory_input_says_folder(tmp_path: Path) -> None:
    with pytest.raises(ReaderError, match="klasör"):
        read_file(tmp_path)


def test_empty_text_is_an_error_everywhere() -> None:
    with pytest.raises(EmptyInput):
        analyze("   \n ")
    res = client.post("/api/analyze", json={"text": "  "})
    assert res.status_code == 422
    assert "boş" in res.json()["detail"]


def test_profile_extends_is_relative_to_the_profile_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "alt" / "klasor"
    folder.mkdir(parents=True)
    (folder / "taban.yaml").write_text("extends: kolay-dil\ncompliance_k: 0.3\n", encoding="utf-8")
    (folder / "ozel.yaml").write_text("extends: taban.yaml\nname: ozel\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # çalışma klasörü başka bir yer
    prof = load_profile(str(folder / "ozel.yaml"))
    assert prof.compliance_k == 0.3


def test_multiword_entries_do_not_span_punctuation() -> None:
    hits = rule_hits("Söz - konusu durum. Söz konusu çalışma bitti.", "KD-K07")
    assert [h.text for h in hits] == ["Söz konusu"]


def test_ikonlar_script_parses_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ikonlar

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        ikonlar.main(["--help"])
    assert exc.value.code == 0
    assert not (tmp_path / "--help").exists()
    assert ikonlar.main(["--kontrol"]) == 0  # depodaki ikonlar güncel
    assert ikonlar.main([str(tmp_path / "yok"), "--kontrol"]) == 1


# --------------------------------------------------------------- yanlış pozitifler


def test_surnames_are_not_negative_verbs() -> None:
    text = "Toplantıya Ahmet Yılmaz, Ali Korkmaz ve Mehmet Sönmez katıldı."
    assert not {"KD-C04", "KD-C02"} & _rules(text)
    assert "KD-C04" not in _rules("Korkmaz ailesi yarın gelecek.")


def test_bosa_is_an_adverb_not_a_predicate() -> None:
    assert "KD-C02" not in _rules("Lütfen suyu birkaç dakika boşa akıtın.")


def test_reflexive_advice_is_not_passive() -> None:
    assert "KD-C03" not in _rules("Gripten korunmak için ellerinizi yıkayın. Soğuktan korunun.")


def test_participles_get_no_active_form_suggestion() -> None:
    for text, bad in [
        ("Ambalajı açılmış ürün iade edilmez.", "'açmış'"),
        ("Çalışmalar öngörülenden erken bitti.", "'öngörenden'"),
    ]:
        for f in rule_hits(text, "KD-C03"):
            assert bad not in (f.suggestion or "")


def test_percent_hint_depends_on_context() -> None:
    hint = {f.text: f.suggestion or "" for f in analyze(
        "Banka faiz oranını yüzde 45 yaptı. Kumaşın yüzde 70'i pamuktur. Vatandaşların %35'i başvurdu."
    ).findings if f.rule_id == "KD-B03"}
    assert "kişi" not in hint["yüzde 45"] and "lira" in hint["yüzde 45"]
    assert "kişi" not in hint["yüzde 70'i"]
    assert "100 kişiden 35'i" in hint["%35'i"]


def test_counted_duration_is_not_vague() -> None:
    assert not rule_hits("Ürünü 14 gün içinde iade edebilirsiniz.", "KD-K07")
    assert not rule_hits("En geç 3 iş günü içinde ararız.", "KD-K07")
    assert rule_hits("Kargonuz gün içinde gelecek.", "KD-K07")


def test_literal_idioms_are_not_flagged() -> None:
    assert not rule_hits("Otobüs sabah saat 08.00'de yola çıktı.", "KD-K05")
    assert not rule_hits("Küçük kız ormana doğru yola çıkmış.", "KD-K05")
    assert not rule_hits("Kapıyı açın.", "KD-K05")
    assert not rule_hits("Kırmızı düğmeye basın.", "KD-K05")
    hits = rule_hits("Belediye yeni projeyle yola çıktı.", "KD-K05")
    assert hits and hits[0].severity == "bilgi" and "Mecaz" in (hits[0].suggestion or "")
    assert rule_hits("Belediye soruna el attı.", "KD-K05")[0].severity == "uyarı"


def test_date_range_needs_no_weekdays() -> None:
    assert not rule_hits("Başvurular 6 Şubat - 2 Mart 2026 tarihleri arasında.", "KD-B04")
    assert not rule_hits("Fuar 15-20 Eylül günlerinde açık.", "KD-B04")
    hits = rule_hits("Kayıt 01.11.2026 - 15.11.2026 arasında.", "KD-B04")
    assert hits and all("Pazar" not in (h.suggestion or "").split("'")[-2] for h in hits)


def test_colon_title_is_a_heading() -> None:
    for text in ("Su kesintisi: 15 Eylül\n\nYarın sabah su kesilecek.",
                 "DUYURU: Su Kesintisi\nYarın sabah su kesilecek."):
        seg = segment(text, frozenset())
        assert seg.sentences[0].is_heading
    assert not segment("Telefon: 185\n\nYarın gelin.", frozenset()).sentences[0].is_heading


def test_normal_sov_sentence_is_not_late_predicate() -> None:
    assert not rule_hits("Eski zamanlarda, küçük bir köyde tatlı bir kız yaşarmış.", "KD-C10")
    hits = rule_hits(
        "Belediyemiz bu kış ihtiyacı olan ailelere yakacak ve yiyecek yardımı da yapacak.", "KD-C10"
    )
    assert hits and "başına" not in (hits[0].suggestion or "")


def test_sentence_initial_names_are_not_rare_words() -> None:
    assert not rule_hits("Ali arkadaşına döndü. Merkür Güneş'e en yakın gezegendir.", "KD-K06")
    text = "Pıtır bir sincapmış. Pıtır palamut toplarmış. Pıtır'ın yuvası ağaçtaymış."
    assert "Pıtır" not in {h.text for h in rule_hits(text, "KD-K06")}


def test_salutation_is_its_own_line() -> None:
    text = "Değerli Sakinlerimiz,\nİlçemiz genelinde yarın saat 10.00'da su kesintisi olacak."
    report = analyze(text)
    assert report.sentences[0].text == "Değerli Sakinlerimiz,"
    assert report.sentences[1].word_count == 8


def test_inflected_common_words_are_not_long() -> None:
    text = "Ellerinizi yıkayın. Tüketiciye bilgi verin. Büyükannesi geldi. Ürünü iade edebilirsiniz."
    assert not rule_hits(text, "KD-K04")
    assert rule_hits("Vatandaşlarımıza duyururuz.", "KD-K04")
    assert rule_hits("Değerlendirilmesinden sonra ararız.", "KD-K04")
    assert rule_hits("Meteoroloji uyardı.", "KD-K04")


def test_long_word_hints_are_word_specific() -> None:
    hints = {f.suggestion for f in analyze(
        "Değerlendirilmesinden sonra ararız. Vatandaşlarımıza duyururuz. Verilebilecektir."
    ).findings if f.rule_id == "KD-K04"}
    assert len(hints) == 3
    assert not any("başvurularınızın değerlendirilmesinden" in (h or "") for h in hints)


def test_common_words_are_known() -> None:
    text = (
        "Şebekeye su verilirken kısa süreli bulanık su akabilir. Grip bulaşır. Etkili bir ilaç "
        "aldım. Kuvvetli rüzgâr var. Kargo geldi. Bu şart. Atmosfer ve gezegen. Diplomatlar "
        "protesto edildi. Temel bilgiler. Palamut, sincap ve kovuk. Tepki verdi. Okur bilir."
    )
    rare = {h.text.lower() for h in rule_hits(text, "KD-K06")}
    assert rare <= {"şebekeye"}, rare


def test_negation_one_finding_per_sentence_with_fitting_hint() -> None:
    hits = rule_hits("Hiçbir zaman gelmeyecek değil.", "KD-C04")
    assert len(hits) == 1
    hint = rule_hits("Bu hizmet ücretli değil.", "KD-C04")[0].suggestion or ""
    assert "ücretsiz" in hint
    hint = rule_hits("Suyu boşa harcamayın.", "KD-C04")[0].suggestion or ""
    assert "az kullanın" in hint


def test_bureaucratic_phrase_is_not_counted_three_times() -> None:
    fired = [f.rule_id for f in analyze("Gerekli önlemleri almanız rica olunur.").findings
             if "olunur" in f.text]
    assert "KD-C03" not in fired and "KD-K01" in fired


def test_simple_texts_score_reasonably() -> None:
    masal = (
        "Bir varmış, bir yokmuş. Eski zamanlarda, küçük bir köyde tatlı bir kız yaşarmış. "
        "Herkes ona Kırmızı Başlıklı Kız dermiş. Bir gün annesi ona bir sepet vermiş. "
        "Sepette kurabiye ve bal varmış."
    )
    grip = (
        "Grip insandan insana kolayca bulaşır. Gripten korunmak için ellerinizi sık sık yıkayın. "
        "Kalabalık yerlerde maske takın. Hastaysanız evde dinlenin. Bol su için ve meyve yiyin."
    )
    assert analyze(masal).scores.compliance.value >= 80
    assert analyze(grip).scores.compliance.value >= 80
    bureaucratic = (
        "Belediyemiz tarafından tahsis edilecek olan sosyal yardım ödeneklerinden faydalanmak "
        "isteyen ihtiyaç sahibi vatandaşlarımızın müracaatlarını ivedilikle yapmaları "
        "gerekmektedir. Bilgilerinize sunulur. Kamuoyuna saygıyla duyurulur."
    )
    assert analyze(bureaucratic).scores.compliance.value <= 20


@pytest.mark.skipif(sys.platform != "win32", reason="Windows'a özgü")
def test_directory_on_windows_is_not_permission_error(tmp_path: Path) -> None:
    with pytest.raises(ReaderError) as exc:
        read_file(str(tmp_path))
    assert "izin" not in str(exc.value)
