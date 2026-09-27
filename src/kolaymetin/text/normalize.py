"""Metin normalleştirme ve orijinal ofset eşlemesi.

Kullanıcının yapıştırdığı metin değiştirilmeden saklanır. Çözümleme normalleştirilmiş kopya
üzerinde yapılır; her normalleştirilmiş karakter için orijinal metindeki başlangıç ve bitiş
konumları tutulur. Böylece her bulgu orijinal metindeki doğru yeri gösterir.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

_QUOTE_DOUBLE = "“”„‟«»″"
_QUOTE_SINGLE = "‘’‚‛′`"
_DASHES = "‐‑‒–—―−"
_SPACES = "\t              　"
_REMOVE = "​‌‍⁠﻿­"

_CHAR_MAP: dict[str, str] = {}
for _c in _QUOTE_DOUBLE:
    _CHAR_MAP[_c] = '"'
for _c in _QUOTE_SINGLE:
    _CHAR_MAP[_c] = "'"
for _c in _DASHES:
    _CHAR_MAP[_c] = "-"
for _c in _SPACES:
    _CHAR_MAP[_c] = " "
for _c in _REMOVE:
    _CHAR_MAP[_c] = ""

_LOWER_SPECIAL = str.maketrans({"I": "ı", "İ": "i"})
_UPPER_SPECIAL = str.maketrans({"i": "İ", "ı": "I"})
_CIRCUMFLEX = str.maketrans({"â": "a", "î": "i", "û": "u", "Â": "A", "Î": "İ", "Û": "U"})


def turkish_lower(text: str) -> str:
    """Türkçe kurallarıyla küçük harfe çevirir (I→ı, İ→i)."""
    return text.translate(_LOWER_SPECIAL).lower()


def turkish_upper(text: str) -> str:
    """Türkçe kurallarıyla büyük harfe çevirir (i→İ, ı→I)."""
    return text.translate(_UPPER_SPECIAL).upper()


def turkish_capitalize(text: str) -> str:
    """İlk harfi Türkçe kurallarıyla büyütür, gerisini küçültür."""
    if not text:
        return text
    return turkish_upper(text[0]) + turkish_lower(text[1:])


def fold_circumflex(text: str) -> str:
    """Şapkalı ünlüleri düz ünlüye çevirir (mezkûr → mezkur)."""
    return text.translate(_CIRCUMFLEX)


def is_upper_word(text: str) -> bool:
    # Büyük/küçük harfi olmayan yazılar (Arap harfleriyle "معمار") büyük harfli sayılmaz:
    # küçük harfe çevrilince değişen en az bir harf olmalı.
    return text == turkish_upper(text) and text != turkish_lower(text)


@dataclass
class NormalizedText:
    """Normalleştirilmiş metin ve orijinal metne karakter eşlemesi."""

    original: str
    text: str
    starts: list[int]
    ends: list[int]

    def to_original(self, start: int, end: int) -> tuple[int, int]:
        """Normalleştirilmiş [start, end) aralığını orijinal metindeki aralığa çevirir."""
        n = len(self.text)
        start = max(0, min(start, n))
        end = max(start, min(end, n))
        if start == n:
            pos = len(self.original)
            return pos, pos
        o_start = self.starts[start]
        o_end = self.ends[end - 1] if end > start else o_start
        return o_start, o_end


def _grapheme_groups(text: str) -> list[tuple[int, int]]:
    """Taban karakteri ve onu izleyen birleşik (combining) işaretleri gruplar."""
    groups: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        j = i + 1
        while j < n and unicodedata.combining(text[j]):
            j += 1
        groups.append((i, j))
        i = j
    return groups


def normalize(text: str) -> NormalizedText:
    """Metni normalleştirir: NFC, tırnak/tire birleştirme, boşluk temizliği.

    Orijinal ofsetler korunur.
    """
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []

    def emit(chars: str, o_start: int, o_end: int) -> None:
        for ch in chars:
            # Art arda gelen yatay boşlukları tek boşluğa indir.
            if ch == " " and out and out[-1] == " ":
                ends[-1] = o_end
                continue
            out.append(ch)
            starts.append(o_start)
            ends.append(o_end)

    for g_start, g_end in _grapheme_groups(text):
        chunk = text[g_start:g_end]
        if chunk == "\r":
            # \r\n → \n ; tek başına \r → \n
            if g_end < len(text) and text[g_end] == "\n":
                continue
            emit("\n", g_start, g_end)
            continue
        if len(chunk) > 1:
            chunk = unicodedata.normalize("NFC", chunk)
        mapped = "".join(_CHAR_MAP.get(c, c) for c in chunk)
        if not mapped:
            continue
        emit(mapped, g_start, g_end)

    return NormalizedText(original=text, text="".join(out), starts=starts, ends=ends)
