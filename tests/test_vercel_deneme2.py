"""Vercel'deki sürümün ikinci denemesinde (2026-10-02) bulunan hataların regresyon testleri.

Denenenler: yoksayılan bulgularla indirilen rapor, rapor tarihi ve rehber bağlantıları,
okunabilirlik formüllerinin ölçek dışı değerleri, büyük harfli jargon, küçük harfle başlayan
cümle, Markdown ve HTML içeren metin, yanlış pozitif ve negatifler, paralel istekler, dosya adı.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import rule_hits
from kolaymetin import analyze
from kolaymetin.io.exporters import readable_date
from kolaymetin.web.app import RateLimiter, app, safe_filename

client = TestClient(app)
BUROKRATIK = (
    "Müracaatlarınızı ivedilikle yapınız. Başvurular tarafımızca alınacaktır. "
    "Evrakları muhtelif yerlere teslim ediniz."
)


# --------------------------------------------------------------- rapor güvenilirliği


def test_ignored_findings_are_reported_with_raw_score() -> None:
    full = analyze(BUROKRATIK)
    ignored = [{"rule_id": f.rule_id, "text": f.text} for f in full.findings[:3]]
    report = analyze(BUROKRATIK, ignored=ignored)
    c = report.scores.compliance
    assert c.ignored_count == len(report.ignored_findings) >= 3
    assert c.raw_value == full.scores.compliance.value
    assert c.value is not None and c.raw_value is not None and c.value > c.raw_value
    md = report.to_markdown()
    assert f"{c.ignored_count} bulgu yoksayıldı" in md
    assert f"Yoksaymadan skor: {c.raw_value} / 100" in md
    assert "## Yoksayılan bulgular" in md
    html = report.to_html()
    assert "Yoksayılan bulgular" in html and f"Yoksaymadan skor: {c.raw_value}" in html
    assert full.scores.compliance.ignored_count == 0
    assert "yoksayıldı" not in full.to_markdown()


def test_readability_scores_stay_on_scale() -> None:
    long_words = " ".join(["sorumluluklarımızdan"] * 60) + "."
    sc = analyze(long_words).scores
    assert sc.atesman.value == 0
    assert sc.cetinkaya_uzun.value == 0
    assert sc.cetinkaya_uzun.grade is None
    assert "ölçeğin altında" in sc.cetinkaya_uzun.level


def test_report_date_is_turkish_time_in_words() -> None:
    assert readable_date("2026-10-01T21:44:24+00:00") == "2 Ekim 2026 Cuma, 00.44"
    report = analyze("Su yarın kesilecek.")
    assert report.created_at.endswith("+03:00")
    assert "- **Tarih:** " + readable_date(report.created_at) in report.to_markdown()


def test_exported_report_links_to_full_rehber_url() -> None:
    r = client.post("/api/export", json={"text": BUROKRATIK, "format": "md"},
                    headers={"x-forwarded-proto": "https", "host": "kolaymetin.example"})
    assert "](https://kolaymetin.example/rehber/KD-" in r.text
    r = client.post("/api/export", json={"text": BUROKRATIK, "format": "html"},
                    headers={"x-forwarded-proto": "https", "host": "kolaymetin.example"})
    assert '<a href="https://kolaymetin.example/rehber/KD-' in r.text


# --------------------------------------------------------------- Türkçe metin işleme


def test_uppercase_dotless_i_jargon() -> None:
    assert rule_hits("İş TARAFINDAN yapılacak.", "KD-K01")


def test_lowercase_sentence_after_question_or_exclamation() -> None:
    assert [s.text for s in analyze("Su var mı? evet var.").sentences] == ["Su var mı?", "evet var."]
    assert [s.text for s in analyze("Dikkat! su kesilecek.").sentences] == ["Dikkat!", "su kesilecek."]
    assert len(analyze("Geliyor musun? diye sordu.").sentences) == 1
    assert len(analyze("Ne güzel! dedi.").sentences) == 1


def test_markdown_and_html_markup_is_not_checked() -> None:
    text = 'Bilgi için [bağlantıya](https://example.com/a) bakın. Resim <img src="x.png"> burada.'
    found = {(f.rule_id, f.text) for f in analyze(text).findings}
    assert not any(rid == "KD-C09" for rid, _ in found)
    assert not {"img", "src", "png"} & {t for _, t in found}


# --------------------------------------------------------------- kural doğruluğu


def test_false_positives() -> None:
    assert not rule_hits("Kapı açıldı.", "KD-K05")
    assert not rule_hits("Yarın su yok.", "KD-C04")
    assert not rule_hits("Su yok, elektrik yok.", "KD-C04")
    assert rule_hits("Evde hiç su yok.", "KD-C04")
    assert not rule_hits("Kemeraltı çarşısı açık.", "KD-K06")


def test_false_negatives() -> None:
    assert rule_hits("Okul yarın açılıyor.", "KD-C03")
    assert rule_hits("Meeting yarın saat 10'da.", "KD-K02")
    assert rule_hits("Formu doldurunuz.", "KD-K01")
    hit = rule_hits("Ödeme 1250000 lira.", "KD-B01")[0]
    assert "1.250.000" in hit.message


def test_long_number_without_unit_is_not_flagged() -> None:
    """Posta kodu, telefon ve kimlik numarası ayırıcısız yazılır."""
    assert not rule_hits("Posta kodu 06100.", "KD-B01")
    assert not rule_hits("Numaranız 12345678901 olarak kayıtlı.", "KD-B01")


# --------------------------------------------------------------- altyapı ve güvenlik


def test_rate_limiter() -> None:
    limiter = RateLimiter(3, window=60)
    assert [limiter.allow("a", now=t) for t in (0, 1, 2, 3)] == [True, True, True, False]
    assert limiter.allow("b", now=3)
    assert limiter.allow("a", now=61)
    assert RateLimiter(0).allow("a")


def test_rate_limit_answers_429_in_turkish() -> None:
    old = app.state.hiz_siniri
    app.state.hiz_siniri = RateLimiter(2)
    try:
        codes = [client.post("/api/analyze", json={"text": "Su var."}).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        r = client.post("/api/analyze", json={"text": "Su var."})
        assert "Çok fazla istek" in r.json()["detail"] and r.headers["retry-after"] == "60"
        assert client.get("/").status_code == 200  # sayfalar sınırlanmaz
    finally:
        app.state.hiz_siniri = old


def test_page_cannot_be_framed() -> None:
    r = client.get("/")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_uploaded_filename_is_sanitized() -> None:
    assert safe_filename("../../etc/passwd.txt") == "passwd.txt"
    assert safe_filename("<img src=x>.txt") == "img srcx.txt"
    assert safe_filename("..\\..\\a.md") == "a.md"
    assert safe_filename("<>.txt") == ".txt"
    r = client.post("/api/upload", files={"file": ("../../<img src=x>.txt", b"merhaba")})
    assert r.json()["dosya_adi"] == "img srcx.txt"
