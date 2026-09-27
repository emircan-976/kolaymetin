"""Dither betiği, piksel ikonlar, yazı tipleri ve kod temizliği."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PIL import Image

import dither
import ikonlar

ROOT = Path(__file__).resolve().parents[1]


def pixels(img: Image.Image) -> list[tuple[int, ...]]:
    raw = img.convert("RGBA").tobytes()
    return [tuple(raw[i : i + 4]) for i in range(0, len(raw), 4)]
STATIC = ROOT / "src" / "kolaymetin" / "web" / "static"


def test_bayer_matrix() -> None:
    assert dither.bayer_matrix(2) == [[0, 2], [3, 1]]
    m = dither.bayer_matrix(4)
    assert sorted(v for row in m for v in row) == list(range(16))
    assert m == dither.BAYER4


def test_atkinson_and_bayer_on_gradient() -> None:
    img = Image.linear_gradient("L").resize((32, 32))
    for ink in (dither.atkinson(img), dither.bayer(img, 4), dither.bayer(img, 8, gamma=0.8)):
        top = sum(ink[0])
        bottom = sum(ink[-1])
        assert top > bottom  # üst koyu (mürekkep çok), alt açık
    png = dither.to_png(dither.atkinson(img), scale=2)
    assert png.size == (64, 64) and png.mode == "RGBA"
    colors = set(pixels(png))
    assert colors <= {(0, 0, 0, 255), (0, 0, 0, 0)}  # 1-bit: yalnızca siyah ya da şeffaf


def test_dither_file_and_tiles(tmp_path: Path) -> None:
    src = tmp_path / "kaynak.png"
    Image.linear_gradient("L").save(src)
    out = dither.dither_file(src, tmp_path / "out.png", "bayer4", width=40, scale=3)
    assert Image.open(out).size == (120, 120)
    inverted = dither.dither_file(src, tmp_path / "ters.png", "atkinson", width=16, invert=True, scale=1)
    assert Image.open(inverted).size == (16, 16)
    tiles = dither.pattern_tiles(tmp_path / "desen", 4, scale=1)
    assert len(tiles) == 17
    assert sum(1 for px in pixels(Image.open(tiles[0])) if px[3]) == 0
    assert sum(1 for px in pixels(Image.open(tiles[8])) if px[3]) == 8
    assert sum(1 for px in pixels(Image.open(tiles[16])) if px[3]) == 16
    with pytest.raises(SystemExit):
        dither.dither_file(src, tmp_path / "x.png", "yok")


def test_svg_source_rasterizes(tmp_path: Path) -> None:
    pytest.importorskip("resvg_py")
    out = dither.dither_file(ROOT / "assets" / "kaynak" / "megafon.svg", tmp_path / "m.png", width=80, scale=1)
    assert Image.open(out).size[0] == 80


def test_shipped_images_are_one_bit() -> None:
    images = list((STATIC / "gorsel").glob("*.png")) + list((STATIC / "desen").glob("*.png"))
    assert len(images) == 6 + 17
    for p in images:
        colors = set(pixels(Image.open(p)))
        assert colors <= {(0, 0, 0, 255), (0, 0, 0, 0)}, p.name
        assert p.stat().st_size < 8_000, p.name


def test_icons() -> None:
    required = {"yukle", "disa-aktar", "kopyala", "tema", "yazi-buyut", "yazi-kucult", "bilgi",
                "kapat", "sonraki", "onceki", "rehber", "filtre"}
    assert required <= set(ikonlar.ICONS)
    for name, (_title, art) in ikonlar.ICONS.items():
        rects = ikonlar._rects(art)
        assert rects, name
        assert all(0 <= x < 16 and 0 <= y < 16 and x + w <= 16 for x, y, w in rects)
    sprite = (STATIC / "ikonlar.svg").read_text(encoding="utf-8")
    assert sprite == ikonlar.sprite()  # üretilen dosya güncel
    with pytest.raises(ValueError):
        ikonlar._rects("#")


def test_icon_script_writes(tmp_path: Path) -> None:
    assert ikonlar.main([str(tmp_path)]) == 0
    assert (tmp_path / "ikon" / "yukle.svg").is_file() and (tmp_path / "ikonlar.svg").is_file()
    assert (tmp_path / "isaret.svg").is_file()


def _hucre(art: str) -> set[tuple[int, int]]:
    return {(x + i, y) for x, y, w in ikonlar._rects(art) for i in range(w)}


def test_dortlu_geometry() -> None:
    """Üç işaret 7×7 hücrelerde: ■ sol üst, □ sağ üst, ○ sol alt; sağ alt boş (temiz metin)."""
    assert list(ikonlar.DORTLU) == ["hata", "uyari", "bilgi"]
    hucreler = {"hata": (0, 0), "uyari": (9, 0), "bilgi": (0, 9)}
    for ad, (x0, y0) in hucreler.items():
        pikseller = _hucre(ikonlar.DORTLU[ad][1])
        assert all(x0 <= x < x0 + 7 and y0 <= y < y0 + 7 for x, y in pikseller), ad
    hata, uyari, bilgi = (_hucre(ikonlar.DORTLU[a][1]) for a in ("hata", "uyari", "bilgi"))
    assert len(hata) == 49  # dolu
    assert len(uyari) == 24 and (12, 3) not in uyari  # boş kare, 1 piksel çerçeve
    assert bilgi == {(x, 24 - y) for x, y in bilgi} == {(6 - x, y) for x, y in bilgi}  # simetrik daire
    assert not any(x >= 9 and y >= 9 for x, y in hata | uyari | bilgi)  # sağ alt hücre boş


def test_dortlu_outputs_are_current() -> None:
    sprite = (STATIC / "ikonlar.svg").read_text(encoding="utf-8")
    for ad in ikonlar.DORTLU:
        assert f'<symbol id="i-dortlu-{ad}" viewBox="0 0 16 16"' in sprite
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    favicon = (STATIC / "isaret.svg").read_text(encoding="utf-8")
    assert favicon == ikonlar.isaret(css)  # renkler style.css ile aynı
    assert "prefers-color-scheme:dark" in favicon and "#FF6B5E" in favicon


def test_dortlu_animation_is_a_sliding_puzzle() -> None:
    """Her an tam bir hücre boştur; işaretler yalnızca komşu hücreye kayar; 12 adımda başa dönülür."""
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    ev = {"hata": (0, 0), "uyari": (9, 0), "bilgi": (0, 9)}
    yollar: dict[str, list[tuple[float, tuple[int, int]]]] = {}
    for ad, (ex, ey) in ev.items():
        govde = re.search(r"@keyframes dortlu-" + ad + r" \{(.*?)\n\}", css, re.S)
        assert govde, ad
        noktalar = []
        for yuzdeler, dx, dy in re.findall(r"([\d.%, ]+)\{ transform: translate\((-?\d+)(?:px)?, (-?\d+)(?:px)?\); \}",
                                           govde.group(1)):
            for y in yuzdeler.split(","):
                noktalar.append((float(y.strip().rstrip("%")), (ex + int(dx), ey + int(dy))))
        yollar[ad] = sorted(noktalar)
        assert yollar[ad][0] == (0.0, (ex, ey)) and yollar[ad][-1] == (100.0, (ex, ey)), ad
    hucreler = {(0, 0), (9, 0), (9, 9), (0, 9)}

    def konum(ad: str, an: float) -> tuple[int, int]:
        return [k for y, k in yollar[ad] if y <= an][-1]

    onceki = None
    for adim in range(12):
        an = (adim + 1) * 100 / 12 - 0.01  # adımın sonunda her işaret bir hücrede durur
        konumlar = [konum(ad, an) for ad in ev]
        assert set(konumlar) < hucreler and len(set(konumlar)) == 3, adim
        if onceki:
            degisen = [(a, b) for a, b in zip(onceki, konumlar, strict=True) if a != b]
            assert len(degisen) == 1, adim  # her adımda tek işaret
            (x1, y1), (x2, y2) = degisen[0]
            assert abs(x1 - x2) + abs(y1 - y2) == 9, adim  # komşu hücreye
        onceki = konumlar
    assert onceki == list(ev.values())


def test_fonts_are_local_and_cover_turkish() -> None:
    fonts = STATIC / "fonts"
    names = {p.name for p in fonts.glob("*.woff2")}
    for fam in ("next", "mono"):
        assert f"atkinson-hyperlegible-{fam}-latin-400-normal.woff2" in names
        assert f"atkinson-hyperlegible-{fam}-latin-ext-400-normal.woff2" in names
    assert (fonts / "OFL-Atkinson-Hyperlegible-Next.txt").is_file()
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "U+0100-02BA" in css  # ğ, ı, ş, İ latin-ext alt kümesinde


def test_no_todo_markers() -> None:
    pattern = re.compile(r"\b(TODO|FIXME|XXX)\b|pass\s*#\s*later", re.IGNORECASE)
    roots = [ROOT / "src", ROOT / "tests", ROOT / "scripts", ROOT / "docs"]
    offenders = []
    for root in roots:
        for p in root.rglob("*"):
            if p.suffix in {".py", ".js", ".css", ".html", ".md", ".yaml", ".txt"} and p.is_file():
                if p.name == "test_assets.py":
                    continue
                if pattern.search(p.read_text(encoding="utf-8", errors="ignore")):
                    offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, offenders
