"""Paragraf ve cümle bölme.

Kısaltmalar, sıra sayıları, tarih/saat/ondalık sayılar, URL ve e-posta içindeki noktalar
cümle sonu sayılmaz. Madde işaretli listelerde her madde ayrı bir "cümle"dir. Kısa,
noktalamasız ve tek satırlık paragraflar başlık olarak işaretlenir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from kolaymetin.text.normalize import is_upper_word, turkish_lower

SUPPRESS_RE = re.compile(r"<!--\s*kolaymetin\s*:\s*yoksay\b(?P<ids>.*?)-->", re.IGNORECASE | re.S)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"]+", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PARA_SPLIT_RE = re.compile(r"\n[ ]*(?:\n[ ]*)+")
LIST_MARKER_RE = re.compile(
    r"^[ ]*(?:(?:[-*+•·▪◦‣]|\d{1,2}[.)]|[a-zçğıöşü][)])[ ]+|[-•](?=[A-ZÇĞİÖŞÜ]))"
)  # "-Güneş …": boşluksuz tire ardından büyük harf de madde işaretidir
MD_HEADING_RE = re.compile(r"^[ ]*#{1,6}[ ]+")
RULE_ID_RE = re.compile(r"KD-[CKBM]\d{2}", re.IGNORECASE)
TERMINAL_RE = re.compile(r"[.!?…]+")
CLOSERS = "\"')]}»”’"
OPENERS = "\"'([{«“‘"
# normalize() bütün tireleri "-", bütün çift tırnakları '"' yapar; yalın segment() çağrısı için
# özgün karakterler de tanınır.
DIALOGUE_DASHES = "-—–"
ROMAN_ORDINAL_RE = re.compile(r"^(?=.)(?:L?X{0,3})(?:IX|IV|V?I{0,3})$")
CITATION_RE = re.compile(r"(?:\[[^\]\n]{1,40}\])+")
QUOTE_RE = re.compile(r"“[^“”\n]{1,400}”")

# Sıra sayısından sonra sık gelen, büyük harfle yazılabilen adlar ("15. Madde").
ORDINAL_NOUNS = frozenset(
    {
        "madde", "maddesi", "fıkra", "fıkrası", "bent", "bendi", "kat", "katta", "sınıf",
        "sınıfı", "yüzyıl", "yüzyılda", "cadde", "caddesi", "sokak", "sokağı", "bölüm",
        "bölümü", "dönem", "dönemi", "hafta", "haftası", "gün", "günü", "yıl", "yılı",
        "sıra", "sırada", "etap", "etabı", "kısım", "ordu", "kolordu", "tümen", "cilt",
        "sayı", "sayfa", "baskı", "derece", "grup", "bölge", "bölgesi", "kademe",
    }
)

# Bu kısaltmalar cümlenin sonunda da olabilir; ardından büyük harf gelirse cümle biter.
SENTENCE_FINAL_ABBREVIATIONS = frozenset({"vb.", "vs.", "vd.", "vb", "vs", "vd", "a.ş.", "şti."})


@dataclass
class SentenceSpan:
    start: int
    end: int
    paragraph_index: int
    is_heading: bool = False
    is_list_item: bool = False


@dataclass
class ParagraphSpan:
    index: int
    start: int
    end: int
    suppressed: set[str] = field(default_factory=set)


@dataclass
class Segmentation:
    text: str  # yorumları boşlukla maskelenmiş metin (uzunluk aynı)
    paragraphs: list[ParagraphSpan]
    sentences: list[SentenceSpan]


def _mask(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _suppression_ids(raw: str) -> set[str]:
    ids = {m.group(0).upper() for m in RULE_ID_RE.finditer(raw)}
    return ids or {"*"}


def _has_content(text: str) -> bool:
    return any(c.isalnum() for c in text)


NUMBERED_RE = re.compile(r"^[ ]*\d{1,2}[.)][ ]+")
INNER_SENTENCE_END_RE = re.compile(r"(\S+)[.!?]+\s+[A-ZÇĞİÖŞÜ]")
_TITLE_ABBREVIATIONS = frozenset({"dr", "prof", "doç", "av", "müh", "uzm", "op", "yrd", "sn", "st"})


def _inner_sentence_end(line: str) -> bool:
    """Satırın ortasında bir cümle bitip yenisi başlıyor mu? "Prof. Dr. Ali" sayılmaz."""
    for m in INNER_SENTENCE_END_RE.finditer(line):
        word = m.group(1)
        if len(word) > 1 and word[-1].islower() and turkish_lower(word) not in _TITLE_ABBREVIATIONS:
            return True
    return False
_ORDINAL_START_RE = re.compile(r"^[ ]*\d{1,2}\.[ ]+(?P<next>\S+)")


def list_marker(line: str, in_list: bool = False) -> re.Match[str] | None:
    """Satır başındaki madde işareti.

    "15. yüzyılda …", "1. maddeye göre …", "3. Madde …" sıra sayısıyla başlayan cümledir, madde
    değil: ardından küçük harf ya da sıra sayısıyla kullanılan bir ad gelir. Aynı blokta başka
    numaralı satırlar da varsa (in_list) satır numaralı bir listenin maddesidir.
    """
    m = LIST_MARKER_RE.match(line)
    if m is None or in_list:
        return m
    o = _ORDINAL_START_RE.match(line)
    if o is not None:
        nxt = o.group("next").lstrip(OPENERS)
        first = nxt[:1]
        if first.isalpha() and first.islower():
            return None
        if turkish_lower(nxt.split("'", 1)[0]).rstrip(".,:;") in ORDINAL_NOUNS:
            return None
    return m


def _numbered_block(text: str, lines: list[tuple[int, int]]) -> bool:
    """Blokta en az iki numaralı satır var mı (numaralı liste)?"""
    return sum(1 for a, b in lines if NUMBERED_RE.match(text[a:b])) >= 2


SALUTATION_WORDS = frozenset(
    {"sayın", "değerli", "sevgili", "kıymetli", "saygıdeğer", "aziz", "merhaba", "selam",
     "iyi", "hemşehrilerimiz", "hemşerilerimiz", "komşularımız", "vatandaşlarımız"}
)


def _is_salutation(line: str) -> bool:
    """"Değerli Sakinlerimiz,", "Sayın Velimiz,", "Merhaba," gibi hitap satırı mı?"""
    stripped = line.strip()
    if not stripped.endswith(",") or LIST_MARKER_RE.match(line):
        return False
    words = stripped.rstrip(",").split()
    if not words or len(words) > 5 or not words[0][:1].isupper():
        return False
    if turkish_lower(words[0]) in SALUTATION_WORDS:
        return True
    return len(words) <= 3 and all(w[:1].isupper() for w in words if w[:1].isalpha())


# Başlık sayılmayan "Etiket: değer" satırları ("Telefon: 185", "Adres: …").
_LABELS = frozenset(
    {"telefon", "tel", "adres", "e-posta", "eposta", "faks", "web", "not", "kaynak", "saat",
     "tarih", "yer", "gsm", "iletişim", "ücret", "fiyat", "süre"}
)


def _colon_heading(stripped: str) -> bool:
    """Metnin ilk satırındaki "Su kesintisi: 15 Eylül", "DUYURU: Su Kesintisi" başlığı."""
    label, _, rest = stripped.partition(":")
    if ":" in rest or not label.strip() or not rest.strip():
        return False
    if turkish_lower(label.strip()) in _LABELS:
        return False
    return any(c.isalpha() for c in rest) and len(stripped.split()) <= 8


def _is_heading_line(line: str, allow_colon: bool = False) -> bool:
    stripped = line.strip()
    if not stripped or not _has_content(stripped):
        return False
    if stripped[-1] in ".!?;,:…":
        return False
    if list_marker(line) or "@" in stripped or "://" in stripped:
        return False
    if ":" in stripped and not (allow_colon and _colon_heading(stripped)):
        return False
    first = stripped.lstrip("#* \"'")[:1]
    if first.isalpha() and not first.isupper():
        return False
    words = stripped.split()
    return len(words) <= 12 and len(stripped) <= 100


def _protected_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    chunk = text[start:end]
    spans = []
    for rx in (URL_RE, EMAIL_RE):
        for m in rx.finditer(chunk):
            spans.append((start + m.start(), start + m.end()))
    return spans


def _in_spans(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def _prev_word(text: str, pos: int, lower_bound: int) -> str:
    """pos konumundan (hariç) geriye doğru boşluğa kadar olan parçayı döndürür."""
    i = pos
    while i > lower_bound and not text[i - 1].isspace():
        i -= 1
    return text[i:pos].lstrip(OPENERS)


def _next_word(text: str, pos: int, upper_bound: int) -> str:
    i = pos
    while i < upper_bound and text[i].isspace():
        i += 1
    j = i
    while j < upper_bound and not text[j].isspace():
        j += 1
    return text[i:j]


def _embedded_quotes(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Cümlenin içine gömülü “…” alıntıları: kapanış tırnağından sonra cümle küçük harfle
    sürer (“Ey iman edenler! … koruyun”[2] emr-i ilahisi gereğince …). Bu alıntının içindeki
    ünlem ve nokta cümleyi bitirmez."""
    pairs = [(m.start(), m.end()) for m in QUOTE_RE.finditer(text, start, end)]
    # Düz tırnaklar sırayla eşlenir (açılış, kapanış, açılış …); satır sonu eşleşmeyi keser.
    for line_start, line_end in _lines(text, start, end):
        marks = [i for i in range(line_start, line_end) if text[i] == '"']
        if len(marks) % 2 == 0:
            pairs += [(marks[k], marks[k + 1] + 1) for k in range(0, len(marks), 2)]
    spans = []
    for a, b in pairs:
        after = CITATION_RE.sub("", text[b : min(end, b + 60)]).lstrip(CLOSERS + " ")
        if after[:1].isalpha() and after[:1].islower():
            spans.append((a, b - 1))
    return spans


