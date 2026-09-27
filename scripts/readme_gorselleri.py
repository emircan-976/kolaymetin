"""README görsellerini üretir: künye, düzeltme provası, kural sayfası, ayırıcı ve kapanış künyesi.

Her görsel iki kez basılır: açık tema (krem kâğıt) ve koyu tema ("negatif baskı"). README bunları
<picture> ile GitHub temasına göre seçer. Renkler style.css içindeki :root ve
:root[data-theme="dark"] değişkenlerinden okunur; yazı tipleri (Atkinson Hyperlegible Next ve
Mono) SVG'nin içine gömülür, dış bağlantı yoktur. Dither görseller projedeki 1-bit PNG'lerden
boyanır; künyedeki tepeler manzara.js'nin çizdiği bir karedir (docs/readme/kaynak/manzara.png).

Canlandırmalar yalnızca CSS'tir. "Hareketi azalt" tercihinde canlandırma durur ve görsel son
hâlini (düzeltilmiş prova) gösterir.

Metin genişlikleri tarayıcıda ölçülür; Playwright gerekir (`pip install -e ".[dev,ekran]"`).

Kullanım:
    python scripts/readme_gorselleri.py [--kanal msedge]
"""

from __future__ import annotations

import argparse
import base64
import io
import re
from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "kolaymetin" / "web" / "static"
FONTS = STATIC / "fonts"
OUT = ROOT / "docs" / "readme"
MANZARA = OUT / "kaynak" / "manzara.png"

W = 1280
SURUM = "1.0.0"

# style.css ile aynı alt kümeler: ğ, ş, İ latin-ext dosyasında.
LATIN = ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, "
         "U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD")
LATIN_EXT = ("U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+1E00-1E9F, U+1EF2-1EFF, "
             "U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF")


