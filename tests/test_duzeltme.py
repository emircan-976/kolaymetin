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
from kolaymetin.text.inflect import inflect_like
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
        "Başvuruların 1 Aralık 2026 Salı tarihinden itibaren yapılması gerekmektedir. Toplantı "
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


# --------------------------------------------------------------------------- kelime düzeltmeleri


@pytest.mark.parametrize(
    ("new", "old", "lemma", "expected"),
    [
        ("başvuru", "müracaatlarınızı", "müracaat", "başvurularınızı"),
        ("başvuru", "müracaatın", "müracaat", "başvurunun"),  # "senin …" okunuşu atılır
        ("başvuru", "müracaatına", "müracaat", "başvurusuna"),
        ("konu", "hususta", "husus", "konuda"),
        ("etkinlik", "aktiviteye", "aktivite", "etkinliğe"),  # yumuşama zeyrek'le doğrulanır
        ("işlem", "prosedürlerden", "prosedür", "işlemlerden"),
        ("vergi ödeyen kişi", "mükelleflerin", "mükellef", "vergi ödeyen kişilerin"),
        ("başvurmak", "ediniz", "etmek", "başvurun"),  # resmî emir kısa emre döner
        ("başvurmak", "etmeyiniz", "etmek", "başvurmayın"),
        ("bildirmek", "edildi", "etmek", "bildirildi"),
        ("bildirmek", "edilecektir", "etmek", "bildirilecektir"),
        ("başvurmak", "ederiz", "etmek", "başvururuz"),
        ("başvurmak", "ediyoruz", "etmek", "başvuruyoruz"),
        ("başvurmak", "edecekler", "etmek", "başvuracaklar"),
        ("göstermek", "edebilirsiniz", "etmek", "gösterebilirsiniz"),
    ],
)
def test_inflect_like(new: str, old: str, lemma: str, expected: str) -> None:
    assert inflect_like(new, old, lemma) == expected


def test_inflect_like_refuses_unsure_forms() -> None:
    # "Valilik koordinasyonunda": iyelik çok kelimeli karşılığın son kelimesine bağlanmaz.
    assert inflect_like("birlikte çalışma", "koordinasyonunda", "koordinasyon") is None
    # Türetme eki ("müracaatçı") üreteçte yok: doğrulanamayan biçim yazılmaz.
    assert inflect_like("başvuru", "müracaatçılar", "müracaat") is None


@pytest.mark.parametrize(
    ("text", "rule_id", "expected"),
    [
        ("Müracaatlarınızı hemen yapın.", "KD-K01", ("Müracaatlarınızı", "Başvurularınızı")),
        ("Lütfen müracaat ediniz.", "KD-K01", ("müracaat ediniz", "başvurun")),
        ("Karar size tebliğ edildi.", "KD-K01", ("tebliğ edildi", "bildirildi")),
        ("Kurallara riayet edilmesi gerekir.", "KD-K01", ("riayet edilmesi", "uyulması")),
        ("Formu doldurunuz.", "KD-K01", ("doldurunuz", "doldurun")),
        ("Bu iş ivedilikle yapılır.", "KD-K01", ("ivedilikle", "hemen")),  # ilk seçenek
        ("Aktivitelere gelin.", "KD-K02", ("Aktivitelere", "Etkinliklere")),
        ("SGK ile görüşün.", "KD-K03", ("SGK", "Sosyal Güvenlik Kurumu (SGK)")),
        ("Kimlik, fatura vb. getirin.", "KD-K03", ("vb.", "ve benzeri")),
        ("Kimlik, fatura vb.", "KD-K03", ("vb", "ve benzeri")),
        ("Dokümanları getirin. Belgeleri getirin. Belgeyi verin.", "KD-K08",
         ("Dokümanları", "Belgeleri")),
    ],
)
def test_word_rule_fix(text: str, rule_id: str, expected: tuple[str, str]) -> None:
    assert expected in fixes(text, rule_id)


@pytest.mark.parametrize(
    ("text", "rule_id"),
    [
        ("Çalışmaların tamamlanmasını müteakip su verilecek.", "KD-K01"),  # duzeltme: yok
        ("Plan revize edildi.", "KD-K02"),  # yardımcı fiil de değişmeli
        ("Halkımızın bilgisine sunulur.", "KD-K01"),  # girdinin başka bir çekimi
        ("MÜRACAATLARI ALINACAK.", "KD-K01"),  # büyük harfi KD-B07 düzeltir
        ("SGK'ya gidin.", "KD-K03"),  # ek açılıma uyumla bağlanmalı
        ("Valilik koordinasyonunda çalışılacak.", "KD-K02"),
    ],
)
def test_no_word_fix_when_unsure(text: str, rule_id: str) -> None:
    assert fixes(text, rule_id) == []


