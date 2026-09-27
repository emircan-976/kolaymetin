"""Renk değişkenlerinin WCAG 2.2 kontrast denetimi.

style.css içindeki açık tema (:root) ve koyu tema (:root[data-theme="dark"]) renk
değişkenlerini okur, her metin/zemin çiftinin kontrast oranını WCAG formülüyle hesaplar.
Metin için 4.5:1, metin dışı öğeler (çizgi, ikon, odak halkası) için 3:1 altında kalan
çift varsa çıkış kodu 1 olur.

Kullanım:
    python scripts/kontrast_denetle.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "src" / "kolaymetin" / "web" / "static" / "style.css"

# (ön plan, zemin, gereken oran, açıklama)
PAIRS: list[tuple[str, str, float, str]] = [
    ("--murekkep", "--kagit", 4.5, "ana metin"),
    ("--murekkep", "--kagit-2", 4.5, "panel ve kart metni"),
    ("--murekkep-soluk", "--kagit", 4.5, "ikincil metin"),
    ("--murekkep-soluk", "--kagit-2", 4.5, "kartta ikincil metin"),
    ("--kagit", "--murekkep", 4.5, "birincil düğme metni"),
    ("--kirmizi", "--kagit", 4.5, "hata kimliği (metin)"),
    ("--kirmizi", "--kagit-2", 4.5, "kartta hata kimliği (metin)"),
    ("--mavi", "--kagit", 4.5, "bağlantı metni"),
    ("--mavi", "--kagit-2", 4.5, "kartta bağlantı metni"),
    ("--murekkep", "--sari", 4.5, "fosforlu kalem üzerindeki metin"),
    ("--kirmizi", "--kagit", 3.0, "hata alt çizgisi / şeridi"),
    ("--mavi", "--kagit", 3.0, "odak halkası / bilgi çizgisi"),
    ("--mavi", "--kagit-2", 3.0, "kart üzerinde odak halkası"),
    ("--murekkep", "--kagit", 3.0, "çerçeve ve çizgiler"),
    ("--murekkep-soluk", "--kagit", 3.0, "kesik bölücü çizgi"),
]

VAR_RE = re.compile(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\b")


def _block(css: str, selector_regex: str) -> dict[str, str]:
    m = re.search(selector_regex + r"\s*\{([^}]*)\}", css)
    if not m:
        raise SystemExit(f"Seçici bulunamadı: {selector_regex}")
    return dict(VAR_RE.findall(m.group(1)))


def themes(css: str) -> dict[str, dict[str, str]]:
    light = _block(css, r"(?m)^:root")
    dark = dict(light)
    dark.update(_block(css, r':root\[data-theme="dark"\]'))
    return {"açık": light, "koyu": dark}


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def check(css_text: str) -> list[str]:
    problems = []
    for theme, colors in themes(css_text).items():
        for fg, bg, need, what in PAIRS:
            if fg not in colors or bg not in colors:
                problems.append(f"[{theme}] {fg} ya da {bg} tanımlı değil")
                continue
            ratio = contrast(colors[fg], colors[bg])
            if ratio < need:
                problems.append(
                    f"[{theme}] {what}: {fg} {colors[fg]} / {bg} {colors[bg]} = {ratio:.2f}:1 "
                    f"(gereken {need}:1)"
                )
    return problems


def report(css_text: str) -> list[str]:
    lines = []
    for theme, colors in themes(css_text).items():
        for fg, bg, need, what in PAIRS:
            if fg in colors and bg in colors:
                ratio = contrast(colors[fg], colors[bg])
                mark = "tamam" if ratio >= need else "YETERSİZ"
                lines.append(f"{theme:5} {what:34} {ratio:5.2f}:1  (≥{need})  {mark}")
    return lines


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    for line in report(css):
        print(line)
    problems = check(css)
    if problems:
        print("\nKontrast sorunları:")
        for p in problems:
            print(" -", p)
        return 1
    print("\nBütün renk çiftleri WCAG 2.2 AA eşiklerini geçiyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
