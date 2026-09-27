"""Kural arayüzü ve kural kaydı (registry)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, ClassVar

from kolaymetin.models import Category, Document, Finding, Sentence, Severity, Token
from kolaymetin.profiles import RuleConfig

if TYPE_CHECKING:
    from kolaymetin.lexicon import PhraseMatch

REHBER_PREFIX = "/rehber/"


class Rule:
    """Bütün kuralların türediği temel sınıf.

    Alt sınıflar ``id``, ``name``, ``level``, ``default_severity``, ``summary`` alanlarını
    tanımlar ve ``check`` yöntemini uygular.
    """

    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    level: ClassVar[Category] = "cümle"
    default_severity: ClassVar[Severity] = "uyarı"
    summary: ClassVar[str] = ""

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        raise NotImplementedError

    # ------------------------------------------------------------------ yardımcılar
    @property
    def rehber_url(self) -> str:
        return f"{REHBER_PREFIX}{self.id}"

    def severity(self, cfg: RuleConfig, override: Severity | None = None) -> Severity:
        return override or cfg.severity or self.default_severity

    def finding(
        self,
        doc: Document,
        cfg: RuleConfig,
        start: int,
        end: int,
        message: str,
        explanation: str,
        suggestion: str | None = None,
        sentence: Sentence | None = None,
        severity: Severity | None = None,
        confidence: float = 1.0,
        paragraph_index: int | None = None,
    ) -> Finding:
        para = paragraph_index
        if para is None and sentence is not None:
            para = sentence.paragraph_index
        return Finding(
            rule_id=self.id,
            rule_name=self.name,
            category=self.level,
            severity=self.severity(cfg, severity),
            message=message,
            explanation=explanation,
            suggestion=suggestion,
            start=start,
            end=end,
            text=doc.text[start:end],
            sentence_index=sentence.index if sentence is not None else None,
            paragraph_index=para,
            confidence=round(max(0.0, min(1.0, confidence)), 2),
            rehber_url=self.rehber_url,
        )


_REGISTRY: dict[str, Rule] = {}


def register(cls: type[Rule]) -> type[Rule]:
    """Sınıf süsleyicisi: kuralı kayda ekler."""
    if not cls.id:
        raise ValueError("Kuralın kimliği (id) boş olamaz.")
    _REGISTRY[cls.id] = cls()
    return cls


def all_rules() -> list[Rule]:
    """Kayıtlı bütün kurallar, kimliğe göre sıralı."""
    order = {"cümle": 0, "kelime": 1, "biçim": 2, "metin": 3}
    return sorted(_REGISTRY.values(), key=lambda r: (order[r.level], r.id))


def get_rule(rule_id: str) -> Rule:
    return _REGISTRY[rule_id]


# ---------------------------------------------------------------------- ortak yardımcılar


def lexicon_matches(doc: Document, name: str) -> list[tuple[Sentence, PhraseMatch]]:
    """Bir sözlüğün metindeki eşleşmeleri. Birkaç kural aynı eşleşmelere baktığı için belge
    başına bir kez hesaplanır."""
    cache: dict[str, list[tuple[Sentence, PhraseMatch]]] = doc.meta.setdefault("lexicon_matches", {})
    if name not in cache:
        cache[name] = [
            (s, m) for s in doc.sentences for m in doc.lexicon.match(name, s.tokens)
            if not _inside_name(s, m)
        ]
    return cache[name]


def _inside_name(s: Sentence, m: PhraseMatch) -> bool:
    """Eşleşme çok kelimeli bir özel adın içinde mi? "Amed Sportif Faaliyetler" bir takımın,
    "Çaykur Rizespor" bir kulübün adıdır; yazar bu adı değiştiremez."""
    if s.is_heading:
        return False
    toks = [t for t in s.tokens[m.start_token : m.end_token] if t.kind == "word"]
    if not toks or not all(is_proper_noun(t) and t.is_capitalized for t in toks):
        return False
    before = [
        t for t in s.tokens[: m.start_token]
        if (t.kind != "punct" or t.text in ("'", "’")) and t.text not in ("&", ">", "/")
    ]
    return bool(before) and before[-1].kind == "word" and before[-1].is_capitalized


def lexicon_covered(doc: Document, names: tuple[str, ...]) -> set[int]:
    """Verilen sözlüklerin bir eşleşmesinin içinde kalan kelimelerin başlangıç konumları.

    Önerisi bütün ifadeyi değiştiren bir bulgunun (KD-K01 "rica olunur" → "lütfen") içindeki
    kelimeye ayrıca uzunluk, seyreklik ya da edilgenlik cezası kesilmez.
    """
    out: set[int] = set()
    for name in names:
        for s, m in lexicon_matches(doc, name):
            out.update(t.start for t in s.tokens[m.start_token : m.end_token])
    return out


def body_sentences(doc: Document) -> Iterator[Sentence]:
    """Başlık olmayan cümleler."""
    for s in doc.sentences:
        if not s.is_heading:
            yield s


def word_tokens(sentence: Sentence) -> list[Token]:
    return [t for t in sentence.tokens if t.kind == "word"]


def quote(text: str) -> str:
    return f"'{text}'"


def join_quoted(items: Iterable[str], limit: int = 4) -> str:
    items = list(dict.fromkeys(items))
    shown = ", ".join(quote(i) for i in items[:limit])
    if len(items) > limit:
        shown += " …"
    return shown


def is_proper_noun(token: Token) -> bool:
    """Cümle başında olmayan büyük harfli kelime, bilinen bir ad ya da morfolojide özel ad."""
    if token.kind != "word":
        return False
    if token.is_proper_name:
        return True
    if token.is_capitalized and not token.sentence_initial:
        return True
    if token.analysis is not None and token.analysis.is_proper and token.is_capitalized:
        return True
    return "'" in token.text and token.is_capitalized
