"""Biçim ve sayı kuralları (KD-B01 … KD-B08)."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable

from kolaymetin.models import Document, Finding, Sentence, Token
from kolaymetin.profiles import RuleConfig
from kolaymetin.rules.base import Rule, body_sentences, quote, register
from kolaymetin.text.morphology import best, vocabulary_keys
from kolaymetin.text.normalize import is_upper_word, turkish_capitalize, turkish_lower
from kolaymetin.text.syllables import MONTHS, date_parts, read_number

NUMBER_WORDS = {
    "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8,
    "dokuz": 9, "on": 10, "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50, "altmış": 60,
    "yetmiş": 70, "seksen": 80, "doksan": 90, "yüz": 100, "bin": 1000,
    "milyon": 1_000_000, "milyar": 1_000_000_000,
}
UNAMBIGUOUS_SINGLE = frozenset(
    {"on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan", "milyon", "milyar"}
)
WEEKDAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
WEEKDAYS_LOWER = frozenset(turkish_lower(w) for w in WEEKDAYS)
MONTHS_TITLE = [turkish_capitalize(m) for m in MONTHS]
UNITS_AFTER_NUMBER = frozenset(
    {"tl", "lira", "kuruş", "kg", "kilo", "km", "metre", "m", "cm", "mm", "lt", "litre", "%",
     "derece", "ton", "gram", "dolar", "euro", "avro"}
)
ADDRESS_LABELS = frozenset({"no", "kat", "daire", "d", "blok", "posta kodu", "pk"})
ROMAN_RE = re.compile(r"^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$")
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def format_thousands(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def parse_number_words(words: list[str]) -> int:
    total = 0
    current = 0
    for w in words:
        val = NUMBER_WORDS[w]
        if val >= 1000:
            current = max(current, 1) * val
            total += current
            current = 0
        elif val == 100:
            current = max(current, 1) * 100
        else:
            current += val
    return total + current


def roman_to_int(text: str) -> int:
    total = 0
    prev = 0
    for ch in reversed(text):
        val = ROMAN_VALUES[ch]
        total = total - val if val < prev else total + val
        prev = max(prev, val)
    return total


def _last_vowel(text: str) -> str:
    for c in reversed(turkish_lower(text)):
        if c in "aeıioöuü":
            return c
    return "e"


def possessive(n: int) -> str:
    """Sayıya 3. tekil iyelik eki: 35'i, 20'si, 50'si, 6'sı."""
    reading = read_number(str(n)).replace(" ", "")
    v = _last_vowel(reading)
    harmony = {"a": "ı", "ı": "ı", "o": "u", "u": "u", "e": "i", "i": "i", "ö": "ü", "ü": "ü"}[v]
    ends_vowel = reading[-1] in "aeıioöuü"
    return f"{n}'{'s' if ends_vowel else ''}{harmony}"


def _number_base(token: Token) -> str | None:
    if token.kind != "word":
        return None
    low = turkish_lower(token.base)
    if low in NUMBER_WORDS:
        return low
    a = token.analysis
    if a is not None and a.pos == "Num" and turkish_lower(a.lemma) in NUMBER_WORDS:
        return turkish_lower(a.lemma)
    return None


@register
class NumbersInWords(Rule):
    id = "KD-B01"
    name = "Yazıyla yazılmış sayı"
    level = "biçim"
    default_severity = "uyarı"
    summary = "Büyük sayılar yazıyla yazılmış; rakamla yazılmalı."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        min_value = int(cfg.get("min_value", 10))
        for s in body_sentences(doc):
            run: list[tuple[Token, str]] = []
            prev: Token | None = None
            for t in [*s.tokens, None]:
                base = _number_base(t) if t is not None else None
                if base is not None and t is not None and not run and prev is not None and prev.kind == "number":
                    base = None  # "100 milyon", "2,5 milyar": sayı zaten rakamla yazılmış
                prev = t
                if base is not None and t is not None:
                    run.append((t, base))
                    if t.text != t.base or (t.analysis is not None and t.analysis.suffix_count):
                        yield from self._emit(doc, cfg, s, run, min_value)
                        run = []
                    continue
                if run:
                    yield from self._emit(doc, cfg, s, run, min_value)
                    run = []

    def _emit(
        self, doc: Document, cfg: RuleConfig, s: Sentence, run: list[tuple[Token, str]], min_value: int
    ) -> Iterable[Finding]:
        words = [b for _t, b in run]
        if len(words) == 1 and words[0] not in UNAMBIGUOUS_SINGLE:
            return
        value = parse_number_words(words)
        if value < min_value:
            return
        text = " ".join(t.text for t, _ in run)
        digits = format_thousands(value)
        yield self.finding(
            doc, cfg, run[0][0].start, run[-1][0].end,
            message=f"{quote(text)} sayısını rakamla yazın: {digits}.",
            explanation="Rakamı okumak, yazıyla yazılmış sayıyı okumaktan daha kolaydır.",
            suggestion=f"{quote(text)} → {quote(digits)}",
            sentence=s,
        )


@register
class RomanNumeral(Rule):
    id = "KD-B02"
    name = "Roma rakamı"
    level = "biçim"
    default_severity = "uyarı"
    summary = "Roma rakamı kullanılmış."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s in doc.sentences:
            toks = s.tokens
            for i, t in enumerate(toks):
                if t.kind != "word" or not t.text or not ROMAN_RE.match(t.text):
                    continue
                nxt = toks[i + 1].text if i + 1 < len(toks) else ""
                if len(t.text) < 2 and (nxt != "." or t.text not in "IVX"):
                    continue  # "Robert M.", "D. F." ad baş harfleridir
                if nxt != "." and not set(t.text) <= set("IVX"):
                    continue  # "CD", "CV", "DC", "MD": kısaltma; Roma rakamı hemen hep noktalıdır
                if doc.lexicon.find_abbreviation(t.text) is not None:
                    continue
                value = roman_to_int(t.text)
                end = toks[i + 1].end if nxt == "." else t.end
                shown = t.text + ("." if nxt == "." else "")
                arabic = f"{value}." if nxt == "." else str(value)
                yield self.finding(
                    doc, cfg, t.start, end,
                    message=f"{quote(shown)} bir Roma rakamı. Yerine {quote(arabic)} yazın.",
                    explanation="Roma rakamlarını birçok kişi okuyamaz.",
                    suggestion=f"{quote(shown)} → {quote(arabic)}",
                    sentence=s,
                )


_FRACTION_WORDS = {
    (1, 2): "yarısı", (1, 3): "üçte biri", (2, 3): "üçte ikisi", (1, 4): "çeyreği",
    (3, 4): "dörtte üçü",
}
_PERCENT_WORDS = {
    10: "onda biri", 20: "beşte biri", 25: "dörtte biri", 33: "üçte biri", 40: "beşte ikisi",
    50: "yarısı", 60: "beşte üçü", 66: "üçte ikisi", 67: "üçte ikisi", 75: "dörtte üçü",
    80: "beşte dördü", 90: "onda dokuzu", 100: "hepsi",
}
# Yüzdenin neyin oranı olduğu: kişiler mi, para mı, başka bir şey mi ("kumaşın yüzde 70'i").
_PEOPLE_WORDS = frozenset(
    {"kişi", "insan", "vatandaş", "halk", "nüfus", "çocuk", "öğrenci", "kadın", "erkek", "çalışan",
     "işçi", "seçmen", "hasta", "yaşlı", "aile", "hane", "katılımcı", "genç", "bebek", "emekli",
     "memur", "veli", "öğretmen", "doktor", "sakin", "kullanıcı", "müşteri", "başvuran",
     "yetişkin", "engelli", "toplum", "üye", "tüketici", "yolcu", "sürücü", "birey",
     "hanehalkı", "okur", "izleyici", "dinleyici", "personel"}
)
_MONEY_WORDS = frozenset(
    {"faiz", "kesinti", "indirim", "zam", "vergi", "ücret", "fiyat", "lira", "tl", "ödeme", "ceza",
     "iade", "kdv", "maaş", "borç", "kredi", "prim", "aidat", "bedel", "tutar", "para",
     "enflasyon", "kira", "komisyon", "harç", "fatura", "kur", "getiri", "kâr", "kar", "zarar",
     "bütçe", "gider", "masraf", "peşinat", "taksit"}
)


def _percent_context(toks: list[Token], i: int) -> str:
    """Yüzdeye en yakın ipucu kelimeye bakar: 'kişi', 'para' ya da ''."""
    best_dist, kind = 99, ""
    for j, t in enumerate(toks):
        if t.kind != "word" or j == i:
            continue
        keys = vocabulary_keys(t.text)
        found = "kişi" if keys & _PEOPLE_WORDS else "para" if keys & _MONEY_WORDS else ""
        if found and abs(j - i) < best_dist:
            best_dist, kind = abs(j - i), found
    return kind


def _percent_hint(value: int, context: str, shown: str = "") -> str:
    """shown: sayının yazıldığı biçim ("35,5"); küsuratlı yüzdede öneride o kullanılır."""
    shown = shown or str(value)
    if value > 100:
        if value % 100 == 0:
            return f"Şöyle yazın: '{value // 100} katı'."
        return "Somut bir örnek verin: 'Önce 100 lira olan fiyat şimdi … lira.'"
    if context == "kişi":
        if value == 50:
            return "Şöyle yazın: 'her 2 kişiden 1'i' ya da 'yarısı'."
        return f"Şöyle açıklayın: '100 kişiden {possessive(value)}'."
    if context == "para":
        return f"Somut bir örnek verin: '100 lirada {shown} lira'."
    if value in _PERCENT_WORDS:
        return f"Şöyle yazın: '… {_PERCENT_WORDS[value]}'."
    return f"Somut bir örnek verin ya da kesirle söyleyin: '100'de {possessive(value)}'."


# "2.5 milyon", "1.75 kg": İngilizcedeki gibi noktayla yazılmış küsurat. "15.000" binliktir.
_DOT_DECIMAL_RE = re.compile(r"^\d+\.\d{1,2}$")
_DECIMAL_UNITS = UNITS_AFTER_NUMBER | {"milyon", "milyar", "bin", "yıl", "saat", "kat"}


@register
class PercentFraction(Rule):
    id = "KD-B03"
    name = "Yüzde ve kesir"
    level = "biçim"
    default_severity = "bilgi"
    summary = "Yüzde ya da kesir kullanılmış; somut bir açıklama eklenebilir."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s in body_sentences(doc):
            toks = s.tokens
            for i, t in enumerate(toks):
                value: int | None = None
                shown = ""
                start, end = t.start, t.end
                if t.kind == "percent":
                    digits = re.sub(r"[^\d]", "", t.base.split(",")[0].split(".")[0])
                    value = int(digits) if digits else None
                elif (
                    t.kind == "word" and turkish_lower(t.text) == "yüzde"
                    and i + 1 < len(toks) and toks[i + 1].kind == "number"
                ):
                    # "yüzde 35,5": küsurat yüz katına çıkmasın (355 değil)
                    number = toks[i + 1].base.split("'", 1)[0]
                    digits = re.sub(r"[^\d]", "", re.split(r"[.,]", number)[0])
                    value = int(digits) if digits else None
                    shown = number
                    end = toks[i + 1].end
                elif (
                    t.kind == "number" and i + 2 < len(toks) and toks[i + 1].text == "/"
                    and toks[i + 2].kind == "number" and toks[i + 1].start == t.end
                    and toks[i + 2].start == toks[i + 1].end
                    and t.base.isdigit() and toks[i + 2].base.isdigit()
                ):
                    a, b = int(t.base), int(toks[i + 2].base)
                    if 0 < a < b <= 10:
                        word = _FRACTION_WORDS.get((a, b), f"{b} parçadan {a} parça")
                        yield self._make(doc, cfg, s, t.start, toks[i + 2].end,
                                         f"{a}/{b}", f"Kesir yerine şöyle yazın: {quote(word)}.")
                    continue
                elif t.kind == "number" and _DOT_DECIMAL_RE.match(t.base) and (
                    i + 1 < len(toks) and turkish_lower(toks[i + 1].base) in _DECIMAL_UNITS
                ):
                    comma = t.base.replace(".", ",")
                    yield self.finding(
                        doc, cfg, t.start, t.end,
                        message=f"{quote(t.base)} sayısında nokta var. Küsuratı virgülle yazın: {quote(comma)}.",
                        explanation=(
                            "Türkçede nokta binlikleri ayırır. Okur '2.5 milyon' sayısını yanlış "
                            "okuyabilir."
                        ),
                        suggestion=f"{quote(t.base)} → {quote(comma)}",
                        sentence=s,
                        severity="uyarı",
                    )
                    continue
                if value is None:
                    continue
                hint = _percent_hint(value, _percent_context(toks, i), shown)
                yield self._make(doc, cfg, s, start, end, doc.text[start:end], hint)

    def _make(
        self, doc: Document, cfg: RuleConfig, s: Sentence, start: int, end: int, shown: str, hint: str
    ) -> Finding:
        return self.finding(
            doc, cfg, start, end,
            message=f"{quote(shown)} yüzde ya da kesir. Bunu herkes kolay anlamayabilir.",
            explanation="Yüzde ve kesir soyut kavramlardır. Somut bir örnek anlamayı kolaylaştırır.",
            suggestion=hint,
            sentence=s,
        )


def _parse_date(text: str) -> dt.date | None:
    parts = date_parts(text)
    if parts is None:
        return None
    d, m, y = parts
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _weekday_after(toks: list[Token], i: int) -> Token | None:
    """toks[i]'de biten tarihten hemen sonra yazılmış haftanın günü: "1 Aralık 2026 Salı",
    "01.12.2026 (Salı)", "01.12.2026, Salı"."""
    for t in toks[i + 1 : i + 4]:
        if t.kind == "word":
            return t if turkish_lower(t.base) in WEEKDAYS_LOWER else None
        if t.text not in "(,-":
            return None
    return None


def _is_past_year(year: int) -> bool:
    """Geçmiş bir yıl mı? Haftanın günü yalnızca yakın ya da gelecek tarihler için önerilir."""
    return year < dt.date.today().year - 1


def date_in_name(toks: list[Token], i: int) -> bool:
    """toks[i] gün, toks[i+1] ay: tarih bir özel adın parçası mı ("1 Kasım İlkokulu")?"""
    if i + 2 >= len(toks):
        return False
    after = toks[i + 2]
    return (
        after.kind == "word"
        and after.is_capitalized
        and turkish_lower(after.base) not in WEEKDAYS_LOWER
        and turkish_lower(after.base) not in MONTHS
    )


_RANGE_JOINERS = frozenset({"-", "–", "—", "ile", "ila"})


def _is_date_part(t: Token) -> bool:
    return t.kind in ("date", "number") or (
        t.kind == "word" and turkish_lower(t.base) in MONTHS
    )


def _range_start(toks: list[Token], i: int) -> bool:
    """toks[i]'de başlayan tarih bir aralığın ilk ucu mu ("6 Şubat - 2 Mart", "15-20 Eylül")?"""
    j = i + 1
    while j < len(toks) and _is_date_part(toks[j]) and toks[j].kind != "date":
        j += 1  # ay adı ve yıl
    if j + 1 >= len(toks):
        return False
    joiner = toks[j]
    return turkish_lower(joiner.text) in _RANGE_JOINERS and toks[j + 1].kind in ("number", "date")


