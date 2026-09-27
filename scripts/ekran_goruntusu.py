"""Arayüzün ekran görüntülerini docs/ekran/ içine alır (Playwright).

Kullanım:
    pip install playwright && playwright install chromium
    python scripts/ekran_goruntusu.py [--kanal msedge]

Betik kendi yerel sunucusunu (127.0.0.1, rastgele port) açar; dış ağa çıkmaz.
Üretilen dosyalar: bos.png, dolu.png, koyu.png, mobil.png, gri-tonlu.png, rapor.png, rehber.png
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "ekran"
SAMPLE = (ROOT / "tests" / "corpus" / "su-kesintisi-burokratik" / "metin.txt").read_text(encoding="utf-8")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_server(port: int) -> None:
    import uvicorn

    from kolaymetin.web.app import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise SystemExit("Sunucu başlatılamadı.")


def _fill(page, text: str) -> None:  # type: ignore[no-untyped-def]
    page.fill("#metin", text)
    page.click("#denetle")
    page.wait_for_selector("#bulgular li", timeout=30_000)
    page.wait_for_timeout(300)
    page.evaluate("document.getElementById('metin').scrollTop = 0;"
                  "document.getElementById('metin').dispatchEvent(new Event('scroll'))")
    page.wait_for_timeout(100)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Arayüz ekran görüntüleri")
    ap.add_argument("--kanal", default=None, help="Tarayıcı kanalı (ör. msedge, chrome)")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    _start_server(port)
    base = f"http://127.0.0.1:{port}"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.kanal) if args.kanal else p.chromium.launch()
        external: list[str] = []
        errors: list[str] = []

        def console_error(msg):  # type: ignore[no-untyped-def]
            if msg.type == "error":
                errors.append(msg.text)

        def track(req):  # type: ignore[no-untyped-def]
            if not req.url.startswith(base) and not req.url.startswith(("data:", "blob:", "file:")):
                external.append(req.url)

        ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="light",
                                  reduced_motion="reduce", bypass_csp=True)
        page = ctx.new_page()
        page.on("request", track)
        page.on("console", console_error)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT / "bos.png"))
        _fill(page, SAMPLE)
        page.click("#bulgular li:nth-child(2) .not-kagidi__mesaj")
        page.click("#bulgular li:nth-child(2) .baglanti-dugme >> text=Metinde göster")
        page.evaluate("document.getElementById('metin').scrollTop = 0;"
                      "document.getElementById('metin').dispatchEvent(new Event('scroll'))")
        page.wait_for_timeout(200)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(100)
        page.screenshot(path=str(OUT / "dolu.png"))
        from PIL import Image

        Image.open(OUT / "dolu.png").convert("L").save(OUT / "gri-tonlu.png")
        ctx.close()

        ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="dark",
                                  reduced_motion="reduce", bypass_csp=True)
        page = ctx.new_page()
        page.on("request", track)
        page.on("console", console_error)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/")
        _fill(page, SAMPLE)
        page.click("#bulgular li:nth-child(2) .not-kagidi__mesaj")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(OUT / "koyu.png"))
        ctx.close()

        ctx = browser.new_context(viewport={"width": 375, "height": 812}, color_scheme="light",
                                  device_scale_factor=2, is_mobile=True, reduced_motion="reduce", bypass_csp=True)
        page = ctx.new_page()
        page.on("request", track)
        page.on("console", console_error)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/")
        _fill(page, SAMPLE)
        page.screenshot(path=str(OUT / "mobil.png"), full_page=False)
        page.screenshot(path=str(OUT / "mobil-tam.png"), full_page=True)
        ctx.close()

        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="light")
        page = ctx.new_page()
        page.on("request", track)
        page.on("console", console_error)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/rehber")
        page.screenshot(path=str(OUT / "rehber.png"))
        page.goto(base + "/stil-rehberi")
        page.screenshot(path=str(OUT / "stil-rehberi.png"), full_page=True)
        from kolaymetin import analyze

        html_path = OUT / "ornek-rapor.html"
        html_path.write_text(analyze(SAMPLE).to_html(), encoding="utf-8")
        page.goto(html_path.as_uri())
        page.screenshot(path=str(OUT / "rapor.png"))
        try:
            page.pdf(path=str(OUT / "ornek-rapor.pdf"), format="A4", print_background=True)
        except Exception as exc:  # yalnızca başsız (headless) Chromium PDF üretebilir
            print("PDF üretilemedi:", exc)
        html_path.unlink()
        ctx.close()
        browser.close()

    if errors:
        print("UYARI: tarayıcı hataları:", *errors, sep="\n  ")
        return 1
    if external:
        print("UYARI: dış istek yapıldı:", *sorted(set(external)), sep="\n  ")
        return 1
    print(f"Ekran görüntüleri yazıldı: {OUT}")
    print("Dış istek sayısı: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