def split_sentences(
    text: str, start: int, end: int, abbreviations: frozenset[str]
) -> list[tuple[int, int]]:
    """[start, end) aralığını cümle aralıklarına böler."""
    protected = _protected_spans(text, start, end) + _embedded_quotes(text, start, end)
    bounds: list[tuple[int, int]] = []
    sent_start = start
    for m in TERMINAL_RE.finditer(text, start, end):
        if _in_spans(m.start(), protected):
            continue
        punct = m.group(0)
        stop = m.end()
        while stop < end and text[stop] in CLOSERS:
            stop += 1
        # Vikipedi kaynak işaretleri: "birleştirilir.[1] Daha sonra …"
        cite = CITATION_RE.match(text, stop, end)
        if cite:
            stop = cite.end()
        if stop < end and not text[stop].isspace():
            continue  # 3.5, 15.09.2026, "vb.," gibi durumlar
        nxt = _next_word(text, stop, end)
        if nxt:
            first = nxt.lstrip(OPENERS + "*")[:1]  # "*Cayma hakkı …" dipnot yıldızı
            rest = text[stop:end]
            gap_has_newline = "\n" in rest[: len(rest) - len(rest.lstrip())]
            starts_ok = first.isdigit() or (first.isalpha() and first.isupper())
            if first in DIALOGUE_DASHES:
                # Konuşma çizgisi yeni bir konuşmayı açar: "… döverim! — Söylemem."
                after_dash = rest.lstrip().lstrip(DIALOGUE_DASHES).lstrip()[:1]
                starts_ok = after_dash.isupper() or after_dash.isdigit()
            if gap_has_newline and not (first.isalpha() and first.islower()):
                starts_ok = True  # satır başında tırnak, tire ya da rakamla başlayan yeni cümle
            if not first and gap_has_newline:
                starts_ok = True
            if not starts_ok:
                continue
        if punct == ".":
            prev = _prev_word(text, m.start(), start)
            prev_l = turkish_lower(prev)
            if prev_l + "." in abbreviations and prev_l + "." not in SENTENCE_FINAL_ABBREVIATIONS:
                continue
            if len(prev) == 1 and prev.isalpha() and prev.isupper():
                continue  # baş harf: "A. Yılmaz"
            if ROMAN_ORDINAL_RE.match(prev) and nxt[:1].isupper():
                continue  # "II. Selim ve III. Murad", "XVI. yüzyıl"
            if prev.isdigit() and turkish_lower(nxt).strip("\"'(,") in ORDINAL_NOUNS:
                continue
        bounds.append((sent_start, stop))
        sent_start = stop
    if sent_start < end:
        bounds.append((sent_start, end))
    result = []
    for a, b in bounds:
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if a < b and _has_content(text[a:b]):
            result.append((a, b))
    return result