def _range_end(toks: list[Token], i: int) -> int | None:
    """toks[i]'de başlayan tarih bir aralığın son ucu mu? Öyleyse birleştiricinin konumu."""
    if i < 2:
        return None
    joiner = toks[i - 1]
    if turkish_lower(joiner.text) not in _RANGE_JOINERS:
        return None
    return i - 1 if _is_date_part(toks[i - 2]) else None


def _readable(date: dt.date, weekday: bool = True) -> str:
    base = f"{date.day} {MONTHS_TITLE[date.month - 1]} {date.year}"
    return f"{base} {WEEKDAYS[date.weekday()]}" if weekday else base


@register
class DateFormat(Rule):
    id = "KD-B04"
    name = "Tarih biçimi"
    level = "biçim"
    default_severity = "uyarı"
    summary = "Tarih rakam ve noktayla yazılmış ya da haftanın günü eksik."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        weekday = bool(cfg.get("suggest_weekday", True))
        for s in body_sentences(doc):
            toks = s.tokens
            for i, t in enumerate(toks):
                if t.kind == "date":
                    date = _parse_date(t.base)
                    if date is None:
                        yield self._invalid(doc, cfg, s, t.start, t.end, t.base)
                        continue
                    written = _weekday_after(toks, i)
                    if written is not None and turkish_lower(written.base) != turkish_lower(
                        WEEKDAYS[date.weekday()]
                    ):
                        yield self._wrong_weekday(doc, cfg, s, t.start, written.end, date, written.base)
                        continue
                    # Tarih aralığında ("01.11.2026 - 15.11.2026") iki uca da gün eklemek metni
                    # uzatır; yalnızca ayın adı önerilir.
                    in_range = _range_end(toks, i) is not None or _range_start(toks, i)
                    readable = _readable(
                        date, weekday=weekday and not in_range and not _is_past_year(date.year)
                    )
                    yield self.finding(
                        doc, cfg, t.start, t.end,
                        message=f"{quote(t.base)} tarihini ayın adıyla yazın: {quote(readable)}.",
                        explanation=(
                            "Rakamlarla yazılan tarihte gün ile ay karışabilir. Ayın adı ve "
                            "haftanın günü tarihi daha anlaşılır yapar."
                        ),
                        suggestion=f"{quote(t.base)} → {quote(readable)}",
                        sentence=s,
                    )
                elif t.kind == "number" and t.base.isdigit() and 1 <= int(t.base) <= 31:
                    if i + 1 >= len(toks) or toks[i + 1].kind != "word":
                        continue
                    month_tok = toks[i + 1]
                    month_low = turkish_lower(month_tok.base)
                    if month_low not in MONTHS:
                        continue
                    has_year = (
                        i + 2 < len(toks) and toks[i + 2].kind == "number" and len(toks[i + 2].base) == 4
                    )
                    if not date_in_name(toks, i):
                        year_or_none = int(toks[i + 2].base) if has_year else None
                        problem = self._check_written(
                            doc, cfg, s, toks, i, int(t.base), MONTHS.index(month_low) + 1, year_or_none
                        )
                        if problem is not None:
                            yield problem
                            continue
                    if not weekday:
                        continue
                    window = toks[max(0, i - 3) : i + 5]
                    if any(turkish_lower(w.base) in WEEKDAYS_LOWER for w in window if w.kind == "word"):
                        continue
                    if date_in_name(toks, i):
                        continue  # "1 Kasım İlkokulu", "19 Mayıs Stadyumu"
                    if _range_start(toks, i) or _range_end(toks, i) is not None:
                        continue  # "6 Şubat - 2 Mart 2026": aralıkta haftanın günü gerekmez
                    end_tok = month_tok
                    year = None
                    if i + 2 < len(toks) and toks[i + 2].kind == "number" and len(toks[i + 2].base) == 4:
                        end_tok = toks[i + 2]
                        year = int(toks[i + 2].base)
                        if _is_past_year(year):
                            continue  # "23 Nisan 1920": tarihî olayın haftanın günü gerekmez
                    hint = "Haftanın gününü de yazın. Örnek: '15 Eylül Salı'."
                    if year:
                        date = dt.date(year, MONTHS.index(month_low) + 1, int(t.base))
                        hint = f"Haftanın gününü de yazın: {quote(_readable(date))}."
                    yield self.finding(
                        doc, cfg, t.start, end_tok.end,
                        message="Bu tarihte haftanın günü yok. Günü de yazın.",
                        explanation="Birçok kişi günleri tarihle değil, haftanın günüyle takip eder.",
                        suggestion=hint,
                        sentence=s,
                        severity="bilgi",
                    )

    def _check_written(
        self, doc: Document, cfg: RuleConfig, s: Sentence, toks: list[Token], i: int,
        day: int, month: int, year: int | None,
    ) -> Finding | None:
        """Ayın adıyla yazılmış tarih ("31 Şubat 2026", "1 Aralık 2026 Pazartesi") gerçek mi,
        haftanın günü doğru mu?"""
        last = i + 2 if year is not None else i + 1
        shown = doc.text[toks[i].start : toks[last].end]
        try:
            date = dt.date(year if year is not None else 2024, month, day)  # 2024: 29 Şubat var
        except ValueError:
            return self._invalid(doc, cfg, s, toks[i].start, toks[last].end, shown)
        if year is None:
            return None  # yıl yoksa haftanın günü denetlenemez
        written = _weekday_after(toks, last)
        if written is None or turkish_lower(written.base) == turkish_lower(WEEKDAYS[date.weekday()]):
            return None
        return self._wrong_weekday(doc, cfg, s, toks[i].start, written.end, date, written.base)

    def _invalid(
        self, doc: Document, cfg: RuleConfig, s: Sentence, start: int, end: int, shown: str
    ) -> Finding:
        return self.finding(
            doc, cfg, start, end,
            message=f"{quote(shown)} gerçek bir tarih değil. Günü ve ayı denetleyin.",
            explanation=(
                "Takvimde olmayan bir tarih okuru şaşırtır. Okur başvuruyu ya da randevuyu "
                "kaçırabilir."
            ),
            suggestion="Doğru tarihi ayın adıyla yazın. Örnek: '15 Eylül 2026 Salı'.",
            sentence=s,
            severity="hata",
        )

    def _wrong_weekday(
        self, doc: Document, cfg: RuleConfig, s: Sentence, start: int, end: int,
        date: dt.date, written: str,
    ) -> Finding:
        right = WEEKDAYS[date.weekday()]
        return self.finding(
            doc, cfg, start, end,
            message=(
                f"{quote(_readable(date, weekday=False))} bir {right} günü. "
                f"Metinde {quote(written)} yazıyor."
            ),
            explanation=(
                "Tarih ile haftanın günü birbirini tutmazsa okur hangisine inanacağını bilemez. "
                "Yanlış gün gelebilir."
            ),
            suggestion=f"Günü düzeltin: {quote(_readable(date))}.",
            sentence=s,
            severity="hata",
        )


