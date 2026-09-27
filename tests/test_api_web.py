"""Web API testleri (FastAPI TestClient)."""

from __future__ import annotations

import io

import docx
import pytest
from fastapi.testclient import TestClient

from kolaymetin.web.app import app, rehber_page, render_markdown

client = TestClient(app)
TEXT = "Müracaatlarınızı ivedilikle yapın. Başvurular alınacaktır."


def test_index_and_static() -> None:
    r = client.get("/")
    assert r.status_code == 200 and "kolaymetin" in r.text
    assert "Content-Security-Policy" in r.headers
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    for path in ("/static/style.css", "/static/app.js", "/static/ikonlar.svg",
                 "/static/gorsel/bos-durum.png", "/static/desen/bayer4-08.png",
                 "/static/fonts/atkinson-hyperlegible-next-latin-ext-400-normal.woff2"):
        assert client.get(path).status_code == 200, path
    assert client.get("/stil-rehberi").status_code == 200


def test_every_page_carries_the_dortlu() -> None:
    """Sekme simgesi ve künye logosu her sayfada dörtlü; ana sayfada yükleme göstergesi de."""
    assert client.get("/static/isaret.svg").status_code == 200
    for path in ("/", "/stil-rehberi", "/rehber", "/rehber/KD-C01"):
        html = client.get(path).text
        assert '<link rel="icon" href="/static/isaret.svg"' in html, path
        kunye = html[html.index('class="kunye__ad"'):]
        assert kunye.index('<svg class="dortlu"') < kunye.index("kolaymetin</a>"), path
    index = client.get("/").text
    durum = index[index.index('id="yukleniyor"'):index.index('id="yukleniyor-metni"')]
    assert "dortlu--doner" in durum
    assert "dortlu--doner" in index[index.index('id="denetle"'):]


def test_health() -> None:
    body = client.get("/saglik").json()
    assert body["durum"] == "tamam" and body["surum"] == "1.0.0"


def test_analyze() -> None:
    r = client.post("/api/analyze", json={"text": TEXT, "profile": "kolay-dil"})
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] == "kolay-dil"
    ids = {f["rule_id"] for f in body["findings"]}
    assert {"KD-K01", "KD-C03"} <= ids
    assert r.headers["Cache-Control"] == "no-store"
    assert "tokens" not in body["sentences"][0]


def test_analyze_ignored_and_custom_lexicon() -> None:
    ignored = [{"rule_id": "KD-K01", "text": "ivedilikle"}]
    body = client.post("/api/analyze", json={"text": TEXT, "ignored": ignored}).json()
    texts = {f["text"] for f in body["findings"] if f["rule_id"] == "KD-K01"}
    assert "ivedilikle" not in texts and "Müracaatlarınızı" in texts
    lex = "jargon:\n  - {ifade: encümen, oneri: belediye kurulu}\n"
    body = client.post("/api/analyze", json={"text": "Encümen karar verdi.", "custom_lexicon": lex}).json()
    assert any(f["rule_id"] == "KD-K01" for f in body["findings"])
    body = client.post("/api/analyze", json={"text": "Encümen.", "custom_lexicon": {"bilinen": ["encümen"]}}).json()
    assert body["findings"] == [] or all(f["rule_id"] != "KD-K06" for f in body["findings"])


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"text": "Su.", "profile": "../../etc/passwd"}, 422),
        ({"text": "x" * 100_001}, 413),
        ({"text": "Su.", "custom_lexicon": "jargon: [}"}, 422),
        ({"text": "Su.", "custom_lexicon": "- liste"}, 422),
        ({"text": "Su.", "custom_lexicon": {"tanimsiz": []}}, 422),
    ],
)
def test_analyze_errors(payload: dict, status: int) -> None:
    r = client.post("/api/analyze", json=payload)
    assert r.status_code == status
    assert isinstance(r.json()["detail"], str)


def test_too_long_message_is_turkish() -> None:
    r = client.post("/api/analyze", json={"text": "x" * 100_001})
    assert "100.000" in r.json()["detail"] and "karakter" in r.json()["detail"]


@pytest.mark.parametrize("fmt", ["json", "md", "html"])
def test_export(fmt: str) -> None:
    r = client.post("/api/export", json={"text": TEXT, "format": fmt})
    assert r.status_code == 200
    assert f"kolaymetin-rapor.{fmt}" in r.headers["content-disposition"]
    assert len(r.content) > 100


def test_upload_txt_docx_and_errors() -> None:
    r = client.post("/api/upload", files={"file": ("duyuru.txt", "Su kesilecek.".encode("cp1254"), "text/plain")})
    assert r.status_code == 200 and r.json()["text"] == "Su kesilecek."
    buf = io.BytesIO()
    d = docx.Document()
    d.add_paragraph("Başvurular alınacaktır.")
    d.save(buf)
    r = client.post("/api/upload", files={"file": ("d.docx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 200 and "alınacaktır" in r.json()["text"]
    r = client.post("/api/upload", files={"file": ("resim.png", b"\x89PNG", "image/png")})
    assert r.status_code == 422 and "desteklenmiyor" in r.json()["detail"]


def test_rules_profiles_samples() -> None:
    rules = client.get("/api/rules").json()
    assert len(rules) == 32
    assert rules[0]["profiles"]["kolay-dil"]["params"]["warn_above"] == 10
    profiles = client.get("/api/profiles").json()
    assert {p["name"] for p in profiles} == {"kolay-dil", "sade-dil"}
    samples = client.get("/api/ornekler").json()
    assert len(samples) >= 5 and all(s["metin"] for s in samples)


def test_rehber_pages() -> None:
    r = client.get("/rehber")
    assert r.status_code == 200 and "Kolay Dil nedir?" in r.text
    assert "dither--kapak" in r.text  # kategori kapakları
    r = client.get("/rehber/KD-C01")
    assert r.status_code == 200 and "Uzun cümle" in r.text and 'aria-current="page"' in r.text
    assert client.get("/rehber/KD-C01.md").status_code == 200
    assert client.get("/rehber/yok-boyle-sayfa").status_code == 404
    assert client.get("/rehber/..%2Fsecret").status_code == 404


def test_markdown_links_rewritten() -> None:
    html = render_markdown("[Skorlar](skorlar.md) ve [KD](KD-C01.md#ornek)")
    assert 'href="/rehber/skorlar"' in html and 'href="/rehber/KD-C01#ornek"' in html
    assert rehber_page("bilinmeyen") is None


def test_validation_error_is_turkish() -> None:
    r = client.post("/api/analyze", json={"metin": "yanlış alan"})
    assert r.status_code == 422
    assert "Geçersiz istek" in r.json()["detail"]
