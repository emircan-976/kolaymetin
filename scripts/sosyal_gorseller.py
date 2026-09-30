"""Sosyal medya görsellerini üretir: profil fotoğrafı ve iki banner (X, LinkedIn).

README künyesiyle aynı baskı dili: krem kâğıt, siyah mürekkep, kırmızı ve mavi nokta renk,
fosforlu kalem; yazı tipleri gömülü, köşe yarıçapı ve gradyan yok. Yardımcılar (palet, dörtlü,
manzara, yazı ölçümü) readme_gorselleri.py'den gelir. Canlandırma yoktur: platformlar
durağan görsel ister.

Her görsel açık ve koyu temada SVG ve PNG olarak assets/sosyal/ altına yazılır. PNG'ler
Chromium'da, platformun istediği boyutta basılır.

Güvenli alanlar:
- Profil: platformlar daire kırpar; dörtlü iç dairenin içinde, bol boşlukla durur.
- X (1500×500): profil fotoğrafı sol alt köşeyi örter, mobil üst ve altı kırpar.
- LinkedIn (1584×396): profil fotoğrafı sol alt çeyreği örter.

Kullanım:
    python scripts/sosyal_gorseller.py [--kanal msedge]
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

import readme_gorselleri as rg
from readme_gorselleri import (
    boya,
    dortlu,
    font_face,
    kose_isaretleri,
    manzara,
    olc,
    ortak_stil,
    svg,
    t,
)

OUT = rg.ROOT / "assets" / "sosyal"
ETIKETLER = ["AÇIK KAYNAK", "TAMAMEN ÇEVRİMDIŞI", "32 KURAL"]


# ------------------------------------------------------------------ parçalar
def zemin(p: dict[str, str], g: int, y: int) -> list[str]:
    return [f'<rect width="{g}" height="{y}" fill="{p["kagit"]}"/>', kose_isaretleri(g, y, p["murekkep-soluk"])]


def logo(p: dict[str, str], x: float, taban: float, dp: int, genislik: float) -> tuple[str, float]:
    """Dörtlü + ad, künyedeki gibi aynı taban çizgisinde; ad kırmızı kalıbı 5 px kaymış basılır.

    genislik: logonun sığması gereken alan. Dönen değer (svg, adın yazı boyutu).
    """
    ax = x + 16 * dp + 22
    boyut = 124
    while olc("kolaymetin", "g800", boyut, -0.03 * boyut) > x + genislik - ax:
        boyut -= 1
    ls = -0.03 * boyut
    kayma = max(3, round(boyut / 25))
    parca = dortlu(p, x, taban - 16 * dp, dp) + (
        f'<g font-weight="800" font-size="{boyut}" letter-spacing="{ls:.2f}">'
        f'{t(ax + kayma, taban + kayma, "kolaymetin", "kirmizi")}{t(ax, taban, "kolaymetin", "")}</g>')
    return parca, boyut


def sahne(p: dict[str, str], sx: float, sy: float, gunes_y: float = 2) -> str:
    """Künye sahnesi (600×200): kırmızı güneş tepelerin ardında."""
    return (f'<clipPath id="sahne"><rect x="{sx}" y="{sy}" width="600" height="200"/></clipPath>'
            f'<g clip-path="url(#sahne)"><image x="{sx + 404}" y="{sy + gunes_y}" width="112" height="112" '
            f'href="{boya("kunye-gunes", p["kirmizi"])}" style="image-rendering:pixelated"/>'
            f'<image x="{sx}" y="{sy}" width="600" height="200" href="{manzara(p)}" '
            f'style="image-rendering:pixelated"/></g>')


def cift_cizgi(p: dict[str, str], y: float, g: int) -> str:
    return (f'<rect x="0" y="{y}" width="{g}" height="2" fill="{p["murekkep"]}"/>'
            f'<rect x="0" y="{y + 6}" width="{g}" height="2" fill="{p["murekkep"]}"/>')


def slogan(p: dict[str, str], orta: float, taban: float, sb: float) -> str:
    """"Kamu duyuruları herkes içindir." — "herkes" fosforlu kalemle."""
    on, vurgu, son = "Kamu duyuruları ", "herkes", " içindir."
    tam = olc(on + vurgu + son, "g800", sb, -0.5)
    x0 = orta - tam / 2
    vx = x0 + olc(on, "g800", sb, -0.5)
    vw = olc(vurgu, "g800", sb, -0.5)
    return (f'<rect x="{vx - 6:.1f}" y="{taban - sb * 0.72:.1f}" width="{vw + 12:.1f}" '
            f'height="{sb * 0.86:.1f}" fill="{p["sari"]}"/>'
            + t(x0, taban, on + vurgu + son, "", font_size=sb, font_weight=800, letter_spacing="-0.5"))


def etiketler(p: dict[str, str], orta: float, y: float, eb: int = 15) -> str:
    """Düz ofset gölgeli mono etiketler, orta noktaya göre ortalanır."""
    pad, ara = 14, 12
    gen = [olc(e, "m400", eb, 0.3) + 2 * pad for e in ETIKETLER]
    x = orta - (sum(gen) + ara * (len(gen) - 1)) / 2
    parca = []
    for e, ew in zip(ETIKETLER, gen, strict=True):
        parca.append(f'<rect x="{x + 3:.1f}" y="{y + 3}" width="{ew:.1f}" height="34" fill="{p["murekkep"]}"/>'
                     f'<rect x="{x:.1f}" y="{y}" width="{ew:.1f}" height="34" fill="{p["kagit"]}" '
                     f'stroke="{p["murekkep"]}" stroke-width="1.5"/>' + t(x + pad, y + 22, e, "m", font_size=eb))
        x += ew + ara
    return "".join(parca)


def ust_satir(p: dict[str, str], g: int, y: float, sol: str, sag: str) -> str:
    return (t(48, y, sol, "m soluk", font_size=15) + t(g - 48, y, sag, "m soluk", font_size=15, text_anchor="end")
            + f'<rect x="48" y="{y + 12}" width="{g - 96}" height="1" fill="{p["murekkep"]}"/>')


# ------------------------------------------------------------------ 1. profil fotoğrafı
def profil(p: dict[str, str]) -> str:
    """1080×1080. Daire kırpmada dörtlünün köşeleri merkezden 340 px uzakta (yarıçap 540)."""
    K = 1080
    dp = 30  # 16 × 30 = 480 px
    x = y = (K - 16 * dp) / 2
    return svg(K, K, "kolaymetin işareti: dörtlü", "",
               f'<rect width="{K}" height="{K}" fill="{p["kagit"]}"/>' + dortlu(p, x, y, dp))


# ------------------------------------------------------------------ 2. X / Twitter banner'ı
def banner_x(p: dict[str, str]) -> str:
    G, Y = 1500, 500
    stil = [ortak_stil(p), font_face(["g400", "g800", "m400"])]
    g = zemin(p, G, Y)
    g.append(ust_satir(p, G, 56, "TÜRKÇE KOLAY DİL · SADE DİL", "AÇIK KAYNAK DENETİM MASASI"))

    sx, sy = G - 48 - 600, 82
    parca, _ = logo(p, 64, 222, 6, sx - 64 - 40)
    g.append(parca)
    g.append(t(66, 274, "Kolay Dil denetim masası", "soluk", font_size=28))
    g.append(sahne(p, sx, sy))
    g.append(cift_cizgi(p, 296, G))

    # alt bant: sol alttaki profil fotoğrafından kaçmak için sağa kaydırılmış
    orta = (420 + G - 48) / 2
    g.append(slogan(p, orta, 382, 46))
    g.append(etiketler(p, orta, 414))
    return svg(G, Y, "kolaymetin — Kamu duyuruları herkes içindir.", "\n".join(stil), "\n".join(g))


# ------------------------------------------------------------------ 3. LinkedIn banner'ı
def banner_linkedin(p: dict[str, str]) -> str:
    G, Y = 1584, 396
    stil = [ortak_stil(p), font_face(["g400", "g800", "m400"])]
    g = zemin(p, G, Y)
    g.append(ust_satir(p, G, 50, "TÜRKÇE KOLAY DİL · SADE DİL", "AÇIK KAYNAK DENETİM MASASI"))

    # sol üst: logo; sol alt çeyrek profil fotoğrafına kalır
    sx, sy = G - 48 - 600, 72
    parca, _ = logo(p, 64, 196, 6, 560)
    g.append(parca)
    g.append(t(66, 246, "Kolay Dil denetim masası", "soluk", font_size=26))
    g.append(sahne(p, sx, sy))

    # sağ alt: slogan ve etiketler, sahnenin altında
    g.append(f'<rect x="{sx - 40}" y="272" width="{G - sx + 40}" height="2" fill="{p["murekkep"]}"/>'
             f'<rect x="{sx - 40}" y="278" width="{G - sx + 40}" height="2" fill="{p["murekkep"]}"/>')
    orta = sx + 300 - 20
    g.append(slogan(p, orta, 324, 32))
    g.append(etiketler(p, orta, 342, 13))
    return svg(G, Y, "kolaymetin — Kamu duyuruları herkes içindir.", "\n".join(stil), "\n".join(g))


# ------------------------------------------------------------------ çalıştır
GORSELLER: dict[str, tuple[Callable[[dict[str, str]], str], int, int]] = {
    "profil": (profil, 1080, 1080),
    "banner-x": (banner_x, 1500, 500),
    "banner-linkedin": (banner_linkedin, 1584, 396),
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Sosyal medya görselleri")
    ap.add_argument("--kanal", default=None, help="Tarayıcı kanalı (ör. msedge, chrome)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rg._olcer = olcer = rg.Olcer(args.kanal)
    try:
        for tema, p in rg.paletler().items():
            for ad, (uret, g, y) in GORSELLER.items():
                yol = OUT / f"{ad}-{tema}.svg"
                icerik = uret(p)
                yol.write_text(icerik, encoding="utf-8")
                sayfa = olcer._tarayici.new_page(viewport={"width": g, "height": y})
                sayfa.set_content(f"<style>html,body{{margin:0}}svg{{display:block}}</style>{icerik}")
                sayfa.evaluate("document.fonts.ready")
                sayfa.screenshot(path=str(yol.with_suffix(".png")))
                sayfa.close()
                print(f"{yol.relative_to(rg.ROOT)}  +  .png  ({g}×{y})")
    finally:
        olcer.kapat()


if __name__ == "__main__":
    main()
