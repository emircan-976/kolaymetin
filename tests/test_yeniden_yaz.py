"""Dil modeliyle yeniden yazma (kolaymetin.rewrite, /api/yz, /api/yeniden-yaz).

Gerçek bir model çağrılmaz: OpenAI uyumlu sahte bir sunucu yerel bir portta çalışır.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from kolaymetin import rewrite
from kolaymetin.web.app import app

# Abonelik araçları yalnızca localhost'tan açılan arayüzde çalışır (app.require_loopback).
client = TestClient(app, base_url="http://localhost")
SENTENCE = "Müracaatların 01.12.2026 tarihinden itibaren Ankara'da ivedilikle yapılması gerekmektedir."


class _Fake(BaseHTTPRequestHandler):
    reply = ""
    error = "Bu model bu hesapta kapalı."
    replies: ClassVar[list[str]] = []  # doluysa sırayla verilir (ilk yazım, onarım turları)
    statuses: ClassVar[list[int]] = []  # doluysa sırayla verilir, sonra status
    status = 200
    seen: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Fake.seen.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization"),
                           "agent": self.headers.get("User-Agent")})
        content = _Fake.replies.pop(0) if _Fake.replies else _Fake.reply
        self._send({"choices": [{"message": {"content": content}}]})

    def do_GET(self) -> None:
        _Fake.seen.append({"path": self.path, "agent": self.headers.get("User-Agent")})
        self._send({"data": [{"id": "deneme-model"}, {"id": "whisper-large-v3"}, {"id": "qwen/qwen3-32b"}]})

    def _send(self, payload: dict[str, Any]) -> None:
        status = _Fake.statuses.pop(0) if _Fake.statuses else _Fake.status
        if status != 200:
            payload = {"error": {"message": _Fake.error}}
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if status == 429:
            self.send_header("Retry-After", "7")
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
    _Fake.seen, _Fake.status, _Fake.replies, _Fake.statuses = [], 200, [], []
    _Fake.error = "Bu model bu hesapta kapalı."
    monkeypatch.setattr(rewrite, "MAX_QUOTA_WAIT", 0)  # 429'da beklemeden hata dönsün
    # Anlam denetimi her öneriye bir istek ekler; yanıt sırası onu bekleyen testlerde açılır.
    monkeypatch.setattr(rewrite, "MEANING_CHECK", False)
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
    assert r.headers["Retry-After"] == "7"  # tarayıcı bekleyip yeniden dener
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


# --------------------------------------------------------------------------- denetle ve onar

ORIGINAL = """SU KESİNTİSİ HAKKINDA DUYURU

Ana isale hattında meydana gelen arıza nedeniyle 15.09.2026 tarihinde saat 09.00 ile 17.00 arasında Çankaya'da su kesintisi yapılacaktır. Vatandaşlarımızın suyu önceden temin etmeleri rica olunur. Bilgi için 185 numaralı hattı arayabilirsiniz."""

FIRST = """Su kesintisi

15 Eylül 2026 günü Çankaya'da su kesilecek.
Su saat 9.00 ile saat 17.00 arasında akmayacak.
Ana su borusunda arıza meydana geldi.
Önceden kaplara su doldurun.
Bilgi için 185'i arayın."""


