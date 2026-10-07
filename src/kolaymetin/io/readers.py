"""Belge okuma: .txt, .md, .docx, .pdf"""

from __future__ import annotations

import io
import math
import re
from pathlib import Path

SUPPORTED = (".txt", ".md", ".markdown", ".docx", ".pdf")


class ReaderError(ValueError):
    """Belge okunamadı. Mesaj kullanıcıya gösterilir."""


def _utf16(data: bytes) -> str | None:
    """Not Defteri'nin "Unicode" kaydı UTF-16'dır. cp1254 her baytı çözdüğü için UTF-16 önce
    denenmezse metin "ÿşY\\x00a\\x00…" gibi bozulur."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        enc = "utf-16"
    elif len(data) >= 4 and data.count(0) * 3 >= len(data):
        # İşaretsiz UTF-16: Latin harflerinin baytlarından biri sıfırdır.
        enc = "utf-16-le" if data[1::2].count(0) > data[0::2].count(0) else "utf-16-be"
    else:
        return None
    try:
        return data.decode(enc)
    except UnicodeDecodeError:
        return None


def _decode(data: bytes) -> str:
    text = _utf16(data)
    if text is not None:
        return text
    for enc in ("utf-8-sig", "cp1254", "iso-8859-9"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")  # pragma: no cover - cp1254 her baytı çözer


def _read_docx(data: bytes) -> str:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - bağımlılık eksikse
        raise ReaderError("Word belgelerini okumak için python-docx kurulu olmalı.") from exc
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ReaderError("Word belgesi açılamadı. Dosya bozuk olabilir.") from exc
    blocks: list[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name if para.style is not None else "").lower()
        if "list" in style or "liste" in style:
            blocks.append(f"- {text}")
        else:
            blocks.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(" – ".join(cells))
    out: list[str] = []
    for block in blocks:
        if out and block.startswith("- ") and out[-1].startswith("- "):
            out[-1] += "\n" + block
        else:
            out.append(block)
    return "\n\n".join(out)


# Simge yazı tipleriyle (Wingdings) basılmış madde işaretleri PDF'ten harf olarak çıkar:
# "u Ürünün içinde …" (◆), "l Fişi çekin" (●), "n …" (■). Satır başında tek harf ve ardından
# büyük harfle başlayan kelime Türkçe bir cümle olamaz.
_SYMBOL_BULLET_RE = re.compile(r"(?m)^[ \t]*[lnquvØ§ü][ \t]+(?=[A-ZÇĞİÖŞÜ0-9])")


# Harfleri aralıklı yazılmış başlık: "G E Ç E N  Y I L", "M Ü T E R C İ M- T E R C Ü M A N".
# Harfler tek, kelimeler çift boşlukla ayrılır.
_LETTER_SPACED_RE = re.compile(r"(?<!\S)[^\W\d_]-?(?: [^\W\d_]-?){2,}(?!\S)")
_LETTER_SPACED_SHORT_RE = re.compile(r"(?<!\S)[^\W\d_]-?(?: [^\W\d_]-?)+(?!\S)")
# PDF dizgisinde noktalamadan önce kalan boşluk: "dokunur ." → "dokunur."
_SPACE_BEFORE_PUNCT_RE = re.compile(r"(?<=\w) +([.,;:!?])(?=\s|$)", re.M)
# Sayfa numaralı yinelenen üst/alt bilgi: "Topluma Hizmet Uygulamaları 12", "Sayfa 3", "3 / 12"
_PAGE_NUMBER_LINE_RE = re.compile(r"^(?:(?P<label>.*?\S)\s+)?(?:sayfa\s+)?\d{1,3}(?:\s*/\s*\d{1,3})?$", re.I)
_LINE_END_PUNCT = ".!?:;,…-–—"


def _edge_lines(lines: list[str]) -> list[str]:
    """Sayfanın ilk ve son dört dolu satırı: üst ve alt bilgi buralarda olur. pypdf metni çizim
    sırasıyla verir; slaytta alt bilgi başlığın hemen ardından da gelebilir."""
    filled = [ln for ln in lines if ln.strip()]
    return filled[:4] + filled[4:][-4:]


def _page_furniture(pages: list[list[str]]) -> set[str]:
    """Sayfaların çoğunun kenarında yinelenen üst/alt bilgi satırları (sayfa numarası atılmış
    hâliyle). Yalnızca bazı sayfalarda geçen "Adım 1", "Adım 2" gibi başlıklar sayılmaz."""
    if len(pages) < 3:
        return set()
    counts: dict[str, int] = {}
    for lines in pages:
        for label in {_furniture_key(ln) for ln in _edge_lines(lines)} - {""}:
            counts[label] = counts.get(label, 0) + 1
    limit = max(3, math.ceil(len(pages) * 0.6))
    return {label for label, n in counts.items() if n >= limit}


def _furniture_key(line: str) -> str:
    m = _PAGE_NUMBER_LINE_RE.match(line.strip())
    if m is None:
        # Numarasız satır yalnızca kısaysa, cümle değilse ve birebir aynıysa üst/alt bilgidir.
        stripped = line.strip()
        if len(stripped.split()) > 8 or stripped[-1:] in ".!?":
            return ""
        return "=" + stripped
    return "#" + (m.group("label") or "")


def _join_letter_spacing(line: str) -> str:
    """"G E Ç E N  Y I L" → "GEÇEN YIL". Satırda en az üç harflik aralıklı bir kelime varsa
    iki harflikler de ("B U  Y I L") birleşir."""
    if not _LETTER_SPACED_RE.search(line):
        return line
    joined = _LETTER_SPACED_SHORT_RE.sub(lambda m: m.group(0).replace(" ", ""), line)
    return re.sub(r"(?<=\S) {2,}(?=\S)", " ", joined)


def _tidy_pdf_pages(pages: list[str]) -> list[str]:
    """PDF'ten çıkan sayfa metinlerini düzenler.

    Sunum (slayt) PDF'lerinde başlık ve kısa bilgi satırları noktasızdır; satır satır birleşince
    80 kelimelik "cümleler" oluşuyordu. Noktasız, kısa bir satırdan sonra büyük harfle başlayan
    satır yeni bir paragraftır. Satırı kaydırılmış uzun düzyazı satırı bölünmez: uzunluğu
    sayfadaki en uzun satıra yakındır ya da sonraki satır küçük harfle başlar.
    """
    split = [[ln.rstrip() for ln in page.split("\n")] for page in pages]
    furniture = _page_furniture(split)
    out = []
    for lines in split:
        edges = set(_edge_lines(lines))
        lines = [ln for ln in lines if not (ln in edges and _furniture_key(ln) in furniture)]
        lines = [_join_letter_spacing(ln) for ln in lines]
        widest = max((len(ln.strip()) for ln in lines), default=0)
        kept: list[str] = []
        for i, ln in enumerate(lines):
            kept.append(ln)
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            cur = ln.strip()
            if (
                cur and nxt
                and cur[-1] not in _LINE_END_PUNCT
                and nxt[:1].isupper()
                and len(cur) < 0.6 * widest
            ):
                kept.append("")  # başlık ya da kısa bilgi satırı: sonraki satırla birleşmez
        out.append(_SPACE_BEFORE_PUNCT_RE.sub(r"\1", "\n".join(kept)).strip())
    return out


def _read_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ReaderError("PDF okumak için pypdf kurulu olmalı.") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        raise ReaderError("PDF açılamadı. Dosya bozuk ya da şifreli olabilir.") from exc
    text = "\n\n".join(p for p in _tidy_pdf_pages(pages) if p)
    text = _SYMBOL_BULLET_RE.sub("• ", text)
    if not any(c.isalpha() for c in text):
        raise ReaderError(
            "Bu PDF'te metin bulunamadı. Belge taranmış (resim olarak kaydedilmiş) olabilir. "
            "Metni kopyalayıp yapıştırın ya da Word belgesi yükleyin."
        )
    return text


def read_bytes(data: bytes, filename: str) -> str:
    """Yüklenen dosyanın içeriğini metne çevirir."""
    suffix = Path(filename).suffix.lower()
    if suffix in (".txt", ".md", ".markdown", ""):
        return _decode(data)
    if suffix == ".docx":
        return _read_docx(data)
    if suffix == ".pdf":
        return _read_pdf(data)
    raise ReaderError(
        f"Bu dosya türü desteklenmiyor: {suffix}. Desteklenen türler: .txt, .md, .docx, .pdf"
    )


def read_file(path: str | Path) -> str:
    p = Path(path)
    # Windows'ta klasörü açmaya çalışmak IsADirectoryError değil PermissionError verir.
    if p.is_dir():
        raise ReaderError(f"Bu bir klasör, dosya değil: {p}")
    try:
        data = p.read_bytes()
    except FileNotFoundError as exc:
        raise ReaderError(f"Dosya bulunamadı: {p}") from exc
    except IsADirectoryError as exc:
        raise ReaderError(f"Bu bir klasör, dosya değil: {p}") from exc
    except PermissionError as exc:
        raise ReaderError(f"Dosya okunamadı (izin yok): {p}") from exc
    return read_bytes(data, p.name)
