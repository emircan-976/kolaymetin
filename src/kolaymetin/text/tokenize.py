"""Sözcük birimlerine ayırma: kelime, sayı, noktalama, URL, e-posta, tarih, saat, yüzde."""

from __future__ import annotations

import re
from collections.abc import Mapping

from kolaymetin.models import Token, TokenKind
from kolaymetin.text.normalize import is_upper_word, turkish_lower
from kolaymetin.text.syllables import syllable_count

_SUFFIX = r"(?:'[^\W\d_]+)?"
TOKEN_RE = re.compile(
    rf"""
    (?P<url>(?:https?://|www\.)[^\s<>"']*[^\s<>"'.,;:!?)\]]{_SUFFIX})
  | (?P<email>[\w.+-]+@[\w-]+(?:\.[\w-]+)+{_SUFFIX})
  | (?P<date>(?<![\d.])\d{{1,2}}[./]\d{{1,2}}[./]\d{{2,4}}(?![\d]){_SUFFIX})
  | (?P<time>(?<![\d.,])(?:[01]?\d|2[0-3])[:.][0-5]\d(?![\d]|[.,]\d){_SUFFIX})
  | (?P<percent>%\s?\d+(?:[.,]\d+)?{_SUFFIX}|\d+(?:[.,]\d+)?\s?%)
  | (?P<number>\d+(?:[.,]\d+)*{_SUFFIX})
  | (?P<dotabbr>(?:[A-ZÇĞİÖŞÜ]\.){{2,}}{_SUFFIX})
  | (?P<lowabbr>(?<![^\W\d_])(?:[a-zçğıöşü]\.){{2,}}[a-zçğıöşü]?(?![^\W\d_]){_SUFFIX})
  | (?P<word>[^\W\d_]+(?:[-'][^\W\d_]+)*)
  | (?P<punct>[.,;:!?…"'()\[\]{{}}\-/])
  | (?P<symbol>\S)
    """,
    re.VERBOSE,
)


def tokenize(
    text: str,
    start: int,
    end: int,
    abbreviations: Mapping[str, str] | None = None,
) -> list[Token]:
    """text[start:end] aralığını sözcük birimlerine ayırır. Ofsetler mutlak konumdur.

    abbreviations: kısaltma → okunuş eşlemesi (okunuş boş olabilir).
    """
    abbreviations = abbreviations or {}
    raw: list[tuple[str, TokenKind, int, int]] = []
    for m in TOKEN_RE.finditer(text, start, end):
        group = m.lastgroup or "symbol"
        kind: TokenKind = "word" if group in ("dotabbr", "lowabbr") else group  # type: ignore[assignment]
        raw.append((m.group(0), kind, m.start(), m.end()))

    words = [r for r in raw if r[1] == "word"]
    mostly_upper = bool(words) and sum(1 for w in words if is_upper_word(w[0])) >= max(
        3, int(len(words) * 0.6 + 0.5)
    )

    tokens: list[Token] = []
    first_word_seen = False
    for surface, kind, a, b in raw:
        base = surface.split("'", 1)[0]
        lower = turkish_lower(surface)
        is_abbr = False
        if kind == "word":
            letters = [c for c in base if c.isalpha()]
            in_lex = base in abbreviations or turkish_lower(base) in abbreviations
            dotted = "." in base
            upper = len(letters) >= 2 and is_upper_word(base)
            is_abbr = in_lex or dotted or (upper and not mostly_upper and len(letters) <= 6)
        sentence_initial = kind != "punct" and not first_word_seen
        if kind != "punct":
            first_word_seen = True
        tokens.append(
            Token(
                text=surface,
                lower=lower,
                kind=kind,
                start=a,
                end=b,
                base=base,
                is_abbreviation=is_abbr,
                is_capitalized=bool(surface[:1]) and surface[:1].isupper(),
                sentence_initial=sentence_initial,
                syllables=syllable_count(surface, kind, is_abbr, abbreviations),
            )
        )
    return tokens