def test_repair_round_sends_only_problem_lines(fake_llm: type[_Fake]) -> None:
    """Modelin çıktısı yeniden denetlenir; kalan bulgular satır numarasıyla geri gönderilir ve
    model yalnızca o satırları yeniden yazar."""
    fake_llm.replies = [FIRST, "[2]\nBelediye 15 Eylül 2026 günü Çankaya'da suyu kesecek.\n"
                        "[3]\nSu saat 9.00'da gidecek.\nSu saat 17.00'de gelecek."]
    r = client.post("/api/kolay-dile-cevir", json={"text": ORIGINAL, "provider": "sunucu"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["calls"] >= 2
    repair = fake_llm.seen[1]["body"]["messages"][1]["content"]
    assert "[2] 15 Eylül 2026 Salı günü Çankaya'da su kesilecek." in repair  # günü araç ekledi
    assert "Sorunlu satırlar:" in repair and "'kesilecek': Bu cümlede işi kimin" in repair
    assert "'akmayacak'" not in repair  # olumsuz cümle (KD-C04) zorla olumluya çevrilmez
    assert "[4] Ana su borusunda arıza oldu." in repair  # "meydana geldi" araçta düzeldi
    assert "[4] Ana" not in repair.split("Sorunlu satırlar:")[1]
    assert "Su saat 17.00'de gelecek." in data["text"] and "akmayacak" not in data["text"]
    assert data["after"]["findings"] < data["before"]["findings"]


def test_repair_stops_when_clean(fake_llm: type[_Fake]) -> None:
    fake_llm.reply = "Başvurular 1 Aralık 2026 günü başlıyor.\nAnkara'da hemen başvurun."
    data = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "sunucu"}).json()
    assert data["calls"] == 1 and data["remaining"] == []
    assert data["text"] == "Başvurular 1 Aralık 2026 Salı günü başlıyor.\nAnkara'da hemen başvurun."


def test_worse_repair_is_not_chosen(fake_llm: type[_Fake]) -> None:
    fake_llm.replies = [FIRST, "[1]\nSU KESİNTİSİ HAKKINDA DUYURU YAPILMAKTADIR",
                        "[1]\nSU KESİNTİSİ HAKKINDA DUYURU YAPILMAKTADIR"]
    data = client.post("/api/kolay-dile-cevir", json={"text": ORIGINAL, "provider": "sunucu"}).json()
    assert data["text"].startswith("Su kesintisi\n")


def test_apply_repair_and_markdown() -> None:
    text = "Başlık\n\nBir.\nİki."
    assert rewrite.apply_repair(text, "[3]\nÜç.\nDört.\n[9]\nYok.") == "Başlık\n\nBir.\nÜç.\nDört."
    assert rewrite.apply_repair(text, "Açıklama yazdım.") == text
    assert rewrite._clean_text("## Başlık\n\n* **öğe**") == "Başlık\n\n- öğe"


def test_long_paragraph_is_split() -> None:
    text = "Başlık\n" + "\n".join(f"Cümle {i}." for i in range(1, 7)) + "\n- öğe"
    out = rewrite._split_paragraphs(text)
    assert out == "Başlık\nCümle 1.\nCümle 2.\nCümle 3.\nCümle 4.\n\nCümle 5.\nCümle 6.\n- öğe"


def test_text_prompt_example_passes_the_rules() -> None:
    """İstemdeki örnek çıktı kendi kurallarımızdan tam puan almalı."""
    prompt = rewrite.TEXT_PROMPT
    example = prompt[prompt.index("Örnek çıktı:") + 12 : prompt.index("Yalnızca Kolay Dil")].strip()
    cand = rewrite._evaluate(example, example, "kolay-dil")
    assert [f.rule_id for f in cand.report.findings] == []