@register
class TimeFormat(Rule):
    id = "KD-B05"
    name = "Saat biçimi"
    level = "biçim"
    default_severity = "uyarı"
    summary = "Saat, önünde 'saat' kelimesi olmadan yazılmış."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s in body_sentences(doc):
            toks = s.tokens
            covered = False
            for i, t in enumerate(toks):
                if t.kind != "time":
                    if t.kind == "word" and turkish_lower(t.text) not in ("ile", "ve", "arası"):
                        covered = False
                    continue
                nxt = turkish_lower(toks[i + 1].text) if i + 1 < len(toks) else ""
                if nxt in UNITS_AFTER_NUMBER:
                    continue
                prev_words = [p for p in toks[max(0, i - 2) : i] if p.kind == "word"]
                if any(turkish_lower(p.base) == "saat" for p in prev_words):
                    covered = True
                    continue
                if covered:
                    continue
                shown = t.base.replace(":", ".")
                yield self.finding(
                    doc, cfg, t.start, t.end,
                    message=f"{quote(t.base)} bir saat mi, bir sayı mı? Önüne 'saat' yazın.",
                    explanation=(
                        "'14.30' gibi yazımlar ondalık sayıyla karışabilir. 'Saat' kelimesi "
                        "belirsizliği giderir."
                    ),
                    suggestion=f"{quote(t.base)} → {quote('saat ' + shown)}",
                    sentence=s,
                )
                covered = True


