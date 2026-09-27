"""Tanıtım videosu için görselleri hazırlar.

Projedeki 1-bit dither görselleri (siyah piksel, şeffaf zemin) istenen nokta renge boyar ve
en yakın komşu yöntemiyle büyütür. Çıktı: tanitim/gorsel/.
"""

from pathlib import Path

from PIL import Image

KOK = Path(__file__).resolve().parent.parent
KAYNAK = KOK / "src/kolaymetin/web/static/gorsel"
HEDEF = Path(__file__).resolve().parent / "gorsel"

MUREKKEP = (0x1B, 0x1A, 0x17)
KIRMIZI = (0xB4, 0x2D, 0x26)
MAVI = (0x23, 0x40, 0x8E)

# (kaynak, renk, çarpan)
ISLER = [
    ("bos-durum", MUREKKEP, 2),
    ("kapak-cumle", MUREKKEP, 2),
    ("kapak-kelime", MAVI, 2),
    ("kapak-bicim", KIRMIZI, 2),
    ("kapak-metin", MUREKKEP, 2),
]


def boya(ad: str, renk: tuple[int, int, int], carpan: int) -> None:
    im = Image.open(KAYNAK / f"{ad}.png").convert("RGBA")
    alfa = im.getchannel("A")
    dolu = Image.new("RGBA", im.size, (*renk, 255))
    bos = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sonuc = Image.composite(dolu, bos, alfa.point(lambda a: 255 if a > 127 else 0))
    sonuc = sonuc.resize((im.width * carpan, im.height * carpan), Image.NEAREST)
    sonuc.save(HEDEF / f"{ad}.png")


def main() -> None:
    HEDEF.mkdir(exist_ok=True)
    for ad, renk, carpan in ISLER:
        boya(ad, renk, carpan)
    print("hazır:", ", ".join(a for a, _, _ in ISLER))


if __name__ == "__main__":
    main()