def test_gpt_oss_gets_low_reasoning(fake_llm: type[_Fake], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOLAYMETIN_LLM_MODEL", "openai/gpt-oss-20b")
    fake_llm.reply = "Hemen başvurun."
    client.post("/api/yeniden-yaz", json={"sentence": "Müracaat ediniz.", "provider": "sunucu"})
    assert fake_llm.seen[0]["body"]["reasoning_effort"] == "low"


def test_translate_rejects_long_section() -> None:
    r = client.post("/api/kolay-dile-cevir",
                    json={"text": "a" * (rewrite.MAX_TEXT_CHARS + 1), "provider": "sunucu"})
    assert r.status_code == 422


def test_unpunctuated_sentences_are_not_headings() -> None:
    """Noktasız satır başlık sayılır ve denetlenmez; model noktayı unutursa araç koyar."""
    text = "Su kesintisi\n\nKesinti bilgisi\nBelediye yarın suyu kesecek\n- Kova\nSoru var mı?"
    assert rewrite._punctuate(text) == (
        "Su kesintisi\n\nKesinti bilgisi\nBelediye yarın suyu kesecek.\n- Kova\nSoru var mı?")


def test_daily_quota_is_named(fake_llm: type[_Fake]) -> None:
    """Groq'un günlük kotası saatler sonra açılır: tarayıcı beklemesin, kullanıcı bilsin."""
    fake_llm.status = 429
    fake_llm.error = ("Rate limit reached for model `openai/gpt-oss-120b` on tokens per day (TPD): "
                      "Limit 200000, Used 199970, Requested 3264.")
    r = client.post("/api/kolay-dile-cevir", json={"text": ORIGINAL, "provider": "sunucu"})
    assert r.status_code == 429 and "günlük ücretsiz kotası doldu" in r.json()["detail"]


def test_quota_during_repair_is_reported(fake_llm: type[_Fake], monkeypatch: pytest.MonkeyPatch) -> None:
    """Onarım turu kotaya takılırsa ilk öneri döner, ama kullanıcı onarılmadığını bilir."""
    real = rewrite.call_chat
    calls = []

    def flaky(*args: Any) -> str:
        calls.append(1)
        if len(calls) > 1:
            raise rewrite.RewriteError("Bu modelin günlük ücretsiz kotası doldu.", 429)
        return real(*args)

    monkeypatch.setattr(rewrite, "call_chat", flaky)
    fake_llm.reply = FIRST
    data = client.post("/api/kolay-dile-cevir", json={"text": ORIGINAL, "provider": "sunucu"}).json()
    assert data["text"].startswith("Su kesintisi") and data["calls"] == 1
    assert "onarılamadı" in data["note"] and "günlük" in data["note"]


def test_busy_provider_is_retried(fake_llm: type[_Fake], monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini yoğunken 503 verir: kısa beklemeyle yinelenir, geçmezse Türkçe ileti döner."""
    waits: list[float] = []
    monkeypatch.setattr(rewrite, "MAX_QUOTA_WAIT", 40)
    monkeypatch.setattr(rewrite.time, "sleep", waits.append)
    fake_llm.statuses = [503]
    fake_llm.reply = "Başvurular 1 Aralık 2026 günü başlıyor. Ankara'da hemen başvurun."
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "sunucu"})
    assert r.status_code == 200 and waits == [5]
    fake_llm.seen, waits[:] = [], []
    fake_llm.status = 503
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "sunucu"})
    assert r.status_code == 503 and "yoğun" in r.json()["detail"]
    assert len(fake_llm.seen) == 1 + rewrite.BUSY_RETRIES and waits == [5, 10]


def test_closed_model_shows_provider_hint(fake_llm: type[_Fake]) -> None:
    """Gemini kapattığı modeli listede gösterir; iletisindeki yeni model adı kullanıcıya ulaşmalı."""
    fake_llm.status = 404
    fake_llm.error = "This model models/gemini-2.5-flash is no longer available to new users."
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "sunucu"})
    assert "kapatılmış" in r.json()["detail"] and "no longer available" in r.json()["detail"]


def test_suffixed_name_counts_as_kept() -> None:
    """Kesme işaretsiz ekli ad başka bir ekle geçince "eksik bilgi" sayılmamalı."""
    original = "Bu belge Afet ve Acil Durum Yönetimi Genel Müdürlüğünden alınmıştır."
    assert rewrite.fact_diff(original, "Bu belgeyi Afet ve Acil Durum Yönetimi Genel Müdürlüğü verdi.")[0] == []
    assert rewrite.fact_diff(original, "Bu belgeyi Afet ve Acil Durum Yönetimi Müdürlüğü verdi.")[0] == ["ad:genel"]


def test_openrouter_limits_are_told_apart(fake_llm: type[_Fake]) -> None:
    """OpenRouter'da günlük ücretsiz sınır ile meşgul model farklı şeyler; kullanıcı ayırt etmeli."""
    fake_llm.status = 429
    fake_llm.error = "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day"
    detail = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "sunucu"}).json()["detail"]
    assert "günlük ücretsiz istek sınırı" in detail and "50" in detail
    fake_llm.error = "google/gemma-4-31b-it:free is temporarily rate-limited upstream. Please retry shortly."
    detail = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "sunucu"}).json()["detail"]
    assert "çok yoğun" in detail and "başka bir model" in detail