def _lines(text: str, start: int, end: int) -> list[tuple[int, int]]:
    out = []
    pos = start
    for line in text[start:end].split("\n"):
        out.append((pos, pos + len(line)))
        pos += len(line) + 1
    return out


def segment(text: str, abbreviations: frozenset[str]) -> Segmentation:
    """Metni paragraflara ve cümlelere böler. Ofsetler verilen metne göredir."""
    suppress_marks: list[tuple[int, set[str]]] = []
    for m in SUPPRESS_RE.finditer(text):
        suppress_marks.append((m.start(), _suppression_ids(m.group("ids"))))
    masked = text
    for m in COMMENT_RE.finditer(text):
        masked = _mask(masked, m.start(), m.end())

    raw_paras: list[tuple[int, int]] = []
    pos = 0
    for m in PARA_SPLIT_RE.finditer(masked):
        raw_paras.append((pos, m.start()))
        pos = m.end()
    raw_paras.append((pos, len(masked)))
    first_content = next((i for i, (a, b) in enumerate(raw_paras) if _has_content(masked[a:b])), 0)
    raw_paras = [
        p for i, (a, b) in enumerate(raw_paras)
        for p in _split_line_paragraphs(masked, a, b, first=i == first_content)
    ]
    title_start = next((a for a, b in raw_paras if _has_content(masked[a:b])), -1)

    paragraphs: list[ParagraphSpan] = []
    sentences: list[SentenceSpan] = []
    pending: set[str] = set()

    for p_start, p_end in raw_paras:
        marks_here = [ids for (mpos, ids) in suppress_marks if p_start <= mpos < p_end]
        if not _has_content(masked[p_start:p_end]):
            for ids in marks_here:
                pending |= ids
            continue
        a, b = p_start, p_end
        while a < b and masked[a].isspace():
            a += 1
        while b > a and masked[b - 1].isspace():
            b -= 1
        para = ParagraphSpan(index=len(paragraphs), start=a, end=b)
        para.suppressed |= pending
        pending = set()
        for ids in marks_here:
            para.suppressed |= ids
        paragraphs.append(para)
        sentences.extend(
            _segment_paragraph(masked, para, abbreviations, is_first=p_start == title_start)
        )

    for s in sentences:
        if s.is_list_item and _numbered_heading(masked, s.start, s.end):
            s.is_list_item = False
            s.is_heading = True
    return Segmentation(text=masked, paragraphs=paragraphs, sentences=sentences)


