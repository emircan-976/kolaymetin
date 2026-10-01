"""Vercel'deki sürümün tarayıcıda ve API üzerinden denenmesinde (2026-10-02) bulunan hataların
regresyon testleri.

Denenenler: emoji içeren metin, yalnızca noktalama, örnek ve dosya yükleme, 4,5 MB üstü ve
100.000 karakter üstü dosya, uzantısız dosya, geçersiz tarih, saat aralığı, Sade Dil profili,
satır satır yazılmış metin, bozuk JSON, bilinmeyen adresler.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import rule_hits
from kolaymetin import analyze
from kolaymetin.web.app import app

client = TestClient(app, follow_redirects=False)


# --------------------------------------------------------------- ofsetler


def test_offsets_are_utf16_when_text_has_emoji() -> None:
    """Python kod noktası, JavaScript UTF-16 sayar: emoji varsa işaretler kayıyordu."""
    text = "😀😀😀 Duyuru müdürlük tarafından yapılacaktır."
    report = client.post("/api/analyze", json={"text": text}).json()
    utf16 = text.encode("utf-16-le")
    hit = next(f for f in report["findings"] if f["text"] == "tarafından")
    assert utf16[hit["start"] * 2 : hit["end"] * 2].decode("utf-16-le") == "tarafından"
    sentence = report["sentences"][0]
    assert utf16[sentence["start"] * 2 : sentence["end"] * 2].decode("utf-16-le") == sentence["text"]


def test_offsets_unchanged_without_emoji() -> None:
    text = "Duyuru müdürlük tarafından yapılacaktır."
    report = client.post("/api/analyze", json={"text": text}).json()
    hit = next(f for f in report["findings"] if f["text"] == "tarafından")
    assert text[hit["start"] : hit["end"]] == "tarafından"


# --------------------------------------------------------------- skorlar


def test_text_without_sentences_has_no_compliance_score() -> None:
    """Yalnızca noktalama ya da emoji: formüller "hesaplanamadı" derken uyum 100 alıyordu."""
    c = analyze("!!! ... 😀").scores.compliance
    assert c.value is None
    assert all(cat.score is None for cat in c.by_category)
    assert c.note == "Metinde denetlenecek bir cümle yok. Skor hesaplanamadı."
    report = analyze("!!! ...")
    assert "— / 100" in report.to_markdown()
    assert "—" in report.to_html()


def test_score_title_follows_profile() -> None:
    sade = analyze("Su yarın kesilecek.", profile="sade-dil")
    assert "Sade Dil Uyum Skoru" in sade.to_markdown()
    assert "Sade Dil Uyum Skoru" in sade.to_html()
    assert "Kolay Dil Uyum Skoru" in analyze("Su yarın kesilecek.").to_markdown()


# --------------------------------------------------------------- kurallar


def test_invalid_date_suggestion_has_no_fixed_example_date() -> None:
    hit = rule_hits("Toplantı 32.13.2026 tarihinde yapılacak.", "KD-B04")[0]
    assert "gerçek bir tarih değil" in hit.message
    assert hit.suggestion is not None and "2026" not in hit.suggestion


def test_time_range_followed_by_saat_is_not_flagged() -> None:
    assert not rule_hits("Ofis 09.00-17.00 saatleri arasında açıktır.", "KD-B05")
    assert not rule_hits("Toplantı 14.30 saatinde başlar.", "KD-B05")
    assert rule_hits("Ofis 09.00-17.00 arasında açıktır.", "KD-B05")


# --------------------------------------------------------------- cümle bölme


def _sentences(text: str) -> list[str]:
    return [s.text for s in analyze(text).sentences if not s.is_heading]


def test_unpunctuated_lines_are_separate_sentences() -> None:
    """Kolay Dil'de her cümle çoğu zaman ayrı satıra, noktasız yazılır."""
    text = "Su kesilecek\nYarın sabah su gelmeyecek\nLütfen su biriktirin\nTeşekkür ederiz"
    assert _sentences(text) == [
        "Su kesilecek", "Yarın sabah su gelmeyecek", "Lütfen su biriktirin", "Teşekkür ederiz",
    ]
    assert _sentences("Su kesilecek\nLütfen su biriktirin.") == [
        "Su kesilecek", "Lütfen su biriktirin.",
    ]


def test_wrapped_lines_still_join() -> None:
    """Satır kaydırması: küçük harfle başlayan ya da bağlaçla biten satır cümleyi sürdürür."""
    assert len(_sentences("Yarın sabah su\nkesilecek. Lütfen su biriktirin.")) == 2
    assert len(_sentences("Yarın su kesilecek ve\nAli Bey bilgi verecek.")) == 1


# --------------------------------------------------------------- dosya yükleme


def test_upload_rejects_empty_extensionless_and_too_long() -> None:
    r = client.post("/api/upload", files={"file": ("a.txt", b"")})
    assert r.status_code == 422 and "metin yok" in r.json()["detail"]
    r = client.post("/api/upload", files={"file": ("a.txt", b" \n ")})
    assert r.status_code == 422
    r = client.post("/api/upload", files={"file": ("dosya", b"merhaba")})
    assert r.status_code == 422 and "desteklenmiyor" in r.json()["detail"]
    r = client.post("/api/upload", files={"file": ("a.txt", b"a" * 100_001)})
    assert r.status_code == 413 and "100.000" in r.json()["detail"]
    r = client.post("/api/upload", files={"file": ("a.txt", b"a " * (2 * 1024 * 1024 + 1))})
    assert r.status_code == 413 and "4 MB" in r.json()["detail"]


# --------------------------------------------------------------- hatalar ve adresler


def test_broken_json_message_is_readable() -> None:
    r = client.post("/api/analyze", content=b"{bozuk", headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Geçersiz istek: gövde geçerli bir JSON değil."
    r = client.post("/api/analyze", content=b"[1]", headers={"content-type": "application/json"})
    assert r.json()["detail"] == "Geçersiz istek: gövde bir JSON nesnesi olmalı."


def test_unknown_urls_answer_in_turkish() -> None:
    page = client.get("/yok")
    assert page.status_code == 404 and "Bu sayfa yok" in page.text
    assert "Not Found" not in page.text
    api = client.get("/api/yok")
    assert api.status_code == 404 and api.json() == {"detail": "Bu adres yok."}
    assert client.get("/api/analyze").json()["detail"].startswith("Bu adrese bu yöntemle")


def test_robots_favicon_and_lowercase_rehber() -> None:
    assert client.get("/robots.txt").text.startswith("User-agent: *")
    assert client.get("/favicon.ico").headers["content-type"] == "image/svg+xml"
    r = client.get("/rehber/kd-c01")
    assert r.status_code == 308 and r.headers["location"] == "/rehber/KD-C01"
    assert client.get("/rehber/KD-C01").status_code == 200


def test_privacy_text_does_not_claim_local_only() -> None:
    page = client.get("/").text
    assert "bilgisayarınızdan çıkmaz" not in page
    assert "bu bilgisayarın belleğinde" not in page
    assert "sunucuya gönderilir" in page