# --------------------------------------------------------------------------- anlam denetimi

CLEAN = """Su kesintisi

15 Eylül 2026 günü Çankaya'da su kesilecek.
Su saat 9.00 ile saat 17.00 arasında akmayacak.
Ana su borusunda arıza oldu.
Önceden kaplara su doldurun.
Bilgi için 185'i arayın."""


def test_meaning_issue_goes_to_repair_first(fake_llm: type[_Fake], monkeypatch: pytest.MonkeyPatch) -> None:
    """Kural bulgusu anlamı ölçmez: "nedeniyle" bağı kopunca arıza ile kesinti ilişkisiz iki
    bilgi olur ama skor düşmez. Anlam denetimi bunu bulur, onarım isteğine ilk sırada girer."""
    monkeypatch.setattr(rewrite, "MEANING_CHECK", True)
    fake_llm.replies = [
        CLEAN,
        "[4] Kopuk bağ: kesintinin nedeni arıza. Doğrusu: arıza yüzünden su kesilecek.",
        "[4]\nAna su borusunda arıza oldu.\nBu yüzden suyu keseceğiz.",
        "TAMAM",
    ]
    data = client.post("/api/kolay-dile-cevir", json={"text": ORIGINAL, "provider": "sunucu"}).json()
    check = fake_llm.seen[1]["body"]["messages"]
    assert check[0]["content"] == rewrite.MEANING_PROMPT
    # Özgün metin aracın düzeltmeleriyle gider: araç ekledi diye "Salı" uydurma sayılmasın.
    assert "15 Eylül 2026 Salı" in check[1]["content"] and "15.09.2026" not in check[1]["content"]
    assert "[4] Ana su borusunda arıza oldu." in check[1]["content"]
    repair = fake_llm.seen[2]["body"]["messages"][1]["content"].split("Sorunlu satırlar:")[1]
    assert "[4] Ana su borusunda arıza oldu.\n- Anlam: Kopuk bağ" in repair
    assert "Bu yüzden suyu keseceğiz." in data["text"]
    assert data["meaning"] == [] and "Anlam" not in data["note"]


def test_repair_that_breaks_meaning_is_not_chosen(fake_llm: type[_Fake], monkeypatch: pytest.MonkeyPatch) -> None:
    """Onarım bulguyu azaltsa da anlamı bozuyorsa önceki öneri kalır."""
    monkeypatch.setattr(rewrite, "MEANING_CHECK", True)
    monkeypatch.setattr(rewrite, "REPAIR_ROUNDS", 2)
    broken = "[2]\nBelediye 15 Eylül 2026 günü Çankaya'da suyu kesecek."
    complaint = "[2] Yanlış bilgi: suyu kimin kestiği özgün metinde yok."
    fake_llm.replies = [CLEAN, "TAMAM", broken, complaint, broken, complaint]
    data = client.post("/api/kolay-dile-cevir", json={"text": ORIGINAL, "provider": "sunucu"}).json()
    assert "Çankaya'da su kesilecek." in data["text"] and "Belediye" not in data["text"]
    assert data["meaning"] == []


