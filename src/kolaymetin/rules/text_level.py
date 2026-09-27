"""Metin ve paragraf düzeyi kurallar (KD-M01 … KD-M05)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from kolaymetin.models import Document, Finding
from kolaymetin.profiles import RuleConfig
from kolaymetin.rules.base import Rule, body_sentences, register
from kolaymetin.rules.format import date_in_name
from kolaymetin.text.normalize import turkish_lower
from kolaymetin.text.syllables import MONTHS

PHONE_RE = re.compile(
    r"(?<!\d)(?:\+90[\s-]?|0[\s-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)"
    r"|(?<!\d)444[\s.-]?\d{1,2}[\s.-]?\d{2}(?!\d)"
    r"|(?<!\d)1(?:12|53|55|56|77|22|10|84|86|70|71)(?!\d)(?=\s*(?:'|numara|nolu|hattı|hattını|'?yi|'?yı))",
    re.IGNORECASE,
)
SOURCE_LABELS = frozenset(
    {"kaynak", "kaynaklar", "kaynakça", "metin", "görsel", "görseller", "fotoğraf", "resim", "çizim"}
)
ADDRESS_WORDS = frozenset(
    {"mahallesi", "mah", "caddesi", "cad", "cd", "sokak", "sokağı", "sok", "sk", "bulvarı", "blv",
     "adres", "adresi", "adresimiz", "no", "numara"}
)


@register
class LongParagraph(Rule):
    id = "KD-M01"
    name = "Uzun paragraf"
    level = "metin"
    default_severity = "uyarı"
    summary = "Paragrafta çok fazla cümle var."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        max_sent = int(cfg.get("max_sentences", 5))
        for p in doc.paragraphs:
            sents = [
                doc.sentences[i] for i in p.sentence_indices
                if not doc.sentences[i].is_heading and not doc.sentences[i].is_list_item
            ]
            if len(sents) <= max_sent:
                continue
            yield self.finding(
                doc, cfg, sents[0].start, sents[-1].end,
                message=f"Bu paragraf çok uzun: {len(sents)} cümle. En fazla {max_sent} cümle yazın.",
                explanation="Uzun paragraf okuru yorar. Kısa paragraflar metni bölümlere ayırır.",
                suggestion="Paragrafı konularına göre ikiye bölün. Her bölüme bir ara başlık koyun.",
                paragraph_index=p.index,
            )


@register
class NoHeading(Rule):
    id = "KD-M02"
    name = "Başlık yok"
    level = "metin"
    default_severity = "bilgi"
    summary = "Uzun metinde başlık ya da ara başlık yok."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        min_words = int(cfg.get("min_words", 150))
        words = sum(s.word_count for s in doc.sentences)
        if words <= min_words or any(s.is_heading for s in doc.sentences) or not doc.sentences:
            return
        if _question_headings(doc):
            return  # "Asgari ödeme tutarı nasıl hesaplanır?" gibi soru biçimli ara başlıklar
        first = doc.sentences[0]
        yield self.finding(
            doc, cfg, first.start, first.end,
            message=f"Bu metinde başlık yok. Metin {words} kelime; başlık ve ara başlık ekleyin.",
            explanation="Başlıklar okura metnin neyle ilgili olduğunu hemen söyler. Okur aradığı bilgiyi kolay bulur.",
            suggestion="Metnin başına konuyu söyleyen kısa bir başlık yazın: 'Su kesintisi: 15 Eylül'.",
            sentence=first,
        )


def _question_headings(doc: Document) -> bool:
    """Metin soru-cevap biçiminde mi? Kendi paragrafında duran, soru işaretiyle biten kısa
    cümleler (en az iki) ara başlık işi görür."""
    count = 0
    for p in doc.paragraphs[:-1]:
        if len(p.sentence_indices) != 1:
            continue
        s = doc.sentences[p.sentence_indices[0]]
        if s.text.rstrip().endswith("?") and s.word_count <= 8:
            count += 1
    return count >= 2


DISCOURSE_MARKERS = frozenset(
    {"örneğin", "mesela", "ayrıca", "ancak", "fakat", "ama", "yani", "kısacası", "sonuç olarak",
     "özetle", "bu nedenle", "bu yüzden", "dolayısıyla", "evet", "hayır", "peki", "önce", "sonra",
     "ardından", "böylece", "bununla birlikte", "öte yandan", "aslında", "elbette", "tabii"}
)


@register
class ListOpportunity(Rule):
    id = "KD-M03"
    name = "Liste fırsatı"
    level = "metin"
    default_severity = "uyarı"
    summary = "Cümlede virgülle sıralanmış çok sayıda öğe var."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        min_items = int(cfg.get("min_items", 4))
        for s in body_sentences(doc):
            if s.is_list_item:
                continue
            segments: list[int] = [0]
            last_join = False
            for t in s.tokens:
                if t.kind == "punct" and t.text == ",":
                    segments.append(0)
                    last_join = False
                elif t.is_wordlike:
                    if turkish_lower(t.text) in ("ve", "veya", "ile", "ya", "yahut") and len(segments) > 1:
                        last_join = True
                    segments[-1] += 1
            if len(segments) > 1 and segments[0] == 1:
                first = next((t for t in s.tokens if t.is_wordlike), None)
                if first is not None and turkish_lower(first.text) in DISCOURSE_MARKERS:
                    segments = segments[1:]  # "Örneğin, AKP, MHP veya CHP": "Örneğin" öğe değil
            items = len(segments) + (1 if last_join else 0)
            short = sum(1 for n in segments if 0 < n <= 5)
            if items < min_items or short < min_items - 1:
                continue
            yield self.finding(
                doc, cfg, s.start, s.end,
                message=f"Bu cümlede {items} öğe sıralanmış. Bunu madde madde yazın.",
                explanation="Uzun sıralamaları cümle içinde takip etmek zordur. Liste bir bakışta okunur.",
                suggestion="Her öğeyi yeni bir satıra, başına '-' koyarak yazın.",
                sentence=s,
            )


def _important_positions(doc: Document) -> list[int]:
    positions: list[int] = []
    for m in PHONE_RE.finditer(doc.text):
        positions.append(m.start())
    for s in body_sentences(doc):
        toks = s.tokens
        first = next((t for t in toks if t.kind == "word"), None)
        if first is not None and turkish_lower(first.text) in SOURCE_LABELS:
            continue  # "Kaynak: https://…", "Metin: …" künye satırıdır, duyurunun bilgisi değil
        for i, t in enumerate(toks):
            if t.kind in ("date", "email", "url"):
                positions.append(t.start)
            elif t.kind == "word":
                low = turkish_lower(t.base).rstrip(".")
                if low in ADDRESS_WORDS:
                    positions.append(t.start)
                elif low in MONTHS and i > 0 and toks[i - 1].kind == "number" and not date_in_name(toks, i - 1):
                    positions.append(toks[i - 1].start)
    return sorted(positions)


@register
class KeyInfoLate(Rule):
    id = "KD-M04"
    name = "Önemli bilgi sonda"
    level = "metin"
    default_severity = "bilgi"
    summary = "Tarih, adres ya da telefon metnin başında değil, sonunda."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        frac = float(cfg.get("first_fraction", 0.3))
        body = list(body_sentences(doc))
        if len(body) < 3:
            return
        start, end = body[0].start, body[-1].end
        limit = start + (end - start) * frac
        positions = [p for p in _important_positions(doc) if p >= start]
        if not positions or positions[0] < limit:
            return
        first = positions[0]
        sent = next((s for s in body if s.start <= first < s.end), body[-1])
        yield self.finding(
            doc, cfg, sent.start, sent.end,
            message="En önemli bilgi (tarih, adres ya da telefon) metnin sonunda. En önemli bilgiyi başa yazın.",
            explanation="Birçok okur metnin yalnızca başını okur. Önemli bilgi sonda kalırsa gözden kaçar.",
            suggestion="Ne, ne zaman, nerede sorularının cevabını ilk cümlelere yazın.",
            sentence=sent,
        )


@register
class LongText(Rule):
    id = "KD-M05"
    name = "Çok uzun metin"
    level = "metin"
    default_severity = "bilgi"
    summary = "Metin Kolay Dil için çok uzun."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        max_words = int(cfg.get("max_words", 400))
        words = sum(s.word_count for s in doc.sentences)
        if words <= max_words or not doc.sentences:
            return
        first = doc.sentences[0]
        yield self.finding(
            doc, cfg, first.start, first.end,
            message=f"Metin çok uzun: {words} kelime. Metni kısaltın ya da bölümlere ayırın.",
            explanation="Uzun metin okuru yorar. Kolay Dil metinleri kısa tutulur.",
            suggestion="Yalnızca okurun bilmesi gereken bilgileri bırakın. Gerisini ayrı bir metne taşıyın.",
            sentence=first,
        )