# ------------------------------------------------------------------ renkler
def paletler() -> dict[str, dict[str, str]]:
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    var_re = re.compile(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\b")
    acik = css[css.index(":root {"):]
    acik = acik[: acik.index("}")]
    koyu = css[css.index(':root[data-theme="dark"] {'):]
    koyu = koyu[: koyu.index("}")]
    return {
        "acik": {k[2:]: v.upper() for k, v in var_re.findall(acik)},
        "koyu": {k[2:]: v.upper() for k, v in var_re.findall(koyu)},
    }


# ------------------------------------------------------------------ yazı tipleri
YAZI = {
    # anahtar: (aile, kalınlık, biçem, dosya kökü)
    "g400": ("Atkinson Hyperlegible Next", 400, "normal", "atkinson-hyperlegible-next-{}-400-normal"),
    "g400i": ("Atkinson Hyperlegible Next", 400, "italic", "atkinson-hyperlegible-next-{}-400-italic"),
    "g700": ("Atkinson Hyperlegible Next", 700, "normal", "atkinson-hyperlegible-next-{}-700-normal"),
    "g800": ("Atkinson Hyperlegible Next", 800, "normal", "atkinson-hyperlegible-next-{}-800-normal"),
    "m400": ("Atkinson Hyperlegible Mono", 400, "normal", "atkinson-hyperlegible-mono-{}-400-normal"),
    "m700": ("Atkinson Hyperlegible Mono", 700, "normal", "atkinson-hyperlegible-mono-{}-700-normal"),
}


def font_face(anahtarlar: list[str]) -> str:
    kurallar = []
    for a in anahtarlar:
        aile, agirlik, bicem, kok = YAZI[a]
        for alt, aralik in (("latin", LATIN), ("latin-ext", LATIN_EXT)):
            veri = base64.b64encode((FONTS / f"{kok.format(alt)}.woff2").read_bytes()).decode()
            kurallar.append(
                f'@font-face{{font-family:"{aile}";font-weight:{agirlik};font-style:{bicem};'
                f'src:url(data:font/woff2;base64,{veri}) format("woff2");unicode-range:{aralik}}}'
            )
    return "\n".join(kurallar)


class Olcer:
    """Metin genişliğini tarayıcıda ölçer: vurgu kutuları ve silme çizgileri kelimeye tam oturur.

    Pillow GPOS aralıklamasını (kerning) uygulamaz; bu yüzden ölçüm SVG'yi çizecek motorla,
    Chromium'un canvas measureText'iyle yapılır. letterSpacing, SVG'deki letter-spacing gibi
    her karakterin ardına eklenir.
    """

    def __init__(self, kanal: str | None) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._tarayici = self._pw.chromium.launch(channel=kanal) if kanal else self._pw.chromium.launch()
        self._sayfa = self._tarayici.new_page()
        self._sayfa.set_content(f"<style>{font_face(list(YAZI))}</style>")
        self._sayfa.evaluate("""async () => {
          await Promise.all([...document.fonts].map(f => f.load()));
          const c = document.createElement('canvas').getContext('2d');
          window.olc = (m, aile, agirlik, bicem, boyut, ls) => {
            c.font = `${bicem} ${agirlik} ${boyut}px "${aile}"`;
            c.letterSpacing = ls + 'px';
            return c.measureText(m).width;
          };
        }""")
        self._onbellek: dict[tuple[str, str, float, float], float] = {}

    def olc(self, metin: str, anahtar: str, boyut: float, harf_araligi: float) -> float:
        k = (metin, anahtar, boyut, harf_araligi)
        if k not in self._onbellek:
            aile, agirlik, bicem, _ = YAZI[anahtar]
            self._onbellek[k] = float(self._sayfa.evaluate(
                "a => olc(...a)", [metin, aile, agirlik, bicem, boyut, harf_araligi]))
        return self._onbellek[k]

    def kapat(self) -> None:
        self._tarayici.close()
        self._pw.stop()


_olcer: Olcer | None = None


def olc(metin: str, anahtar: str, boyut: float, harf_araligi: float = 0.0) -> float:
    """Metnin piksel genişliği (harf aralığı her karakterin ardına eklenir)."""
    assert _olcer is not None, "main() önce Olcer'i başlatır"
    return _olcer.olc(metin, anahtar, boyut, harf_araligi)


# ------------------------------------------------------------------ dither görseller
def png_uri(im: Image.Image) -> str:
    tampon = io.BytesIO()
    im.save(tampon, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode()


def hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def boya(ad: str, renk: str, carpan: int = 1) -> str:
    """1-bit maskeyi (siyah piksel, saydam zemin) tek renge boyar."""
    im = Image.open(STATIC / "gorsel" / f"{ad}.png").convert("RGBA")
    alfa = im.getchannel("A").point(lambda a: 255 if a > 127 else 0)
    sonuc = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sonuc.paste(Image.new("RGBA", im.size, (*hex_rgb(renk), 255)), mask=alfa)
    if carpan > 1:
        sonuc = sonuc.resize((im.width * carpan, im.height * carpan), Image.Resampling.NEAREST)
    return png_uri(sonuc)


def manzara(p: dict[str, str]) -> str:
    """manzara.js karesi: 0 gök (saydam), 1 kâğıt, 2 mavi kalıp, 3 mürekkep. 2× büyütülür."""
    kaynak = Image.open(MANZARA)
    renkler = {1: p["kagit"], 2: p["mavi"], 3: p["murekkep"]}
    im = Image.new("RGBA", kaynak.size, (0, 0, 0, 0))
    px = im.load()
    kp = kaynak.load()
    assert px is not None and kp is not None
    for y in range(kaynak.height):
        for x in range(kaynak.width):
            i = kp[x, y]
            if i in renkler:
                px[x, y] = (*hex_rgb(renkler[i]), 255)
    im = im.resize((kaynak.width * 2, kaynak.height * 2), Image.Resampling.NEAREST)
    return png_uri(im)


def bayer_deseni(desen_id: str, seviye: int, renk: str, piksel: int = 2) -> str:
    """Bayer 4×4 sıralı dither deseni (seviye 0–16), skor çubuklarındaki gibi."""
    m = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
    kutular = "".join(
        f'<rect x="{c * piksel}" y="{r * piksel}" width="{piksel}" height="{piksel}"/>'
        for r in range(4) for c in range(4) if m[r][c] < seviye
    )
    boyut = 4 * piksel
    return (f'<pattern id="{desen_id}" width="{boyut}" height="{boyut}" patternUnits="userSpaceOnUse">'
            f'<g fill="{renk}">{kutular}</g></pattern>')


# ------------------------------------------------------------------ SVG yardımcıları
def t(x: float, y: float, metin: str, sinif: str, **nit: str | float) -> str:
    ek = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in nit.items())
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{sinif}"{ek}>{escape(metin)}</text>'


def kose_isaretleri(g: int, y: int, renk: str) -> str:
    """Baskı kesim işaretleri (+)."""
    parcalar = []
    for cx, cy in ((18, 18), (g - 18, 18), (18, y - 18), (g - 18, y - 18)):
        parcalar.append(f'<path d="M{cx - 7} {cy}h14M{cx} {cy - 7}v14" stroke="{renk}" stroke-width="1"/>')
    return "".join(parcalar)


def svg(genislik: int, yukseklik: int, baslik: str, stil: str, govde: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{genislik}" height="{yukseklik}" '
        f'viewBox="0 0 {genislik} {yukseklik}" role="img" aria-label="{escape(baslik)}">\n'
        f"<title>{escape(baslik)}</title>\n<style>\n{stil}\n</style>\n{govde}\n</svg>\n"
    )


def ortak_stil(p: dict[str, str]) -> str:
    return f"""
text{{font-family:"Atkinson Hyperlegible Next",sans-serif;fill:{p['murekkep']}}}
.m{{font-family:"Atkinson Hyperlegible Mono",monospace;letter-spacing:.02em}}
.soluk{{fill:{p['murekkep-soluk']}}}
.kirmizi{{fill:{p['kirmizi']}}}
.mavi{{fill:{p['mavi']}}}
.a{{transform-box:fill-box;transform-origin:0 50%}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}"""


def kf(ad: str, sure: float, noktalar: list[tuple[float, str]], zamanlama: str = "linear",
       sayac: str = "infinite") -> str:
    """Bir öğeye özel keyframes + sınıf kuralı üretir."""
    adimlar = "".join(f"{y:g}%{{{css}}}" for y, css in noktalar)
    return (f"@keyframes {ad}{{{adimlar}}}\n"
            f".{ad}{{animation:{ad} {sure}s {zamanlama} {sayac} both}}")


# ------------------------------------------------------------------ 1. künye (başlık)
def kunye(p: dict[str, str]) -> str:
    Y = 470
    stil = [ortak_stil(p), font_face(["g400", "g800", "m400", "m700"])]
    g: list[str] = [f'<rect width="{W}" height="{Y}" fill="{p["kagit"]}"/>', kose_isaretleri(W, Y, p["murekkep-soluk"])]

    g.append(t(48, 50, "TÜRKÇE KOLAY DİL · SADE DİL", "m soluk", font_size=15))
    g.append(t(W - 48, 50, f"SAYI {SURUM} · EYLÜL 2026", "m soluk", font_size=15, text_anchor="end"))
    g.append(f'<rect x="48" y="62" width="{W - 96}" height="1" fill="{p["murekkep"]}"/>')

    # logo: siyah mürekkep, kırmızı kalıp 5 px kaymış
    sx, sy = W - 48 - 600, 72
    boyut = 124
    while olc("kolaymetin", "g800", boyut, -0.03 * boyut) > sx - 48 - 36:
        boyut -= 1
    ls = -0.03 * boyut
    g.append(f'<g font-weight="800" font-size="{boyut}" letter-spacing="{ls:.2f}">'
             f'{t(53, 219, "kolaymetin", "kirmizi")}{t(48, 214, "kolaymetin", "")}</g>')
    g.append(t(50, 264, "Kolay Dil denetim masası", "soluk", font_size=27))

    # künye sahnesi: kırmızı güneş sırtın ardından doğar, önünde tepeler (sahne 600×200)
    g.append(f'<clipPath id="sahne"><rect x="{sx}" y="{sy}" width="600" height="200"/></clipPath>')
    g.append(f'<g clip-path="url(#sahne)"><image class="a gunes" x="{sx + 404}" y="{sy + 2}" width="112" height="112" '
             f'href="{boya("kunye-gunes", p["kirmizi"])}" style="image-rendering:pixelated"/>'
             f'<image x="{sx}" y="{sy}" width="600" height="200" href="{manzara(p)}" style="image-rendering:pixelated"/></g>')
    stil.append(kf("gunes", 0.72, [(0, "transform:translateY(48px)"), (100, "transform:translateY(0)")],
                   "steps(6)", "1"))
    stil.append(".gunes{animation-delay:.3s}")

    # çift çizgi
    g.append(f'<rect x="0" y="284" width="{W}" height="2" fill="{p["murekkep"]}"/>'
             f'<rect x="0" y="290" width="{W}" height="2" fill="{p["murekkep"]}"/>')

    # slogan, "herkes" fosforlu kalemle
    sb = 44
    on, vurgu, son = "Kamu duyuruları ", "herkes", " içindir."
    tam = olc(on + vurgu + son, "g800", sb, -0.5)
    x0 = W / 2 - tam / 2
    vx = x0 + olc(on, "g800", sb, -0.5)
    vw = olc(vurgu, "g800", sb, -0.5)
    g.append(f'<rect class="a kalem" x="{vx - 6:.1f}" y="{362 - sb * 0.72:.1f}" width="{vw + 12:.1f}" '
             f'height="{sb * 0.86:.1f}" fill="{p["sari"]}"/>')
    g.append(t(x0, 362, on + vurgu + son, "", font_size=sb, font_weight=800, letter_spacing="-0.5"))
    stil.append(kf("kalem", 0.5, [(0, "transform:scaleX(0)"), (100, "transform:scaleX(1)")], "ease-out", "1"))
    stil.append(".kalem{animation-delay:1.1s}")

    # künye etiketleri
    etiketler = ["AÇIK KAYNAK · APACHE-2.0", "TAMAMEN ÇEVRİMDIŞI", "32 KURAL", f"SÜRÜM {SURUM}"]
    komut = "$ docker compose up  →  localhost:8000"
    eb, pad, ara = 15, 14, 12
    genislikler = [olc(e, "m400", eb, 0.3) + 2 * pad for e in etiketler]
    kw = olc(komut, "m700", eb, 0.3) + 2 * pad
    toplam = sum(genislikler) + kw + ara * len(etiketler)
    x = W / 2 - toplam / 2
    for e, ew in zip(etiketler, genislikler, strict=True):
        g.append(f'<rect x="{x + 3:.1f}" y="{403}" width="{ew:.1f}" height="34" fill="{p["murekkep"]}"/>'
                 f'<rect x="{x:.1f}" y="400" width="{ew:.1f}" height="34" fill="{p["kagit"]}" '
                 f'stroke="{p["murekkep"]}" stroke-width="1.5"/>')
        g.append(t(x + pad, 422, e, "m", font_size=eb))
        x += ew + ara
    g.append(f'<rect x="{x:.1f}" y="400" width="{kw:.1f}" height="34" fill="{p["murekkep"]}"/>')
    g.append(f'<text x="{x + pad:.1f}" y="422" class="m" font-size="{eb}" font-weight="700" fill="{p["kagit"]}" '
             f'style="fill:{p["kagit"]}">{escape(komut)}</text>')

    return svg(W, Y, "kolaymetin — Türkçe Kolay Dil / Sade Dil denetim masası", "\n".join(stil), "\n".join(g))


# ------------------------------------------------------------------ 2. düzeltme provası
PROVA_SURE = 12.0


def prova(p: dict[str, str]) -> str:
    Y = 610
    stil = [ortak_stil(p), font_face(["g400", "g400i", "g700", "g800", "m400", "m700"])]
    g: list[str] = [f'<rect width="{W}" height="{Y}" fill="{p["kagit"]}"/>', kose_isaretleri(W, Y, p["murekkep-soluk"])]
    sure = PROVA_SURE

    g.append(t(48, 50, "BELGE · DUYURU NO. 2026/417", "m soluk", font_size=15))
    g.append(t(W - 48, 50, "PROFİL: KOLAY DİL (EN SIKI)", "m soluk", font_size=15, text_anchor="end"))
    g.append(f'<rect x="48" y="62" width="{W - 96}" height="1" fill="{p["murekkep"]}"/>')

    # masa: kenar sütunu + metin alanı
    mx, my, mw, mh = 48, 90, 862, 400
    kenar = 196
    g.append(f'<rect x="{mx + 3}" y="{my + 3}" width="{mw}" height="{mh}" fill="{p["murekkep"]}"/>'
             f'<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" fill="{p["kagit"]}" stroke="{p["murekkep"]}" stroke-width="2"/>'
             f'<path d="M{mx + kenar} {my + 1}V{my + mh - 1}" stroke="{p["murekkep-soluk"]}" stroke-dasharray="3 4"/>')

    satirlar = [
        ["Müracaatların", "01.12.2026", "tarihinden"],
        ["itibaren", "ivedilikle", "yapılması"],
        ["gerekmektedir."],
    ]
    tx = mx + kenar + 30
    genislik_siniri = mx + mw - 24 - tx
    fb = 34
    while max(olc(" ".join(s), "g400", fb) for s in satirlar) > genislik_siniri:
        fb -= 1
    bosluk = olc(" ", "g400", fb)
    tabanlar = [my + 118, my + 238, my + 358]

    # kelimelerin konumları
    konum: dict[str, tuple[float, float, float]] = {}  # kelime → (x, taban, genişlik)
    for satir, taban in zip(satirlar, tabanlar, strict=True):
        x = float(tx)
        for k in satir:
            konum[k] = (x, taban, olc(k, "g400", fb))
            x += konum[k][2] + bosluk

    # 1) uyarı işaretleri: fosforlu kalem + ince alt çizgi (kolaymetin'in gerçek bulguları)
    uyarilar = ["Müracaatların", "01.12.2026", "itibaren", "ivedilikle", "yapılması", "gerekmektedir"]
    for i, k in enumerate(uyarilar):
        x, taban, w = konum[k if k in konum else k + "."]
        if k == "gerekmektedir":
            w = olc(k, "g400", fb)
        bas = 5 + i * 2.6
        ad = f"v{i}"
        g.append(f'<g class="a {ad}"><rect x="{x - 3:.1f}" y="{taban - fb * 0.82:.1f}" width="{w + 6:.1f}" '
                 f'height="{fb * 1.08:.1f}" fill="{p["sari"]}"/>'
                 f'<rect x="{x - 3:.1f}" y="{taban + 5:.1f}" width="{w + 6:.1f}" height="1.2" fill="{p["murekkep"]}"/></g>')
        stil.append(kf(ad, sure, [(0, "transform:scaleX(0);opacity:1"), (bas, "transform:scaleX(0);opacity:1"),
                                  (bas + 3, "transform:scaleX(1);opacity:1"), (40, "transform:scaleX(1);opacity:1"),
                                  (44, "transform:scaleX(1);opacity:0"), (100, "transform:scaleX(1);opacity:0")]))
        stil.append(f".{ad}{{opacity:0}}")

    # kenar işaretleri: □ uyarı + kural kimliği
    kenar_isaretleri = [["KD-K01", "KD-B04"], ["KD-K01", "KD-K01", "KD-C03"], ["KD-C07", "KD-C11"]]
    kenar_bas = [5, 10.2, 15.4]
    for j, (kimlikler, taban) in enumerate(zip(kenar_isaretleri, tabanlar, strict=True)):
        ad = f"k{j}"
        parcalar = []
        for n, kimlik in enumerate(kimlikler):
            yy = taban - 20 + n * 22 - (len(kimlikler) - 1) * 11
            parcalar.append(f'<rect x="{mx + 16}" y="{yy - 10}" width="10" height="10" fill="none" '
                            f'stroke="{p["murekkep"]}" stroke-width="1.6"/>')
            parcalar.append(t(mx + 34, yy, kimlik, "m", font_size=14, font_weight=700))
        g.append(f'<g class="{ad}">{"".join(parcalar)}</g>')
        b = kenar_bas[j]
        stil.append(kf(ad, sure, [(0, "opacity:0"), (b, "opacity:0"), (b + 1.5, "opacity:1"),
                                  (93, "opacity:1"), (97, "opacity:0"), (100, "opacity:0")]))

    # metin
    for satir, taban in zip(satirlar, tabanlar, strict=True):
        g.append(t(tx, taban, " ".join(satir), "", font_size=fb))

    # 2) düzeltmen: kırmızı silme çizgisi + mavi el yazısı düzeltme
    silinecek = [("Müracaatların", "Başvurular"), ("01.12.2026", "1 Aralık 2026 Salı"), ("tarihinden", None),
                 ("itibaren", "günü başlıyor."), ("ivedilikle", "Başvurunuzu hemen yapın."), ("yapılması", None),
                 ("gerekmektedir.", None)]
    db = round(fb * 0.74)
    son_bitis: dict[float, float] = {}
    for i, (k, duzeltme) in enumerate(silinecek):
        x, taban, w = konum[k]
        bas = 46 + i * 2.2
        ad = f"s{i}"
        g.append(f'<rect class="a {ad}" x="{x - 4:.1f}" y="{taban - fb * 0.3:.1f}" width="{w + 8:.1f}" height="3" '
                 f'fill="{p["kirmizi"]}"/>')
        stil.append(kf(ad, sure, [(0, "transform:scaleX(0);opacity:1"), (bas, "transform:scaleX(0);opacity:1"),
                                  (bas + 2, "transform:scaleX(1);opacity:1"), (93, "transform:scaleX(1);opacity:1"),
                                  (97, "transform:scaleX(1);opacity:0"), (100, "transform:scaleX(1);opacity:0")]))
        if duzeltme:
            dx = max(x, son_bitis.get(taban, 0) + 18)
            son_bitis[taban] = dx + olc(duzeltme, "g400i", db)
            ad = f"d{i}"
            # düzeltme işareti (⁁ biçiminde küçük şapka) + düzeltme metni
            g.append(f'<g class="{ad}"><path d="M{x - 2:.1f} {taban + 9:.1f}l7 -9l7 9" fill="none" '
                     f'stroke="{p["mavi"]}" stroke-width="2"/>'
                     f'{t(dx, taban - fb - 6, duzeltme, "mavi", font_size=db, font_style="italic")}</g>')
            stil.append(kf(ad, sure, [(0, "opacity:0;transform:translateY(6px)"),
                                      (bas + 1.5, "opacity:0;transform:translateY(6px)"),
                                      (bas + 4, "opacity:1;transform:translateY(0)"),
                                      (93, "opacity:1;transform:translateY(0)"),
                                      (97, "opacity:0;transform:translateY(0)"),
                                      (100, "opacity:0;transform:translateY(0)")]))

    # 3) skor kartı
    kx, kw = mx + mw + 30, W - 48 - (mx + mw + 30)
    g.append(f'<rect x="{kx}" y="{my}" width="{kw}" height="{mh}" fill="{p["kagit"]}" stroke="{p["murekkep"]}" stroke-width="2"/>')
    g.append(t(kx + 16, my + 30, "Kolay Dil Uyum Skoru", "m soluk", font_size=14))
    defs = []
    for n in range(17):
        defs.append(bayer_deseni(f"b{n}", n, p["murekkep"]))
    g.insert(0, f"<defs>{''.join(defs)}</defs>")

    def skor_grubu(ad: str, skor: int, alt: list[tuple[str, int]], bulgu: int) -> str:
        parca = [t(kx + 16, my + 104, str(skor), "m", font_size=72, font_weight=700)]
        sw = olc(str(skor), "m700", 72)
        parca.append(t(kx + 16 + sw + 12, my + 104, "/ 100", "m", font_size=15, font_weight=700))
        bx, bw = kx + 16, kw - 32
        parca.append(f'<rect x="{bx}" y="{my + 124}" width="{bw}" height="16" fill="none" stroke="{p["murekkep"]}" stroke-width="1.2"/>')
        parca.append(f'<rect class="a {ad}c" x="{bx + 2}" y="{my + 126}" width="{(bw - 4) * skor / 100:.1f}" height="12" '
                     f'fill="{p["murekkep"]}"/>')
        for n, (etiket, deger) in enumerate(alt):
            yy = my + 180 + n * 34
            parca.append(t(kx + 16, yy, etiket, "m soluk", font_size=14))
            cx, cw = kx + 96, kw - 96 - 52
            parca.append(f'<rect x="{cx}" y="{yy - 12}" width="{cw}" height="14" fill="none" stroke="{p["murekkep"]}" stroke-width="1.2"/>')
            seviye = round(deger / 100 * 16)
            dolgu = p["murekkep"] if seviye >= 16 else f"url(#b{seviye})"
            parca.append(f'<rect class="a {ad}c" x="{cx + 2}" y="{yy - 10}" width="{(cw - 4) * deger / 100:.1f}" height="10" fill="{dolgu}"/>')
            parca.append(t(kx + kw - 16, yy, str(deger), "m", font_size=14, font_weight=700, text_anchor="end"))
        parca.append(f'<path d="M{kx + 16} {my + 318}H{kx + kw - 16}" stroke="{p["murekkep-soluk"]}" stroke-dasharray="3 4"/>')
        parca.append(t(kx + 16, my + 352, f"Bulgular ({bulgu})", "", font_size=20, font_weight=700))
        parca.append(t(kx + 16, my + 380, "Ateşman " + ("−43,3" if skor < 50 else "61,2"), "m soluk", font_size=14))
        return f'<g class="{ad}">{"".join(parca)}</g>'

    g.append(skor_grubu("once", 1, [("Cümle", 17), ("Kelime", 17), ("Biçim", 55), ("Metin", 100)], 7))
    g.append(skor_grubu("sonra", 100, [("Cümle", 100), ("Kelime", 100), ("Biçim", 100), ("Metin", 100)], 0))
    stil.append(kf("once", sure, [(0, "opacity:1"), (64, "opacity:1"), (64.5, "opacity:0"), (97, "opacity:0"),
                                  (98, "opacity:1"), (100, "opacity:1")]))
    stil.append(".once{opacity:0}")
    stil.append(kf("sonra", sure, [(0, "opacity:0"), (64, "opacity:0"), (64.5, "opacity:1"), (97, "opacity:1"),
                                   (98, "opacity:0"), (100, "opacity:0")]))
    stil.append(kf("sonrac", sure, [(0, "transform:scaleX(0)"), (64.5, "transform:scaleX(0)"),
                                    (70, "transform:scaleX(1)"), (100, "transform:scaleX(1)")], "steps(8)"))

    # 4) alt yazı
    ab = 32
    on, vurgu, son = "Aynı bilgi. ", "Herkesin", " anlayacağı dilde."
    tam = olc(on + vurgu + son, "g800", ab)
    x0 = W / 2 - tam / 2
    vx, vw = x0 + olc(on, "g800", ab), olc(vurgu, "g800", ab)
    g.append(f'<g class="alt"><rect x="{vx - 5:.1f}" y="{556 - ab * 0.72:.1f}" width="{vw + 10:.1f}" height="{ab * 0.86:.1f}" '
             f'fill="{p["sari"]}"/>{t(x0, 556, on + vurgu + son, "", font_size=ab, font_weight=800)}</g>')
    stil.append(kf("alt", sure, [(0, "opacity:0"), (72, "opacity:0"), (75, "opacity:1"), (93, "opacity:1"),
                                 (97, "opacity:0"), (100, "opacity:0")]))

    return svg(W, Y, "Düzeltme provası: bürokratik cümle kolaymetin'in işaretleriyle Kolay Dile çevriliyor; uyum skoru 1'den 100'e çıkıyor",
               "\n".join(stil), "\n".join(g))


# ------------------------------------------------------------------ 3. kural sayfası
KATEGORILER = [
    ("Cümle", "kapak-cumle", "murekkep", [f"C{n:02d}" for n in range(1, 12)]),
    ("Kelime", "kapak-kelime", "mavi", [f"K{n:02d}" for n in range(1, 9)]),
    ("Biçim", "kapak-bicim", "kirmizi", [f"B{n:02d}" for n in range(1, 9)]),
    ("Metin", "kapak-metin", "murekkep", [f"M{n:02d}" for n in range(1, 6)]),
]


def kurallar(p: dict[str, str]) -> str:
    Y = 820
    stil = [ortak_stil(p), font_face(["g400", "g800", "m400", "m700"])]
    g: list[str] = [f'<rect width="{W}" height="{Y}" fill="{p["kagit"]}"/>', kose_isaretleri(W, Y, p["murekkep-soluk"])]
    g.append(t(48, 50, "KURAL REHBERİ · /rehber", "m soluk", font_size=15))
    g.append(t(W - 48, 50, "32 KURAL · 4 KATEGORİ · 3 ÖNEM DÜZEYİ", "m soluk", font_size=15, text_anchor="end"))
    g.append(f'<rect x="48" y="62" width="{W - 96}" height="1" fill="{p["murekkep"]}"/>')

    g.append(t(40, 290, "32", "", font_size=250, font_weight=800, letter_spacing="-10"))
    g.append(t(48, 360, "kural.", "", font_size=58, font_weight=800, letter_spacing="-1.5"))
    g.append(t(48, 424, "4 kategori.", "", font_size=58, font_weight=800, letter_spacing="-1.5"))

    satirlar = ["Her işaret için", "nedeni ve", "somut bir öneri."]
    for n, s in enumerate(satirlar):
        yy = 500 + n * 36
        if s.startswith("somut"):
            w = olc("somut", "g400", 25)
            g.append(f'<rect x="46" y="{yy - 19}" width="{w + 6:.1f}" height="23" fill="{p["sari"]}"/>')
        g.append(t(49, yy, s, "", font_size=25))

    # önem düzeyleri
    onem = [("■", "Hata", "kalın kırmızı çizgi"), ("□", "Uyarı", "fosforlu kalem"), ("○", "Bilgi", "noktalı mavi çizgi")]
    for n, (isaret, ad, aciklama) in enumerate(onem):
        yy = 650 + n * 40
        renk = {"■": p["kirmizi"], "□": p["murekkep"], "○": p["mavi"]}[isaret]
        if isaret == "■":
            g.append(f'<rect x="49" y="{yy - 13}" width="13" height="13" fill="{renk}"/>')
        elif isaret == "□":
            g.append(f'<rect x="50" y="{yy - 12}" width="11" height="11" fill="none" stroke="{renk}" stroke-width="2"/>')
        else:
            g.append(f'<circle cx="55.5" cy="{yy - 6.5}" r="6" fill="none" stroke="{renk}" stroke-width="2"/>')
        g.append(t(74, yy, ad, "m", font_size=17, font_weight=700))
        g.append(t(154, yy, aciklama, "soluk", font_size=17))
        ornek_y = yy + 8
        if isaret == "■":
            g.append(f'<rect x="154" y="{ornek_y}" width="{olc(aciklama, "g400", 17):.1f}" height="3" fill="{renk}"/>')
        elif isaret == "□":
            g.insert(-1, f'<rect x="152" y="{yy - 16}" width="{olc(aciklama, "g400", 17) + 4:.1f}" height="21" fill="{p["sari"]}"/>')
            g.append(f'<rect x="152" y="{ornek_y - 3}" width="{olc(aciklama, "g400", 17) + 4:.1f}" height="1.2" fill="{p["murekkep"]}"/>')
        else:
            g.append(f'<path d="M154 {ornek_y + 1}h{olc(aciklama, "g400", 17):.1f}" stroke="{renk}" stroke-width="2" stroke-dasharray="2 3"/>')

    # 2×2 kart
    cw, ch, ara = 380, 336, 32
    x0 = W - 48 - (2 * cw + ara)
    y0 = 96
    for n, (ad, gorsel, renk_ad, kimlikler) in enumerate(KATEGORILER):
        cx = x0 + (n % 2) * (cw + ara)
        cy = y0 + (n // 2) * (ch + ara)
        g.append(f'<rect x="{cx + 4}" y="{cy + 4}" width="{cw}" height="{ch}" fill="{p["murekkep"]}"/>'
                 f'<rect x="{cx}" y="{cy}" width="{cw}" height="{ch}" fill="{p["kagit"]}" stroke="{p["murekkep"]}" stroke-width="2"/>')
        g.append(f'<image x="{cx + 30}" y="{cy + 18}" width="320" height="180" href="{boya(gorsel, p[renk_ad])}" '
                 f'style="image-rendering:pixelated"/>')
        g.append(f'<path d="M{cx + 20} {cy + 212}H{cx + cw - 20}" stroke="{p["murekkep-soluk"]}" stroke-dasharray="3 4"/>')
        g.append(t(cx + 24, cy + 250, ad, "", font_size=30, font_weight=800, letter_spacing="-0.5"))
        g.append(t(cx + 24 + olc(ad, "g800", 30) + 12, cy + 250, f"{len(kimlikler)} kural", "m soluk", font_size=15))
        for i, kimlik in enumerate(kimlikler):
            kx = cx + 24 + (i % 6) * 55
            ky = cy + 270 + (i // 6) * 30
            g.append(f'<rect x="{kx}" y="{ky}" width="49" height="24" fill="none" stroke="{p["murekkep"]}" stroke-width="1.2"/>')
            g.append(t(kx + 24.5, ky + 17, kimlik, "m", font_size=13, font_weight=700, text_anchor="middle"))

    return svg(W, Y, "32 kural, 4 kategori: Cümle, Kelime, Biçim, Metin", "\n".join(stil), "\n".join(g))


# ------------------------------------------------------------------ 4. ayırıcı
def ayirici(p: dict[str, str]) -> str:
    Y = 40
    orta = W / 2
    g = [
        f'<path d="M24 20H{orta - 60}M{orta + 60} 20H{W - 24}" stroke="{p["murekkep"]}" stroke-width="1"/>',
        f'<path d="M10 20h14M17 13v14M{W - 24} 20h14M{W - 17} 13v14" stroke="{p["murekkep-soluk"]}" stroke-width="1"/>',
        f'<rect x="{orta - 38}" y="14" width="12" height="12" fill="{p["kirmizi"]}"/>',
        f'<rect x="{orta - 5}" y="15" width="10" height="10" fill="none" stroke="{p["murekkep"]}" stroke-width="2"/>',
        f'<circle cx="{orta + 32}" cy="20" r="6" fill="none" stroke="{p["mavi"]}" stroke-width="2"/>',
    ]
    return svg(W, Y, "", "", "\n".join(g)).replace(' role="img" aria-label=""', ' aria-hidden="true"').replace("<title></title>\n<style>\n\n</style>\n", "")


# ------------------------------------------------------------------ 5. kapanış künyesi
def kapanis(p: dict[str, str]) -> str:
    Y = 330
    stil = [ortak_stil(p), font_face(["g400", "g800", "m400", "m700"])]
    g: list[str] = [f'<rect width="{W}" height="{Y}" fill="{p["kagit"]}"/>', kose_isaretleri(W, Y, p["murekkep-soluk"])]
    g.append(f'<rect x="0" y="36" width="{W}" height="2" fill="{p["murekkep"]}"/>'
             f'<rect x="0" y="42" width="{W}" height="2" fill="{p["murekkep"]}"/>')
    # güneş batıyor: tepelerin ardına yarı gömülü
    sx, sy = W - 48 - 600, 90
    g.append(f'<clipPath id="sahne"><rect x="{sx}" y="{sy}" width="600" height="200"/></clipPath>')
    g.append(f'<g clip-path="url(#sahne)"><image x="{sx + 150}" y="{sy + 26}" width="112" height="112" '
             f'href="{boya("kunye-gunes", p["kirmizi"])}" style="image-rendering:pixelated"/>'
             f'<image x="{sx}" y="{sy}" width="600" height="200" href="{manzara(p)}" style="image-rendering:pixelated"/></g>')

    g.append(t(48, 84, "KÜNYE", "m soluk", font_size=15))
    satirlar = [
        ("Dizgi", "Atkinson Hyperlegible Next ve Mono"),
        ("Baskı", "krem kâğıt, siyah mürekkep, iki nokta renk"),
        ("Görsel", "1-bit dither: Atkinson, Bayer 4×4 ve 8×8"),
        ("Lisans", "kod Apache-2.0 · rehber ve sözlük CC BY 4.0"),
    ]
    for n, (etiket, deger) in enumerate(satirlar):
        yy = 122 + n * 34
        g.append(t(48, yy, etiket, "m", font_size=15, font_weight=700))
        g.append(t(136, yy, deger, "", font_size=19))
        g.append(f'<path d="M48 {yy + 12}H{sx - 40}" stroke="{p["murekkep-soluk"]}" stroke-dasharray="2 4"/>')
    g.append(t(48, 290, "Bu araç bir yardımcıdır, hakem değildir.", "", font_size=26, font_weight=800))
    g.append(t(48, 316, "Kolay Dil metnini her zaman hedef okurlarla test edin.", "soluk", font_size=17))
    return svg(W, Y, "Künye: Atkinson Hyperlegible ile dizildi; bu araç bir yardımcıdır, hakem değildir",
               "\n".join(stil), "\n".join(g))


# ------------------------------------------------------------------ 6. işlem hattı
def _kart(p: dict[str, str], x: float, y: float, w: float, h: float, satirlar: list[tuple[str, str, int]],
          zemin: str | None = None, yazi: str | None = None) -> str:
    """Düz ofset gölgeli kart. satirlar: (metin, yazı tipi anahtarı, boyut); ilk satır mono dosya adı."""
    zemin = zemin or p["kagit"]
    parca = [f'<rect x="{x + 4}" y="{y + 4}" width="{w}" height="{h}" fill="{p["murekkep"]}"/>',
             f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{zemin}" stroke="{p["murekkep"]}" stroke-width="2"/>']
    yy = y + 26
    for metin, anahtar, boyut in satirlar:
        genislik = olc(metin, anahtar, boyut)
        if genislik > w - 28:
            raise ValueError(f"'{metin}' karta sığmıyor ({genislik:.0f} > {w - 28})")
        mono = anahtar.startswith("m")
        sinif = "m" + (" soluk" if mono and yazi is None else "") if mono else ""
        kalin = YAZI[anahtar][1]
        renk = f' style="fill:{yazi}"' if yazi else ""
        parca.append(f'<text x="{x + 14}" y="{yy:.1f}" class="{sinif}" font-size="{boyut}" font-weight="{kalin}"{renk}>'
                     f"{escape(metin)}</text>")
        yy += boyut + 9
    return "".join(parca)


def _ok(p: dict[str, str], noktalar: list[tuple[float, float]]) -> str:
    """Dik açılı bağlantı çizgisi + dolu ok ucu (son iki noktanın yönünde)."""
    d = "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in noktalar)
    (x1, y1), (x2, y2) = noktalar[-2], noktalar[-1]
    if x2 > x1:
        uc = f"M{x2} {y2}l-9 -5v10z"
    elif x2 < x1:
        uc = f"M{x2} {y2}l9 -5v10z"
    else:
        uc = f"M{x2} {y2}l-5 -9h10z" if y2 > y1 else f"M{x2} {y2}l-5 9h10z"
    return (f'<path d="{d}" fill="none" stroke="{p["murekkep"]}" stroke-width="1.6"/>'
            f'<path d="{uc}" fill="{p["murekkep"]}"/>')


def hat(p: dict[str, str]) -> str:
    Y = 500
    stil = [ortak_stil(p), font_face(["g400", "g800", "m400", "m700"])]
    g: list[str] = [f'<rect width="{W}" height="{Y}" fill="{p["kagit"]}"/>', kose_isaretleri(W, Y, p["murekkep-soluk"])]
    g.append(t(48, 50, "İŞLEM HATTI · docs/MIMARI.md", "m soluk", font_size=15))
    g.append(t(W - 48, 50, "ÜÇ ARAYÜZ, TEK analyze()", "m soluk", font_size=15, text_anchor="end"))
    g.append(f'<rect x="48" y="62" width="{W - 96}" height="1" fill="{p["murekkep"]}"/>')

    # 1. satır: metinden morfolojiye
    ust = [
        ("girdi", "metin", ".txt .md .docx .pdf"),
        ("text/normalize.py", "normalize", "NFC · tırnak · tire"),
        ("text/segment.py", "segment", "paragraf · cümle"),
        ("text/tokenize.py", "tokenize", "kelime · sayı · hece"),
        ("text/morphology.py", "morfoloji", "zeyrek + sezgisel"),
    ]
    kw, kh, ara, x0, y0 = 204, 104, 40, 48, 96
    for i, (dosya, ad, alt) in enumerate(ust):
        x = x0 + i * (kw + ara)
        g.append(_kart(p, x, y0, kw, kh, [(dosya, "m400", 13), (ad, "g800", 22), (alt, "m400", 13)]))
        if i:
            g.append(_ok(p, [(x - ara + 4, y0 + kh / 2), (x - 3, y0 + kh / 2)]))

    # satırbaşı: morfolojiden aşağı, sola, ikinci satıra
    son_x = x0 + 4 * (kw + ara) + kw / 2
    g.append(_ok(p, [(son_x, y0 + kh + 4), (son_x, 238), (x0 + 130, 238), (x0 + 130, 262)]))
    g.append(t(son_x - 10, 230, "↵ satırbaşı", "m soluk", font_size=13, text_anchor="end"))

    # 2. satır: kurallar ve okunabilirlik → Report → çıktılar
    g.append(_kart(p, x0, 264, 260, 96, [("rules/ · lexicon.py", "m400", 13), ("32 kural", "g800", 22),
                                          ("profil (YAML) · sözlük", "m400", 13)], zemin=p["sari"], yazi=p["murekkep"]))
    g.append(_kart(p, x0, 380, 260, 96, [("readability/", "m400", 13), ("okunabilirlik", "g800", 22),
                                          ("Ateşman · Ç-U · B-Y", "m400", 13)]))
    rx, ry, rw, rh = 452, 318, 250, 104
    g.append(_kart(p, rx, ry, rw, rh, [("api.analyze()", "m400", 13), ("Report", "g800", 22),
                                        ("bulgular · skorlar", "m400", 13)], zemin=p["murekkep"], yazi=p["kagit"]))
    g.append(_ok(p, [(x0 + 264, 312), (392, 312), (392, 358), (rx - 3, 358)]))
    g.append(_ok(p, [(x0 + 264, 428), (392, 428), (392, 382), (rx - 3, 382)]))

    ciktilar = [("web/app.py", "web arayüzü", "FastAPI · /rehber"),
                ("cli.py", "komut satırı", "denetle · sunucu"),
                ("io/exporters.py", "dışa aktarma", "JSON · Markdown · HTML")]
    ox, ow, oh = 790, W - 48 - 790, 62
    for i, (dosya, ad, alt) in enumerate(ciktilar):
        oy = 262 + i * (oh + 14)
        g.append(f'<rect x="{ox + 4}" y="{oy + 4}" width="{ow}" height="{oh}" fill="{p["murekkep"]}"/>'
                 f'<rect x="{ox}" y="{oy}" width="{ow}" height="{oh}" fill="{p["kagit"]}" stroke="{p["murekkep"]}" stroke-width="2"/>')
        g.append(t(ox + 16, oy + 38, ad, "", font_size=22, font_weight=800))
        g.append(t(ox + 16 + olc(ad, "g800", 22) + 14, oy + 37, alt, "m", font_size=14))
        g.append(t(ox + ow - 14, oy + 22, dosya, "m soluk", font_size=12, text_anchor="end"))
        g.append(_ok(p, [(rx + rw + 4, 370), (746, 370), (746, oy + oh / 2), (ox - 3, oy + oh / 2)]))

    return svg(W, Y, "İşlem hattı: metin, normalize, segment, tokenize, morfoloji; sonra 32 kural ve okunabilirlik "
                     "formülleri; Report; web arayüzü, komut satırı ve dışa aktarma", "\n".join(stil), "\n".join(g))


# ------------------------------------------------------------------ 7. renk şeridi
RENK_ADLARI = [("kagit", "zemin"), ("kagit-2", "panel"), ("murekkep", "metin"), ("murekkep-soluk", "ikincil"),
               ("kirmizi", "hata"), ("mavi", "bilgi, bağlantı"), ("sari", "yalnızca kalem")]


def renkler(p: dict[str, str]) -> str:
    Y = 214
    stil = [ortak_stil(p), font_face(["m400", "m700"])]
    g: list[str] = [f'<rect width="{W}" height="{Y}" fill="{p["kagit"]}"/>', kose_isaretleri(W, Y, p["murekkep-soluk"])]
    ara = 14
    sw = (W - 96 - ara * (len(RENK_ADLARI) - 1)) / len(RENK_ADLARI)
    for i, (ad, gorev) in enumerate(RENK_ADLARI):
        x = 48 + i * (sw + ara)
        g.append(f'<rect x="{x + 4:.1f}" y="44" width="{sw:.1f}" height="130" fill="{p["murekkep"]}"/>'
                 f'<rect x="{x:.1f}" y="40" width="{sw:.1f}" height="130" fill="{p["kagit"]}" stroke="{p["murekkep"]}" stroke-width="1.5"/>'
                 f'<rect x="{x:.1f}" y="40" width="{sw:.1f}" height="72" fill="{p[ad]}" stroke="{p["murekkep"]}" stroke-width="1.5"/>')
        g.append(t(x + 10, 134, f"--{ad}", "m", font_size=13, font_weight=700))
        g.append(t(x + 10, 152, gorev, "m soluk", font_size=12))
        g.append(t(x + 10, 166, p[ad], "m soluk", font_size=12))
    return svg(W, Y, "Renkler: kâğıt, kâğıt 2, mürekkep, soluk mürekkep, kırmızı, mavi, sarı",
               "\n".join(stil), "\n".join(g))


# ------------------------------------------------------------------ çalıştır
GORSELLER: dict[str, Callable[[dict[str, str]], str]] = {
    "kunye": kunye,
    "prova": prova,
    "kurallar": kurallar,
    "hat": hat,
    "renkler": renkler,
    "ayirici": ayirici,
    "kapanis": kapanis,
}


def main() -> None:
    global _olcer
    ap = argparse.ArgumentParser(description="README görselleri")
    ap.add_argument("--kanal", default=None, help="Tarayıcı kanalı (ör. msedge, chrome)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    _olcer = Olcer(args.kanal)
    try:
        for tema, p in paletler().items():
            for ad, uret in GORSELLER.items():
                yol = OUT / f"{ad}-{tema}.svg"
                yol.write_text(uret(p), encoding="utf-8")
                print(f"{yol.relative_to(ROOT)}  {yol.stat().st_size // 1024} KB")
    finally:
        _olcer.kapat()


if __name__ == "__main__":
    main()