def test_remaining_meaning_issue_is_shown(fake_llm: type[_Fake], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rewrite, "MEANING_CHECK", True)
    monkeypatch.setattr(rewrite, "REPAIR_ROUNDS", 0)
    fake_llm.replies = [CLEAN, "[4] Kopuk bağ: kesintinin nedeni arıza."]
    data = client.post("/api/kolay-dile-cevir", json={"text": ORIGINAL, "provider": "sunucu"}).json()
    assert data["meaning"] == ["'Ana su borusunda arıza oldu.': Kopuk bağ: kesintinin nedeni arıza."]
    assert "Anlam denetimi şu sorunları buldu" in data["note"]


def test_meaning_check_failure_keeps_draft(fake_llm: type[_Fake], monkeypatch: pytest.MonkeyPatch) -> None:
    """Anlam denetimi kotaya takılırsa denetlenmemiş onarım yapılmaz; kullanıcı bunu bilir."""
    monkeypatch.setattr(rewrite, "MEANING_CHECK", True)
    real = rewrite.call_chat
    calls = []

    def flaky(*args: Any) -> str:
        calls.append(1)
        if len(calls) > 1:
            raise rewrite.RewriteError("Bu modelin günlük ücretsiz kotası doldu.", 429)
        return real(*args)

    monkeypatch.setattr(rewrite, "call_chat", flaky)
    fake_llm.reply = CLEAN
    data = client.post("/api/kolay-dile-cevir", json={"text": ORIGINAL, "provider": "sunucu"}).json()
    assert data["calls"] == 1 and len(calls) == 2
    assert "anlam bakımından denetlenemedi" in data["note"]


def test_parse_meaning() -> None:
    assert rewrite.parse_meaning("TAMAM", 3) == []
    assert rewrite.parse_meaning("Bence sorun yok.", 3) == []
    assert rewrite.parse_meaning("[2] Eksik bilgi.\n- [9] Uydurma.\n[0] Koşul yok.\n[2] Eksik bilgi.", 3) == [
        (2, "Eksik bilgi."), (0, "Uydurma."), (0, "Koşul yok.")]


def test_previous_section_is_sent_as_context(fake_llm: type[_Fake], monkeypatch: pytest.MonkeyPatch) -> None:
    """Bölümler ayrı çevrilir; önceki bölümün çevirisi olmadan gönderimler kopar."""
    monkeypatch.setattr(rewrite, "MAX_CONTEXT_CHARS", 30)
    fake_llm.reply = "Bu yüzden suyu keseceğiz."
    context = "Su kesintisi\n\nAna su borusunda arıza oldu."
    client.post("/api/kolay-dile-cevir", json={
        "text": "Bu nedenle su kesilecektir.", "first": False, "context": context, "provider": "sunucu"})
    user = fake_llm.seen[0]["body"]["messages"][1]["content"]
    assert "Önceki bölümün Kolay Dil çevirisi" in user
    assert "Ana su borusunda arıza oldu." in user and "Su kesintisi" not in user  # satır başından kesildi


def test_gemini_3_keeps_default_temperature(fake_llm: type[_Fake], monkeypatch: pytest.MonkeyPatch) -> None:
    """Google, Gemini 3 ve sonrasında sıcaklığın varsayılan 1.0 kalmasını öneriyor."""
    fake_llm.reply = "Hemen başvurun."
    monkeypatch.setenv("KOLAYMETIN_LLM_MODEL", "gemini-3.5-flash-lite")
    client.post("/api/yeniden-yaz", json={"sentence": "Müracaat ediniz.", "provider": "sunucu"})
    assert "temperature" not in fake_llm.seen[-1]["body"]
    monkeypatch.setenv("KOLAYMETIN_LLM_MODEL", "openai/gpt-oss-120b")
    client.post("/api/yeniden-yaz", json={"sentence": "Müracaat ediniz.", "provider": "sunucu"})
    assert fake_llm.seen[-1]["body"]["temperature"] == 0.2


