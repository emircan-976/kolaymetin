"""Belge okuma: .txt, .md, .docx, .pdf"""

from __future__ import annotations

import io
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
    text = "\n\n".join(p for p in pages if p)
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