# --------------------------------------------------------------------------- cümle düzeltmeleri


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # cümle bölme
        ("Su kesilecek ve elektrik de iki gün verilmeyecek.",
         "Su kesilecek. Elektrik de iki gün verilmeyecek."),
        ("Tahliye işlemleri valilik koordinasyonunda gerçekleştirilecek olup toplanma alanları "
         "duyurulacak.",
         "Boşaltma işlemleri valilik koordinasyonunda gerçekleştirilecek. Toplanma alanları "
         "duyurulacak."),
        ("Yağış bekleniyor, dere kenarına yaklaşmayın.", "Yağış bekleniyor. Dere kenarına yaklaşmayın."),
        # dolaylı seslenme → emir
        ("Formların doldurulması gerekmektedir.", "Formları doldurun."),
        ("Belgelerin teslim edilmesi gerekmektedir.", "Belgeleri teslim edin."),
        ("Acil durumlarda 112 Acil Çağrı Merkezi'nin aranması gerekmektedir.",
         "Acil durumlarda 112 Acil Çağrı Merkezi'ni arayın."),
        ("Vatandaşlarımızın suyu önceden temin etmeleri önemle rica olunur.",
         "Lütfen suyu önceden temin edin."),
        # resmî zaman ekleri
        ("Kuvvetli yağış beklenmektedir.", "Kuvvetli yağış bekleniyor."),
        ("Başvurular alınmayacaktır.", "Başvurular alınmayacak."),
        ("Liste oluşturulmuştur.", "Liste oluşturuldu."),
    ],
)
def test_sentence_fixes(text: str, expected: str) -> None:
    assert analyze(text).fixed_text() == expected


@pytest.mark.parametrize(
    "text",
    [
        "Kadın ve erkek seçmenler sandığa gidecek.",  # "kadın" yüklem değil
        "Kayıt yapılıp yapılmadığı bilinmiyor.",
        "Başvurunun kabul edilip edilmeyeceği yarın belli olacak.",
        "Engelli ve yaşlı seçmenlerimizin erken gelmeleri gerekmektedir.",  # özne niteleniyor
    ],
)
def test_sentence_left_alone(text: str) -> None:
    assert analyze(text).fixed_text() == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Edilgendeki olumsuzluk korunur: anlam tersine dönmez.
        ("Ürünün kullanılmaması gerekir.", "Ürünü kullanmayın."),
        ("Bu işlemin yapılmaması rica olunur.", "Lütfen bu işlemi yapmayın."),
        # Bağlanan edilgen ad-fiillerin ilgi hâli de nesne olur.
        ("Formların doldurulması ve belgelerin getirilmesi gerekmektedir.",
         "Formları doldurun ve belgeleri getirin."),
        # Okura seslenen özne düşer.
        ("Velilerimizin okula gelmesi gerekmektedir.", "Okula gelin."),
        # Okur olmayan özne okura çevrilmez; işi yapan yazıyorsa da düzeltme yok.
        ("Çocukların okula gitmesi gerekmektedir.", "Çocukların okula gitmesi gerekmektedir."),
        ("Belediyenin yol yapması gerekmektedir.", "Belediyenin yol yapması gerekmektedir."),
        ("Çocukların aileleri tarafından getirilmesi gerekir.",
         "Çocukların aileleri tarafından getirilmesi gerekir."),
        # Bağlamda yanlış karşılık verilen sözlük girdileri otomatik düzeltilmez.
        ("Müdür bizzat katılacaktır.", "Müdür bizzat katılacaktır."),
        ("Borç kısmen ödendi.", "Borç kısmen ödendi."),
        ("Hak sahibi kişiler başvurur.", "Hak sahibi kişiler başvurur."),
        ("Dr. Ali geldi.", "Doktor Ali geldi."),
        ("Başvurular 15.09 tarihinde başlar.", "Başvurular 15.09 tarihinde başlar."),
    ],
)
def test_fix_keeps_meaning(text: str, expected: str) -> None:
    assert analyze(text).fixed_text() == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Formların “yeni” doldurulması gerekmektedir.", "Formları “yeni” doldurun."),
        ("Formların – yeni – doldurulması gerekmektedir.", "Formları – yeni – doldurun."),
        ("Formların\r\ndoldurulması gerekmektedir.", "Formları\r\ndoldurun."),
        ("Okul kapandı;\r\nöğrenciler eve gitti.", "Okul kapandı.\r\nÖğrenciler eve gitti."),
        ("ÖNEMLİ – DUYURU “YARIN” OKULLAR KAPALI.", "Önemli – duyuru “yarın” okullar kapalı."),
        ("Belgelerinizi hazırlayın ve “eksiksiz” getirin.", "Belgelerinizi hazırlayın. “Eksiksiz” getirin."),
    ],
)
def test_multi_word_fix_keeps_original_characters(text: str, expected: str) -> None:
    """Birkaç kelimelik düzeltme normalleştirilmiş metinden kurulur; değişmeyen tırnak, tire ve
    satır sonları yazarın yazdığı gibi kalır."""
    assert analyze(text).fixed_text() == expected