def test_meaning_fix_is_kept_when_checker_finds_something_else(
    fake_llm: type[_Fake], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Canlı denemede: anlam sorunu ("bulanıklık" → "kum") onarılıyor, denetçi onarımda başka
    bir sorun buluyordu; sayı eşit kalınca eski öneri seçiliyor, düzeltme çöpe gidiyordu."""
    monkeypatch.setattr(rewrite, "MEANING_CHECK", True)
    original = ("Çalışmaların tamamlanmasını müteakip suyun verilmesine kademeli olarak başlanacak olup "
                "şebekede meydana gelebilecek bulanıklığın giderilmesi için musluklarınızın bir süre "
                "açık tutulması gerekmektedir.")
    fake_llm.replies = [
        "Çalışmalar bitecek.\nSonra suyu açacağız.\nBorularda kum çıkabilir.\nMusluğu açık tutun.",
        "[3] Bulanıklık kum olarak çevrilmiş. Doğrusu: Su bulanık akabilir.",
        "[3]\nSu bulanık akabilir.",
        "[4] Eksik bilgi: musluğu bir süre açık tutun.",
        "[4]\nBu yüzden musluğu bir süre açık tutun.",
        "TAMAM",
    ]
    data = client.post("/api/yeniden-yaz", json={"sentence": original, "provider": "sunucu"}).json()
    assert data["text"] == ("Çalışmalar bitecek.\nSonra suyu açacağız.\nSu bulanık akabilir.\n"
                            "Bu yüzden musluğu bir süre açık tutun.")
    assert data["meaning"] == []



# --------------------------------------------------------------------------- abonelik (CLI)

# Akış kipini (stream-json) konuşan sahte claude/agy: her mesajı ve süreç kimliğini günlüğe yazar,
# sıradaki yanıtı verir. "__ERR__…" hata sonucu, "__DIE__" süreç çöküşü.
_FAKE_CLI = r"""
import json, os, sys
mode, replies_path, log_path = sys.argv[1:4]
replies = json.load(open(replies_path, encoding="utf-8"))
for line in sys.stdin:
    msg = json.loads(line)
    content = msg["message"]["content"]
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"pid": os.getpid(), "content": content,
                             "api_key": os.environ.get("ANTHROPIC_API_KEY")}, ensure_ascii=False) + "\n")
    if content == "Yalnızca TAMAM yaz.":
        reply = "TAMAM"
    else:
        replies = json.load(open(replies_path, encoding="utf-8"))
        reply = replies.pop(0) if len(replies) > 1 else replies[0]
        json.dump(replies, open(replies_path, "w", encoding="utf-8"))
    if reply == "__DIE__":
        sys.stderr.write("çöktü\n")
        sys.exit(3)
    error = reply[7:] if reply.startswith("__ERR__") else None
    if mode == "claude":
        print(json.dumps({"type": "system", "subtype": "init"}))
        out = {"type": "result", "subtype": "success", "is_error": bool(error), "result": error or reply}
    else:
        out = {"event": "result", "result": {"status": "ERROR", "error": error} if error
               else {"status": "SUCCESS", "response": reply}}
    print(json.dumps(out, ensure_ascii=False), flush=True)