@register
class SemicolonColon(Rule):
    id = "KD-B06"
    name = "Noktalı virgül / iki nokta yoğunluğu"
    level = "biçim"
    default_severity = "uyarı"
    summary = "Cümlede noktalı virgül ya da çok sayıda iki nokta var."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        max_colons = int(cfg.get("max_colons", 1))
        for s in body_sentences(doc):
            colons = [
                t for i, t in enumerate(s.tokens)
                if t.kind == "punct" and t.text == ":"
                and not (i > 0 and turkish_lower(s.tokens[i - 1].text) in ADDRESS_LABELS)
            ]
            for t in s.tokens:
                if t.kind == "punct" and t.text == ";":
                    yield self.finding(
                        doc, cfg, t.start, t.end,
                        message="Bu cümlede noktalı virgül var. Noktalı virgül yerine nokta koyun.",
                        explanation=(
                            "Noktalı virgül iki cümleyi birleştirir. Okur cümlenin nerede "
                            "bittiğini anlamakta zorlanır."
                        ),
                        suggestion="';' yerine '.' koyun ve yeni cümleye büyük harfle başlayın.",
                        sentence=s,
                    )
            if len(colons) > max_colons:
                t = colons[max_colons]
                yield self.finding(
                    doc, cfg, t.start, t.end,
                    message=f"Bu cümlede {len(colons)} tane iki nokta (:) var. Cümleyi bölün.",
                    explanation="Çok sayıda iki nokta cümleyi karmaşık yapar.",
                    suggestion="Her bilgiyi ayrı bir satıra ya da maddeye yazın.",
                    sentence=s,
                )