def _neighbour_line(text: str, pos: int, step: int) -> str | None:
    """pos'un bulunduğu satırdan önceki (step=-1) ya da sonraki (step=1) dolu satır."""
    if step < 0:
        end = text.rfind("\n", 0, pos)
        while end >= 0:
            start = text.rfind("\n", 0, end) + 1
            if _has_content(text[start:end]):
                return text[start:end]
            end = start - 1
        return None
    start = text.find("\n", pos)
    while start >= 0:
        end = text.find("\n", start + 1)
        line = text[start + 1 : end if end >= 0 else len(text)]
        if _has_content(line):
            return line
        start = end
    return None


def _numbered_heading(text: str, start: int, end: int) -> bool:
    """Numaralı ara başlık: "1. Bu Sözleşme" satırının ardından düz metin gelir, önünde de
    başka bir numaralı satır yoktur. Arka arkaya numaralı satırlar ise bir listedir."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = text[line_start : line_end if line_end >= 0 else len(text)]
    if not NUMBERED_RE.match(line) or text[end:line_end if line_end >= 0 else len(text)].strip():
        return False
    body = text[start:end].strip()
    if body[-1:] in ".!?;,:…" or not _starts_upper(body) or len(body.split()) > 8:
        return False
    prev, nxt = _neighbour_line(text, start, -1), _neighbour_line(text, start, 1)
    return not (
        nxt is None or LIST_MARKER_RE.match(nxt) or (prev is not None and NUMBERED_RE.match(prev))
    )


def _starts_upper(line: str) -> bool:
    first = line.strip().lstrip(OPENERS)[:1]
    return first.isdigit() or (first.isalpha() and first.isupper())


def _split_line_paragraphs(
    text: str, start: int, end: int, first: bool = False
) -> list[tuple[int, int]]:
    """Web sayfasından ya da Word'den yapıştırılan metinde paragraflar boş satırla değil,
    tek satır sonuyla ayrılır. Her satır bir cümleyle (ya da başlıkla, liste maddesiyle)
    bitiyorsa satır sonlarını paragraf sınırı sayar. Satır kaydırmalı metinde bazı satırlar
    cümlenin ortasında biter; o zaman aralık olduğu gibi kalır.
    """
    lines = [(a, b) for a, b in _lines(text, start, end) if _has_content(text[a:b])]
    if len(lines) < 3:
        return [(start, end)]
    in_list = _numbered_block(text, lines)
    sentence_lines = 0
    other_lines = 0  # noktalamasız biten ama ardından büyük harfle satır gelen düz satırlar
    # Virgül, noktalı virgül ya da iki noktayla biten satır cümlenin devamıdır: kesilmez.
    # Hitap satırı ("Değerli Sakinlerimiz,") virgülle biter ama ayrı durur.
    cuts: list[tuple[int, int]] = []  # (bu satırın sonu, sonraki satırın başı)
    for k, (a, b) in enumerate(lines):
        line = text[a:b].rstrip()
        nxt = text[lines[k + 1][0] : lines[k + 1][1]] if k + 1 < len(lines) else None
        next_item = nxt is not None and bool(list_marker(nxt, in_list))
        salutation = k == 0 and nxt is not None and _is_salutation(line) and _starts_upper(nxt)
        heading_like = _is_heading_line(line, allow_colon=first and k == 0)
        if line.rstrip(CLOSERS)[-1:] in ".!?…":
            sentence_lines += 1
        elif (
            salutation
            or line.endswith((":", ",", ";"))
            or list_marker(line, in_list)
            or MD_HEADING_RE.match(line)
            or (heading_like and (nxt is None or next_item or _starts_upper(nxt)))
        ):
            pass
        elif nxt is None or next_item or _starts_upper(nxt):
            other_lines += 1  # ör. nokta konmamış paragraf sonu: "… farkında olun"
        else:
            return [(start, end)]  # ardından küçük harf geliyor: satır kaydırması var
        if nxt is not None and (
            salutation
            or ((not next_item or heading_like) and not line.endswith((":", ",", ";")))
        ):
            cuts.append((b, lines[k + 1][0]))  # "Korunma Yolları" başlığı listeden ayrılır
    if sentence_lines < 2 or other_lines * 2 > sentence_lines:
        return [(start, end)]
    out = []
    pos = start
    for line_end, next_start in cuts:
        out.append((pos, line_end))
        pos = next_start
    out.append((pos, end))
    return out


def _segment_paragraph(
    text: str, para: ParagraphSpan, abbreviations: frozenset[str], is_first: bool = False
) -> list[SentenceSpan]:
    lines = [(a, b) for a, b in _lines(text, para.start, para.end) if _has_content(text[a:b])]
    out: list[SentenceSpan] = []
    if not lines:
        return out

    # Tek satırlık kısa, noktalamasız paragraf → başlık. Metnin ilk satırında iki noktalı
    # başlık da olur: "Su kesintisi: 15 Eylül".
    if len(lines) == 1 and _is_heading_line(text[lines[0][0] : lines[0][1]], allow_colon=is_first):
        a, b = lines[0]
        md = MD_HEADING_RE.match(text[a:b])
        if md:
            a += md.end()
        out.extend(_heading_spans(text, a, b, para.index, abbreviations))
        return out

    in_list = _numbered_block(text, lines)
    blocks: list[tuple[int, int, str]] = []  # (start, end, kind) kind: text|item|heading
    for i, (a, b) in enumerate(lines):
        line = text[a:b]
        md = MD_HEADING_RE.match(line)
        lm = list_marker(line, in_list)
        if md:
            blocks.append((a + md.end(), b, "heading"))
        elif (
            i == 0
            and len(lines) > 1
            and (
                (_is_heading_line(line) and is_upper_word(line) and len(line.split()) <= 10)
                or (is_first and ":" in line and _is_heading_line(line, allow_colon=True))
            )
        ):
            blocks.append((a, b, "heading"))
        elif i == 0 and len(lines) > 1 and _is_salutation(line) and _starts_upper(
            text[lines[1][0] : lines[1][1]]
        ):
            # Hitap satırı ("Değerli Sakinlerimiz,") ardından gelen cümleye eklenmez; kendi
            # başına kısa bir satırdır.
            blocks.append((a, b, "line"))
        elif lm:
            blocks.append((a + lm.end(), b, "item"))
        elif _standalone_line(text, lines, i, blocks):
            # Kapanmış bir cümleden sonra gelen, noktalamasız kısa satır ve ardından büyük
            # harfle başlayan satır: ara başlık ("Bina içindeyseniz") ya da tek başına bir
            # bilgi satırı ("10.01.2026 - 12.00"). Satır kaydırması değildir.
            first = line.strip().lstrip("#* \"'")[:1]
            blocks.append((a, b, "heading" if first.isalpha() else "line"))
        elif (
            blocks
            and blocks[-1][2] in ("text", "item")
            and not text[blocks[-1][0] : blocks[-1][1]].rstrip().endswith(":")
        ):
            s, _, kind = blocks[-1]
            blocks[-1] = (s, b, kind)  # satır kaydırması: önceki bloğa ekle
        else:
            blocks.append((a, b, "text"))

    for s, e, kind in blocks:
        if kind == "heading":
            out.extend(_heading_spans(text, s, e, para.index, abbreviations))
            continue
        for a, b in split_sentences(text, s, e, abbreviations):
            out.append(SentenceSpan(a, b, para.index, is_list_item=(kind == "item")))
    return out


def _heading_spans(
    text: str, a: int, b: int, para_index: int, abbreviations: frozenset[str]
) -> list[SentenceSpan]:
    """Başlık satırı. İçinde bir cümle bitip yenisi başlıyorsa ("Tam istediğim gibi oldu.
    Tşk ederim") başlık değil, noktası unutulmuş cümlelerdir."""
    if _inner_sentence_end(text[a:b]):
        return [SentenceSpan(x, y, para_index) for x, y in split_sentences(text, a, b, abbreviations)]
    return [SentenceSpan(*_trim(text, a, b), para_index, is_heading=True)]


def _standalone_line(
    text: str, lines: list[tuple[int, int]], i: int, blocks: list[tuple[int, int, str]]
) -> bool:
    line = text[lines[i][0] : lines[i][1]]
    if not _is_heading_line(line):
        return False
    if not blocks:
        return False  # paragrafın ilk satırı: başlık kuralı yukarıda ayrıca denetlenir
    s, e, kind = blocks[-1]
    closed = kind in ("heading", "line") or text[s:e].rstrip()[-1:] in ".!?…:"
    if not closed:
        return False
    if i + 1 >= len(lines):
        return True
    nxt = text[lines[i + 1][0] : lines[i + 1][1]]
    if list_marker(nxt, _numbered_block(text, lines)):
        return True
    first = nxt.strip().lstrip(OPENERS)[:1]
    return first.isdigit() or (first.isalpha() and first.isupper())


def _trim(text: str, a: int, b: int) -> tuple[int, int]:
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1].isspace():
        b -= 1
    return a, b