"""


class _FakeCli:
    def __init__(self, tmp_path: Any) -> None:
        self.script = tmp_path / "sahte_cli.py"
        self.script.write_text(_FAKE_CLI, encoding="utf-8")
        self.replies_path = tmp_path / "yanitlar.json"
        self.log_path = tmp_path / "gunluk.jsonl"
        self.args: list[list[str]] = []
        self.replies(["Hemen başvurun."])

    def replies(self, items: list[str]) -> None:
        self.replies_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    def session_args(self, cli: str, exe: str, model: str) -> list[str]:
        self.args.append(rewrite._REAL_SESSION_ARGS(cli, exe, model))
        return [sys.executable, str(self.script), cli, str(self.replies_path), str(self.log_path)]

    def log(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        return [json.loads(x) for x in self.log_path.read_text(encoding="utf-8").splitlines()]

    def work(self) -> list[dict[str, Any]]:
        return [x for x in self.log() if x["content"] != rewrite._WARMUP]


@pytest.fixture
def cli(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeCli]:
    fake = _FakeCli(tmp_path)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    monkeypatch.setattr(rewrite.shutil, "which", lambda name: f"C:/bin/{name}.exe")
    monkeypatch.setattr(rewrite, "_REAL_SESSION_ARGS", rewrite._session_args, raising=False)
    monkeypatch.setattr(rewrite, "_session_args", fake.session_args)
    monkeypatch.setattr(rewrite, "CLI_SPARES", 0)
    monkeypatch.setattr(rewrite, "CLI_TIMEOUT", 20)
    monkeypatch.setattr(rewrite, "MEANING_CHECK", False)
    monkeypatch.setattr(rewrite, "REPAIR_ROUNDS", 0)
    rewrite.close_pools()
    yield fake
    rewrite.close_pools()


def test_claude_subscription_runs_claude_code(cli: _FakeCli, monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude aboneliği: claude -p akış kipinde, araçlar kapalı. ANTHROPIC_API_KEY alt sürece
    geçmez: geçerse Claude Code abonelik yerine ücretli API'yi kullanır."""
    cli.replies(["Ankara'da hemen başvurun.\nBaşvurular 1 Aralık 2026 günü başlıyor."])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ücretli")
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "claude-abonelik",
                                              "model": "haiku"})
    assert r.status_code == 200, r.text
    assert "1 Aralık 2026 Salı günü" in r.json()["text"]
    args = cli.args[0]
    assert args[:2] == ["C:/bin/claude.exe", "-p"] and args[args.index("--tools") + 1] == ""
    assert args[args.index("--input-format") + 1] == "stream-json" and "--bare" not in args
    assert args[args.index("--model") + 1] == "haiku"
    work = cli.work()
    assert rewrite.SENTENCE_PROMPT in work[0]["content"] and SENTENCE in work[0]["content"]
    assert all(x["api_key"] is None for x in cli.log())


def test_one_job_one_conversation(cli: _FakeCli, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bir işin istekleri (ilk yazım, anlam denetimi, onarım) aynı süreçten geçer; sonraki iş yeni
    süreçte başlar, metinler birbirine karışmaz. İş bitince süreç kapanır."""
    monkeypatch.setattr(rewrite, "MEANING_CHECK", True)
    cli.replies(["Hemen başvurun.", "TAMAM"])
    for _ in range(2):
        r = client.post("/api/yeniden-yaz", json={"sentence": "Müracaat ediniz.", "provider": "claude-abonelik"})
        assert r.status_code == 200, r.text
    pids = [x["pid"] for x in cli.work()]
    assert len(pids) == 4 and pids[0] == pids[1] and pids[2] == pids[3] and pids[0] != pids[2]
    assert rewrite.MEANING_PROMPT in cli.work()[1]["content"]


def test_warm_spare_is_used(cli: _FakeCli, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isıtılmış yedek süreç hazır bekler; iş onu kullanır, yerine yenisi ısınır."""
    monkeypatch.setattr(rewrite, "CLI_SPARES", 1)
    rewrite.warm_cli("gemini-abonelik", "gemini-3.8-flash-low")
    deadline = time.monotonic() + 15
    while not cli.log() and time.monotonic() < deadline:
        time.sleep(0.05)
    warmed = cli.log()[0]["pid"]
    r = client.post("/api/yeniden-yaz", json={"sentence": "Müracaat ediniz.", "provider": "gemini-abonelik",
                                              "model": "gemini-3.8-flash-low"})
    assert r.status_code == 200, r.text
    assert cli.work()[0]["pid"] == warmed
    assert cli.work()[0]["content"].startswith(rewrite._AGY_PREFIX)
    args = cli.args[0]
    assert args[1] == "--print=" and args[args.index("--model") + 1] == "gemini-3.8-flash-low"


def test_subscription_errors_are_turkish(cli: _FakeCli) -> None:
    cli.replies(["__ERR__Claude AI usage limit reached|1760000000"])
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "claude-abonelik"})
    assert r.status_code == 429 and "kullanım sınırı" in r.json()["detail"]
    cli.replies(["__ERR__authentication required"])
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "gemini-abonelik"})
    assert r.status_code == 400 and "'agy'" in r.json()["detail"]
    cli.replies(["__DIE__"])  # çöken araç isteği asılı bırakmamalı
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "claude-abonelik"})
    assert r.status_code == 502 and "çöktü" in r.json()["detail"]