@register
class AllCaps(Rule):
    id = "KD-B07"
    name = "Tamamen büyük harf"
    level = "biçim"
    default_severity = "uyarı"
    summary = "Uzun bir bölüm tamamen büyük harfle yazılmış."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        max_words = int(cfg.get("max_words", 3))
        for s in doc.sentences:
            run: list[Token] = []
            for t in [*s.tokens, None]:
                if t is not None and t.kind == "punct":
                    continue
                upper = (
                    t is not None
                    and t.kind == "word"
                    and sum(1 for c in t.base if c.isalpha()) >= 2
                    and is_upper_word(t.base)
                )
                if upper and t is not None:
                    run.append(t)
                    continue
                if len(run) > max_words:
                    text = doc.text[run[0].start : run[-1].end]
                    fixed = turkish_capitalize(text) if text else text
                    yield self.finding(
                        doc, cfg, run[0].start, run[-1].end,
                        message=f"Bu bölüm tamamen büyük harfle yazılmış ({len(run)} kelime). Normal yazın.",
                        explanation=(
                            "Büyük harfle yazılan kelimelerin biçimi birbirine benzer. Okumak "
                            "yavaşlar. Ekran okuyucular bazen harf harf okur."
                        ),
                        suggestion=f"Şöyle yazın: {quote(fixed)}",
                        sentence=s,
                    )
                run = []


