"""1-bit dither (titreşimli tarama) üreticisi.

Gri tonlu bir görseli (PNG, JPG ya da SVG) Atkinson hata yayma ya da Bayer sıralı dither
ile 1-bit'e çevirir. Çıktı: şeffaf zeminli, yalnızca siyah pikselli PNG. Renklendirme
CSS ile yapılır (mask-image), böylece aynı görsel açık/koyu temada çalışır.

Kullanım:
    python scripts/dither.py GIRDI.svg CIKTI.png [--yontem atkinson|bayer4|bayer8]
                             [--genislik 160] [--gama 1.0] [--ters]
    python scripts/dither.py --desenler KLASOR     # Bayer 4×4 desen karoları (17 seviye)
    python scripts/dither.py --hepsi               # projedeki bütün görselleri yeniden üret

Gereken: Pillow; SVG girdisi için resvg-py (pip install resvg-py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "kolaymetin" / "web" / "static"
KAYNAK = ROOT / "assets" / "kaynak"

BAYER4 = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
]


def bayer_matrix(n: int) -> list[list[int]]:
    """n×n Bayer matrisi (n: 2'nin kuvveti)."""
    if n == 1:
        return [[0]]
    half = bayer_matrix(n // 2)
    size = n // 2
    out = [[0] * n for _ in range(n)]
    for y in range(size):
        for x in range(size):
            v = half[y][x] * 4
            out[y][x] = v
            out[y][x + size] = v + 2
            out[y + size][x] = v + 3
            out[y + size][x + size] = v + 1
    return out


def load_gray(path: Path, width: int | None = None) -> Image.Image:
    """Görseli gri tonlu (L) olarak yükler; SVG ise önce PNG'ye çevirir."""
    if path.suffix.lower() == ".svg":
        try:
            import resvg_py
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("SVG için resvg-py gerekli: pip install resvg-py") from exc
        import io

        data = bytes(resvg_py.svg_to_bytes(svg_string=path.read_text(encoding="utf-8")))
        img = Image.open(io.BytesIO(data))
    else:
        img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        img = bg
    img = img.convert("L")
    if width and img.width != width:
        height = max(1, round(img.height * width / img.width))
        img = img.resize((width, height), Image.Resampling.LANCZOS)
    return img


def _apply_gamma(values: list[float], gamma: float) -> list[float]:
    if gamma == 1.0:
        return values
    return [255.0 * ((v / 255.0) ** gamma) for v in values]


def atkinson(img: Image.Image, gamma: float = 1.0) -> list[list[bool]]:
    """Atkinson hata yayma. Dönüş: True = mürekkep (siyah piksel)."""
    w, h = img.size
    px = _apply_gamma([float(v) for v in img.tobytes()], gamma)
    ink = [[False] * w for _ in range(h)]
    neighbours = ((1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2))
    for y in range(h):
        for x in range(w):
            i = y * w + x
            old = px[i]
            new = 255.0 if old >= 128 else 0.0
            ink[y][x] = new == 0.0
            err = (old - new) / 8.0
            for dx, dy in neighbours:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and ny < h:
                    px[ny * w + nx] += err
    return ink


def bayer(img: Image.Image, n: int = 4, gamma: float = 1.0) -> list[list[bool]]:
    """Bayer sıralı dither."""
    w, h = img.size
    m = bayer_matrix(n)
    scale = n * n
    px = _apply_gamma([float(v) for v in img.tobytes()], gamma)
    ink = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            threshold = (m[y % n][x % n] + 0.5) * 255.0 / scale
            ink[y][x] = px[y * w + x] < threshold
    return ink


def to_png(ink: list[list[bool]], invert: bool = False, scale: int = 1) -> Image.Image:
    """Mürekkep matrisini şeffaf zeminli siyah PNG'ye çevirir.

    scale > 1 ise her piksel scale×scale kare olarak büyütülür (en yakın komşu); böylece
    tarayıcı ölçeklemesinden bağımsız olarak pikseller net ve kare görünür.
    """
    h = len(ink)
    w = len(ink[0]) if h else 0
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    data = []
    for row in ink:
        for on in row:
            on = (not on) if invert else on
            data.append((0, 0, 0, 255) if on else (0, 0, 0, 0))
    out.putdata(data)
    if scale > 1:
        out = out.resize((w * scale, h * scale), Image.Resampling.NEAREST)
    return out


def dither_file(
    src: Path, dst: Path, method: str = "atkinson", width: int | None = 160,
    gamma: float = 1.0, invert: bool = False, scale: int = 1,
) -> Path:
    img = load_gray(src, width)
    if method == "atkinson":
        ink = atkinson(img, gamma)
    elif method in ("bayer4", "bayer8"):
        ink = bayer(img, 4 if method == "bayer4" else 8, gamma)
    else:
        raise SystemExit(f"Bilinmeyen yöntem: {method}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    to_png(ink, invert, scale).save(dst, optimize=True)
    return dst


def pattern_tiles(folder: Path, n: int = 4, scale: int = 2) -> list[Path]:
    """0…n² seviyeli Bayer desen karoları: seviye k'da n² pikselin k tanesi mürekkeplidir."""
    folder.mkdir(parents=True, exist_ok=True)
    m = bayer_matrix(n)
    paths = []
    for level in range(n * n + 1):
        ink = [[m[y][x] < level for x in range(n)] for y in range(n)]
        p = folder / f"bayer{n}-{level:02d}.png"
        to_png(ink, scale=scale).save(p, optimize=True)
        paths.append(p)
    return paths


# Projedeki görseller: kaynak → (çıktı, yöntem, genişlik, gama)
PROJECT_IMAGES = {
    "duyuru-panosu.svg": ("gorsel/bos-durum.png", "atkinson", 160, 1.0),
    "megafon.svg": ("gorsel/kapak-cumle.png", "atkinson", 160, 1.0),
    "buyutec.svg": ("gorsel/kapak-kelime.png", "atkinson", 160, 1.0),
    "katlanmis-kagit.svg": ("gorsel/kapak-bicim.png", "atkinson", 160, 0.8),
    "el-kalem.svg": ("gorsel/kapak-metin.png", "atkinson", 160, 1.0),
    "kunye-gunes.svg": ("gorsel/kunye-gunes.png", "atkinson", 56, 1.0),
}


def build_all() -> list[Path]:
    made = []
    for src, (dst, method, width, gamma) in PROJECT_IMAGES.items():
        made.append(dither_file(KAYNAK / src, STATIC / dst, method, width, gamma, scale=2))
    made += pattern_tiles(STATIC / "desen", 4)
    return made


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="1-bit dither üreticisi")
    ap.add_argument("girdi", nargs="?", help="Kaynak görsel (.svg, .png, .jpg)")
    ap.add_argument("cikti", nargs="?", help="Çıktı PNG yolu")
    ap.add_argument("--yontem", default="atkinson", choices=["atkinson", "bayer4", "bayer8"])
    ap.add_argument("--genislik", type=int, default=160, help="Piksel genişliği (varsayılan 160)")
    ap.add_argument("--gama", type=float, default=1.0, help="Gama düzeltmesi (1.0 = yok)")
    ap.add_argument("--ters", action="store_true", help="Mürekkep ve boşluğu yer değiştir")
    ap.add_argument("--olcek", type=int, default=2, help="Piksel büyütme katı (varsayılan 2)")
    ap.add_argument("--desenler", metavar="KLASOR", help="Bayer 4×4 desen karolarını üret")
    ap.add_argument("--hepsi", action="store_true", help="Projedeki bütün görselleri üret")
    args = ap.parse_args(argv)
    if args.hepsi:
        for p in build_all():
            print("yazıldı:", p.relative_to(ROOT))
        return 0
    if args.desenler:
        for p in pattern_tiles(Path(args.desenler)):
            print("yazıldı:", p)
        return 0
    if not args.girdi or not args.cikti:
        ap.error("GIRDI ve CIKTI gerekli (ya da --hepsi / --desenler kullanın).")
    out = dither_file(Path(args.girdi), Path(args.cikti), args.yontem, args.genislik,
                      args.gama, args.ters, args.olcek)
    print("yazıldı:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