def test_missing_cli(cli: _FakeCli, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rewrite.shutil, "which", lambda name: None)
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "claude-abonelik"})
    assert r.status_code == 400 and "Claude Code bulunamadı" in r.json()["detail"]


def test_subscription_models_and_public_server(cli: _FakeCli, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rewrite, "warm_cli", lambda *a: None)
    data = client.post("/api/yz/modeller", json={"provider": "claude-abonelik"}).json()
    assert data == {"models": ["haiku", "sonnet", "opus"], "suggested": "sonnet"}
    listing = "Kullanılabilir modeller:\n  gemini-3.8-flash-medium   Hızlı\n  gemini-3.8-flash-low   Daha hızlı\n"
    monkeypatch.setattr(rewrite, "_run_cli", lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, ""))
    data = client.post("/api/yz/modeller", json={"provider": "gemini-abonelik"}).json()
    assert data == {"models": ["gemini-3.8-flash-low", "gemini-3.8-flash-medium"],
                    "suggested": "gemini-3.8-flash-low"}
    monkeypatch.setenv("VERCEL", "1")  # abonelik başkalarına sunulamaz: çevrim içi sürümde yok
    ids = [p["id"] for p in client.get("/api/yz").json()["saglayicilar"]]
    assert "claude-abonelik" not in ids and "gemini-abonelik" not in ids


def test_subscription_needs_loopback_host(cli: _FakeCli) -> None:
    """DNS yeniden bağlama: 127.0.0.1'e çözülen yabancı alan adı aboneliği kullanamaz."""
    for host in ("evil.example:8000", "192.168.1.5:8000"):
        r = client.post("/api/yeniden-yaz", headers={"host": host},
                        json={"sentence": SENTENCE, "provider": "claude-abonelik"})
        assert r.status_code == 403 and "localhost" in r.json()["detail"]
    for path in ("/api/yz/modeller", "/api/yz/isit"):
        r = client.post(path, headers={"host": "evil.example"}, json={"provider": "gemini-abonelik"})
        assert r.status_code == 403
    r = client.post("/api/yeniden-yaz", headers={"host": "[::1]:8000"},
                    json={"sentence": SENTENCE, "provider": "claude-abonelik"})
    assert r.status_code == 200


def test_cross_site_post_rejected() -> None:
    """CSRF: kullanıcının açtığı başka bir site yerel sunucuya istek atamaz."""
    body = {"text": "Su kesilecek."}
    for headers in ({"sec-fetch-site": "cross-site"}, {"sec-fetch-site": "same-site"},
                    {"origin": "https://evil.example"}, {"origin": "null"}):
        r = client.post("/api/analyze", headers=headers, json=body)
        assert r.status_code == 403, headers
    for headers in ({"sec-fetch-site": "same-origin"}, {"origin": "http://localhost"}, {}):
        assert client.post("/api/analyze", headers=headers, json=body).status_code == 200, headers
    assert client.get("/api/yz", headers={"sec-fetch-site": "cross-site"}).status_code == 200


@pytest.mark.parametrize("model", ["-p", "--dangerously-skip-permissions", "sonnet & calc", "a b", "x\ny"])
def test_cli_model_name_validated(cli: _FakeCli, model: str) -> None:
    r = client.post("/api/yeniden-yaz", json={"sentence": SENTENCE, "provider": "claude-abonelik", "model": model})
    assert r.status_code == 400 and "model" in r.json()["detail"]