_QUOTE_RE = re.compile(r'"([^"\n]{1,60})"')
_QUOTE_FOLLOWERS = frozenset(
    {"diye", "dedi", "der", "demek", "adlı", "isimli", "başlıklı", "yazan", "yazılı", "olarak",
     "kelimesi", "kelimesini", "sözü", "denir", "deyin", "yazın"}
)


_QUOTE_CHAIN_RE = re.compile(r'^(?:\s*,?\s*(?:ve|veya|ya da|ile)?\s*"[^"\n]{1,60}")+')


def _is_quote_follower(word: str) -> bool:
    """Aktarma fiili ya da adlandırma sözü mü ("der", "dediğinde", "diye", "adlı")?"""
    if word in _QUOTE_FOLLOWERS:
        return True
    a = best(word)
    return a is not None and a.lemma == "demek"


@register
class ScareQuotes(Rule):
    id = "KD-B08"
    name = "Tırnak içinde vurgu ya da ironi"
    level = "biçim"
    default_severity = "bilgi"
    summary = "Tırnak işareti vurgu ya da ironi için kullanılmış olabilir."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s in body_sentences(doc):
            for m in _QUOTE_RE.finditer(s.text):
                inner = m.group(1).strip()
                words = inner.split()
                if not words or len(words) > 3:
                    continue
                before = s.text[max(0, m.start() - 2) : m.start()]
                if ":" in before:
                    continue
                # '"evet" veya "hayır" der': sıralanan öteki alıntıları atlayıp fiile bak
                rest = _QUOTE_CHAIN_RE.sub("", s.text[m.end() :])
                after = rest.split()
                if after and _is_quote_follower(turkish_lower(after[0].strip(".,;:!?"))):
                    continue
                if all(w[:1].isupper() for w in words if w[:1].isalpha()):
                    continue  # özel ad ya da başlık
                yield self.finding(
                    doc, cfg, s.start + m.start(), s.start + m.end(),
                    message=f"{quote(inner)} tırnak içinde. Bu bir vurgu mu? Tırnak alay gibi de anlaşılabilir.",
                    explanation=(
                        "Tırnak işareti bazen 'aslında öyle değil' anlamı taşır. Okur bu "
                        "anlamı yanlış çıkarabilir."
                    ),
                    suggestion="Vurgu için tırnağı kaldırın ya da kelimeyi kalın yazın.",
                    sentence=s,
                )