def test_cli_duzelt_keeps_crlf(tmp_path: Path) -> None:
    source = tmp_path / "metin.txt"
    source.write_bytes("Formların\r\ndoldurulması gerekmektedir.\r\n".encode())
    target = tmp_path / "duzeltilmis.txt"
    out, err = io.StringIO(), io.StringIO()
    main(["denetle", str(source), "--duzelt", "-o", str(target)], out=out, err=err)
    assert b"\r\r\n" not in target.read_bytes() and b"\r\n" in target.read_bytes()


def test_long_single_sentence_is_fast() -> None:
    """Cümle bölme düzeltmesi cümle uzunluğuyla doğrusal büyür (önceden 60.000 karakter ~25 sn)."""
    import time

    text = " ".join(["Su kesilecek ve elektrik verilmeyecek"] * 1500) + "."
    t0 = time.perf_counter()
    analyze(text, max_chars=None)
    assert time.perf_counter() - t0 < 10


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("TÜRKİYE BÜYÜK MİLLET MECLİSİ YARIN TOPLANACAK.", "Türkiye Büyük Millet Meclisi yarın toplanacak."),
        ("BAŞVURUNUZU SOSYAL GÜVENLİK KURUMU'NA HEMEN YAPIN.", "Başvurunuzu Sosyal Güvenlik Kurumu'na hemen yapın."),
        ("DİLEKÇENİZİ TÜİK'E HEMEN GÖNDERİN LÜTFEN.", "Dilekçenizi TÜİK'e hemen gönderin lütfen."),
    ],
)
def test_all_caps_fix_keeps_institution_names(text: str, expected: str) -> None:
    assert analyze(text).fixed_text() == expected


@pytest.mark.parametrize(
    ("new", "old", "expected"),
    [
        # İnce uyumlu alıntı kelimeler: zeyrek yalnızca doğru biçimi kabul ediyor.
        ("saat", "müracaata", "saate"),
        ("dikkat", "müracaatı", "dikkati"),
        ("isim", "müracaatı", "ismi"),  # ünlü düşmesi
        # zeyrek iki biçimi de kabul ediyor ("kalbı"/"kalbi", "halı"/"hali", "kayıtı"/"kaydı"):
        # yanlışını yazmaktansa düzeltme verilmez.
        ("kalp", "müracaatı", None),
        ("hal", "müracaatı", None),
        ("kayıt", "müracaata", None),
    ],
)
def test_inflect_like_harmony_exceptions(new: str, old: str, expected: str | None) -> None:
    assert inflect_like(new, old, "müracaat") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("YARIN İÇ ANADOLU BÖLGESİNDE KAR YAĞACAK.", "Yarın İç Anadolu bölgesinde kar yağacak."),
        ("DOĞU KARADENİZ'DE YAĞMUR VAR BUGÜN.", "Doğu Karadeniz'de yağmur var bugün."),
        ("EVİN İÇ KISMI ÇOK SOĞUK OLDU.", "Evin iç kısmı çok soğuk oldu."),
    ],
)
def test_all_caps_fix_keeps_region_names(text: str, expected: str) -> None:
    assert analyze(text).fixed_text() == expected


def test_agy_runs_sandboxed() -> None:
    """Antigravity'de araçlar kapatılamıyor; terminal komutları --sandbox ile kısıtlanır."""
    from kolaymetin import rewrite

    assert "--sandbox" in rewrite._session_args("agy", "agy", "")
