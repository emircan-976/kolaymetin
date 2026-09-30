"""Performans (5.000 kelime < 3 sn) ve ağ yalıtımı (hiçbir dış bağlantı yok)."""

from __future__ import annotations

import gc
import os
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from kolaymetin import analyze
from kolaymetin.text import morphology

CORPUS = Path(__file__).parent / "corpus"
# Kapsam ölçümü (coverage) ya da hata ayıklayıcı her satırı izler ve kodu birkaç kat yavaşlatır.
# Süre sınırı yalnızca izleme yokken 3 saniyedir. Yavaş bir CI makinesinde
# KOLAYMETIN_PERF_SINIR=5 gibi bir değerle genişletilebilir.
LIMIT = float(os.environ.get("KOLAYMETIN_PERF_SINIR", "0") or 0) or (
    3.0 if sys.gettrace() is None else 9.0
)


def _timed(run: Callable[[], object], cold: bool) -> float:
    """İki ölçümün en iyisi (timeit gibi). Ölçüm sırasında çöp toplayıcı durur: yüzlerce testten
    sonra biriken nesneler rastgele bir anda toplanıp süreyi şişirmesin. cold=True ise her
    ölçümden önce çözümleme önbellekleri boşaltılır; ikinci ölçüm de aynı işi yapar."""
    best = float("inf")
    for _ in range(2):
        if cold:
            morphology.clear_caches()
        gc.collect()
        gc.disable()
        try:
            start = time.perf_counter()
            run()
            best = min(best, time.perf_counter() - start)
        finally:
            gc.enable()
    return best


def _five_thousand_words() -> str:
    """Korpustaki bütün metinleri art arda ekleyerek ~5.000 kelimelik gerçekçi bir metin kurar."""
    texts = [(p / "metin.txt").read_text(encoding="utf-8") for p in sorted(CORPUS.iterdir())]
    out: list[str] = []
    words = 0
    i = 0
    while words < 5000:
        t = texts[i % len(texts)]
        out.append(t)
        words += len(t.split())
        i += 1
    return "\n\n".join(out)


@pytest.mark.yavas
def test_5000_words_under_3_seconds() -> None:
    text = _five_thousand_words()
    assert len(text.split()) >= 5000
    analyze(text[:2000])  # çözümleyici ve sözlük zaten yüklü; ısınma
    report = analyze(text)
    assert report.stats.word_count >= 4500
    elapsed = _timed(lambda: analyze(text), cold=True)
    assert elapsed < LIMIT, f"5.000 kelime {elapsed:.2f} sn sürdü"


@pytest.mark.yavas
def test_5000_unique_words_under_3_seconds() -> None:
    """Önbellekten yararlanamayan zor durum: kelimelerin çoğu farklı."""
    from kolaymetin.lexicon import load_lexicon

    vocab = sorted(load_lexicon().common_words)
    suffixes = ["", "ler", "de", "den", "in", "i", "e", "leri", "lerin", "imiz"]
    words: list[str] = []
    k = 0
    while len(words) < 5000:  # liste 5.000'den kısaysa aynı köke başka bir ek
        words += [w + suffixes[(i + k) % len(suffixes)] for i, w in enumerate(vocab)]
        words = list(dict.fromkeys(words))  # "kök + ek" başka bir köke denk gelebilir
        k += 1
    words = words[:5000]
    assert len(set(words)) == 5000
    text = " ".join(" ".join(words[i : i + 8]) + "." for i in range(0, 5000, 8))
    analyze("Isınma için kısa bir metin.")
    elapsed = _timed(lambda: analyze(text), cold=True)
    assert elapsed < LIMIT, f"5.000 farklı kelime {elapsed:.2f} sn sürdü"


LOCAL = {"127.0.0.1", "localhost", "::1", "0.0.0.0", None, ""}
_attempts: list[object] = []


def _guard_connect(original):  # type: ignore[no-untyped-def]
    def connect(self, address):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOCAL:
            _attempts.append(address)
            raise AssertionError(f"Dış ağ bağlantısı denendi: {address!r}")
        return original(self, address)

    return connect


def _guard_getaddrinfo(original):  # type: ignore[no-untyped-def]
    def getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host not in LOCAL:
            _attempts.append(host)
            raise AssertionError(f"DNS sorgusu denendi: {host!r}")
        return original(host, *args, **kwargs)

    return getaddrinfo


def test_no_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dış bağlantıları ve DNS sorgularını engelleyerek bütün işlem hattını çalıştırır."""
    monkeypatch.setattr(socket.socket, "connect", _guard_connect(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", _guard_connect(socket.socket.connect_ex))
    monkeypatch.setattr(socket, "getaddrinfo", _guard_getaddrinfo(socket.getaddrinfo))
    _attempts.clear()
    text = (CORPUS / "asi-duyurusu-burokratik" / "metin.txt").read_text(encoding="utf-8")
    report = analyze(text, profile="sade-dil")
    report.to_html()
    report.to_markdown()
    from fastapi.testclient import TestClient

    from kolaymetin.web.app import app

    client = TestClient(app)
    assert client.post("/api/analyze", json={"text": text}).status_code == 200
    assert client.get("/rehber/KD-C03").status_code == 200
    assert client.get("/").status_code == 200
    assert _attempts == []
