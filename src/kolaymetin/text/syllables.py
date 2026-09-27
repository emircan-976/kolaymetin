"""Türkçe hece sayımı.

Türkçede her hecede tam bir ünlü bulunur; bu yüzden hece sayısı ünlü sayısına eşittir.
Rakamlar okunuşlarına, kısaltmalar sözlükteki okunuşa ya da harf harf okunuşa çevrilir.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from kolaymetin.text.normalize import turkish_lower

VOWELS = frozenset("aeıioöuüâîû")

_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_SCALES = [
    (10**18, "kentilyon"),
    (10**15, "katrilyon"),
    (10**12, "trilyon"),
    (10**9, "milyar"),
    (10**6, "milyon"),
    (10**3, "bin"),
]
MONTHS = [
    "ocak", "şubat", "mart", "nisan", "mayıs", "haziran",
    "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık",
]

# Harf adlarının hece sayısı (harf harf okunan kısaltmalar için). "ğ" = "yumuşak ge".
_LETTER_SYLLABLES = {"ğ": 3, "w": 2}


def count_vowels(text: str) -> int:
    return sum(1 for c in turkish_lower(text) if c in VOWELS)


def _below_thousand(n: int) -> str:
    parts = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        parts.append("yüz" if hundreds == 1 else f"{_ONES[hundreds]} yüz")
    tens, ones = divmod(rest, 10)
    if tens:
        parts.append(_TENS[tens])
    if ones:
        parts.append(_ONES[ones])
    return " ".join(parts)


def number_to_words_builtin(n: int) -> str:
    """Tam sayıyı Türkçe okunuşa çevirir (num2words yoksa kullanılır)."""
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + number_to_words_builtin(-n)
    parts = []
    for value, name in _SCALES:
        if n >= value:
            count, n = divmod(n, value)
            if value == 1000 and count == 1:
                parts.append("bin")
            else:
                parts.append(f"{number_to_words_builtin(count)} {name}")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def number_to_words(n: int) -> str:
    """num2words varsa onu, yoksa yerleşik dönüştürücüyü kullanır."""
    try:
        from num2words import num2words

        return str(num2words(n, lang="tr"))
    except Exception:  # pragma: no cover - num2words yoksa
        return number_to_words_builtin(n)


def read_number(text: str) -> str:
    """'15.000', '3,5', '1996' gibi bir sayıyı okunuşa çevirir."""
    raw = text.strip()
    if "," in raw:
        whole, frac = raw.split(",", 1)
        whole_n = int(whole.replace(".", "") or "0")
        frac_digits = re.sub(r"\D", "", frac)
        frac_read = " ".join(number_to_words(int(d)) for d in frac_digits) if frac_digits else ""
        return f"{number_to_words(whole_n)} virgül {frac_read}".strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
        return number_to_words(int(raw.replace(".", "")))
    if "." in raw:
        return " ".join(number_to_words(int(p)) for p in raw.split(".") if p.isdigit())
    return number_to_words(int(raw)) if raw.isdigit() else raw


def read_date(text: str) -> str:
    parts = re.split(r"[./]", text)
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return read_number(text)
    day, month, year = (int(p) for p in parts)
    month_name = MONTHS[month - 1] if 1 <= month <= 12 else number_to_words(month)
    return f"{number_to_words(day)} {month_name} {number_to_words(year)}"


def read_time(text: str) -> str:
    hour, minute = (int(p) for p in re.split(r"[.:]", text)[:2])
    if minute == 0:
        return number_to_words(hour)
    return f"{number_to_words(hour)} {number_to_words(minute)}"


def spell_letters(text: str) -> int:
    """Harf harf okunan kısaltmanın hece sayısı (TBMM → te-be-me-me → 4)."""
    total = 0
    for c in turkish_lower(text):
        if c.isalpha():
            total += _LETTER_SYLLABLES.get(c, 1)
    return total


def _split_suffix(text: str) -> tuple[str, str]:
    if "'" in text:
        base, suffix = text.split("'", 1)
        return base, suffix
    return text, ""


def syllable_count(
    text: str,
    kind: str = "word",
    is_abbreviation: bool = False,
    readings: Mapping[str, str] | None = None,
) -> int:
    """Bir sözcük birimindeki hece sayısını döndürür."""
    base, suffix = _split_suffix(text)
    suffix_syl = count_vowels(suffix)
    if kind == "number":
        return count_vowels(read_number(base)) + suffix_syl
    if kind == "date":
        return count_vowels(read_date(base)) + suffix_syl
    if kind == "time":
        return count_vowels(read_time(base)) + suffix_syl
    if kind == "percent":
        digits = base.replace("%", "").strip()
        return count_vowels("yüzde " + read_number(digits)) + suffix_syl
    if kind in ("url", "email"):
        return max(1, count_vowels(base))
    if is_abbreviation:
        key = base
        reading = None
        if readings:
            reading = readings.get(key) or readings.get(turkish_lower(key))
        if reading:
            return count_vowels(reading) + suffix_syl
        return spell_letters(base) + suffix_syl
    vowels = count_vowels(text)
    if vowels == 0 and any(c.isalpha() for c in text):
        return spell_letters(text)  # "km", "kg" gibi ünlüsüz yazımlar
    return vowels
