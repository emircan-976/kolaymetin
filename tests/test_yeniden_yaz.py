"""Dil modeliyle yeniden yazma (kolaymetin.rewrite, /api/yz, /api/yeniden-yaz).

Gerçek bir model çağrılmaz: OpenAI uyumlu sahte bir sunucu yerel bir portta çalışır.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from kolaymetin import rewrite
from kolaymetin.web.app import app

client = TestClient(app)
SENTENCE = "Müracaatların 01.12.2026 tarihinden itibaren Ankara'da ivedilikle yapılması gerekmektedir."


class _Fake(BaseHTTPRequestHandler):
    reply = ""
    status = 200
    seen: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Fake.seen.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization"),
                           "agent": self.headers.get("User-Agent")})
        self._send({"choices": [{"message": {"content": _Fake.reply}}]})

    def do_GET(self) -> None:
        _Fake.seen.append({"path": self.path, "agent": self.headers.get("User-Agent")})
        self._send({"data": [{"id": "deneme-model"}, {"id": "whisper-large-v3"}, {"id": "qwen/qwen3-32b"}]})

    def _send(self, payload: dict[str, Any]) -> None:
        if _Fake.status != 200:
            payload = {"error": {"message": "Bu model bu hesapta kapalı."}}
        data = json.dumps(payload).encode()
        self.send_response(_Fake.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_Fake]]:
    """Sunucunun kendi modeli (KOLAYMETIN_LLM_URL) olarak sahte sunucu."""
    server = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("KOLAYMETIN_LLM_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("KOLAYMETIN_LLM_MODEL", "deneme-model")
    monkeypatch.setenv("KOLAYMETIN_LLM_KEY", "gizli")
    monkeypatch.delenv("VERCEL", raising=False)
    _Fake.seen, _Fake.status = [], 200
    yield _Fake
    server.shutdown()


def test_facts_compare_dates_in_both_forms() -> None:
    assert rewrite.facts("01.12.2026 saat 14:30") == rewrite.facts("1 Aralık 2026 günü saat 14.30")
    assert "sayı:1250000" in rewrite.facts("1.250.000 lira")
    assert "adres:www.ornek.bel.tr" in rewrite.facts("Bilgi: www.ornek.bel.tr.")


def test_clean_reply() -> None:
    assert rewrite.clean_reply("<think>uzun düşünce</think>\n“Başvurun.”") == "Başvurun."
    assert rewrite.clean_reply("```\nÖneri: Başvurun.\n```") == "Başvurun."


def test_good_rewrite_is_applicable(fake_llm: type[_Fake]) -> None:
    fake_llm.reply = "Başvurular 1 Aralık 2026 Salı günü başlıyor. Ankara'da hemen başvurun."
    r = client.post("/api/yeniden-yaz", json={
        "sentence": SENTENCE, "problems": ["Uzun cümle"], "provider": "sunucu",
        "before": "Önceki.", "after": "Sonraki.",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["applicable"] is True and data["missing"] == [] and data["added"] == []
    assert data["text"] == fake_llm.reply and data["model"] == "deneme-model"
    assert data["after"]["findings"] < data["before"]["findings"]
    sent = fake_llm.seen[0]
    assert sent["path"] == "/v1/chat/completions" and sent["auth"] == "Bearer gizli"
    user = sent["body"]["messages"][1]["content"]
    assert SENTENCE in user and "Uzun cümle" in user and "Önceki cümle: Önceki." in user


def test_lost_or_invented_facts_block_apply(fake_llm: type[_Fake]) -> None:
    fake_llm.reply = "Başvurular 2 Aralık 2026 günü başlıyor. Hemen başvurun."
    data = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "sunucu"}).json()
    assert data["applicable"] is False
    assert "1 Aralık tarihi" in data["missing"] and "ankara" in " ".join(data["missing"])
    assert "2 Aralık tarihi" in data["added"]
    assert "Öneride şu bilgiler yok" in data["note"]


def test_provider_errors_are_turkish(fake_llm: type[_Fake]) -> None:
    fake_llm.status = 429
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "sunucu"})
    assert r.status_code == 429 and "kotası" in r.json()["detail"]
    fake_llm.status = 401
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "sunucu"})
    assert r.status_code == 502 and "anahtar" in r.json()["detail"]


def test_models_are_listed_and_requests_carry_a_user_agent(fake_llm: type[_Fake]) -> None:
    """Groq'un önündeki Cloudflare "Python-urllib" kimliğini 403 (1010) ile engelliyor."""
    data = client.post("/api/yz/modeller", json={"provider": "sunucu"}).json()
    assert data["models"] == ["deneme-model", "qwen/qwen3-32b"]  # ses modeli elendi
    assert data["suggested"] == "deneme-model"
    agent = fake_llm.seen[-1]["agent"] or ""
    assert agent.startswith("kolaymetin/") and "urllib" not in agent.lower()


def test_forbidden_shows_provider_message(fake_llm: type[_Fake]) -> None:
    fake_llm.status = 403
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "sunucu"})
    assert r.status_code == 502 and "Bu model bu hesapta kapalı." in r.json()["detail"]


def test_unknown_provider_and_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KOLAYMETIN_LLM_URL", raising=False)
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "http://10.0.0.1"})
    assert r.status_code == 400 and "Bilinmeyen" in r.json()["detail"]
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "gemini"})
    assert r.status_code == 400 and "anahtar" in r.json()["detail"]
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "sunucu"})
    assert r.status_code == 400 and "ayarlı değil" in r.json()["detail"]


def test_no_request_field_carries_an_address() -> None:
    """Çevrim içi sunucu kullanıcının verdiği adrese istek atmamalı (SSRF)."""
    from kolaymetin.web.app import RewriteRequest

    assert not {"url", "base_url", "address"} & set(RewriteRequest.model_fields)


def test_local_providers_hidden_on_public_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KOLAYMETIN_LLM_URL", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    ids = [p["id"] for p in client.get("/api/yz").json()["saglayicilar"]]
    assert {"ollama", "lmstudio", "gemini", "groq"} <= set(ids)
    monkeypatch.setenv("VERCEL", "1")
    data = client.get("/api/yz").json()
    assert data["cevrimici"] is True
    assert "ollama" not in [p["id"] for p in data["saglayicilar"]]
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "ollama"})
    assert r.status_code == 400 and "kendi bilgisayarınıza" in r.json()["detail"]


def test_local_model_down_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setitem(
        rewrite.PROVIDERS, "ollama",
        rewrite.Provider("ollama", "Ollama", "http://localhost:9/v1", "m", needs_key=False, local=True),
    )
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "ollama"})
    assert r.status_code == 502 and "ollama serve" in r.json()["detail"]
