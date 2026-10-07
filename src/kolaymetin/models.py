"""Veri modelleri: Token, Sentence, Finding, Scores, Report ve iç Document yapısı."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

if TYPE_CHECKING:
    from kolaymetin.lexicon import Lexicon
    from kolaymetin.profiles import Profile
    from kolaymetin.text.normalize import NormalizedText

Severity = Literal["hata", "uyarı", "bilgi"]
Category = Literal["cümle", "kelime", "metin", "biçim"]
TokenKind = Literal[
    "word", "number", "punct", "url", "email", "date", "time", "percent", "symbol"
]

SEVERITY_ORDER: dict[str, int] = {"hata": 0, "uyarı": 1, "bilgi": 2}
CATEGORIES: tuple[Category, ...] = ("cümle", "kelime", "biçim", "metin")
WORDLIKE_KINDS = frozenset({"word", "number", "url", "email", "date", "time", "percent"})


class Analysis(BaseModel):
    """Bir kelimenin tek bir morfolojik çözümlemesi."""

    model_config = ConfigDict(frozen=True)

    word: str
    root: str
    lemma: str
    pos: str
    suffixes: tuple[str, ...] = ()
    stem_surface: str = ""
    suffix_surfaces: tuple[str, ...] = ()
    is_passive: bool = False
    is_negative: bool = False
    is_causative: bool = False
    is_converb: bool = False
    is_participle: bool = False
    is_nominalized: bool = False
    is_finite: bool = False
    is_genitive: bool = False
    is_proper: bool = False
    is_reflexive_candidate: bool = False
    suffix_count: int = 0
    source: Literal["zeyrek", "sezgisel"] = "zeyrek"
    confidence: float = 1.0
    flag_confidence: dict[str, float] = Field(default_factory=dict)

    def conf(self, flag: str) -> float:
        """Belirli bir işaretin (ör. is_passive) güveni."""
        return self.flag_confidence.get(flag, self.confidence)


class Token(BaseModel):
    text: str
    lower: str
    kind: TokenKind
    start: int
    end: int
    syllables: int = 0
    base: str = ""
    is_abbreviation: bool = False
    is_capitalized: bool = False
    sentence_initial: bool = False
    is_proper_name: bool = False  # özel ad (konuma, ad listesine ve metnin geri kalanına göre)
    analysis: Analysis | None = None

    @property
    def is_wordlike(self) -> bool:
        return self.kind in WORDLIKE_KINDS


class Sentence(BaseModel):
    index: int
    paragraph_index: int
    start: int
    end: int
    text: str
    is_heading: bool = False
    is_list_item: bool = False
    tokens: list[Token] = Field(default_factory=list, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def word_count(self) -> int:
        return sum(1 for t in self.tokens if t.is_wordlike)

    @property
    def words(self) -> list[Token]:
        return [t for t in self.tokens if t.is_wordlike]


class Paragraph(BaseModel):
    index: int
    start: int
    end: int
    sentence_indices: list[int] = Field(default_factory=list)
    suppressed: set[str] = Field(default_factory=set)


class Fix(BaseModel):
    """Bir bulgunun otomatik düzeltmesi: metnin [start, end) aralığı ``text`` olur.

    Yalnızca sonucu kesin olan düzeltmeler verilir ("01.12.2026" → "1 Aralık 2026 Salı").
    Aralık bulgunun aralığından farklı olabilir: noktalı virgülün düzeltmesi ardından gelen
    kelimeyi de büyük harfle başlatır."""

    start: int
    end: int
    text: str


class Finding(BaseModel):
    rule_id: str
    rule_name: str
    category: Category
    severity: Severity
    message: str
    explanation: str
    suggestion: str | None = None
    fix: Fix | None = None
    start: int
    end: int
    text: str = ""
    sentence_index: int | None = None
    paragraph_index: int | None = None
    confidence: float = 1.0
    rehber_url: str = ""

    def __str__(self) -> str:
        return f"{self.rule_id} [{self.severity}] {self.message}"


def applicable_fixes(findings: Iterable[Finding], length: int) -> list[Fix]:
    """Birlikte uygulanabilecek düzeltmeler, metindeki sırasıyla. Aralıkları çakışanlardan önce
    başlayan seçilir; öteki bir sonraki denetimde yeniden önerilir."""
    out: list[Fix] = []
    pos = 0
    for fx in sorted((f.fix for f in findings if f.fix is not None), key=lambda x: (x.start, x.end)):
        if fx.start >= pos and fx.end <= length:
            out.append(fx)
            pos = fx.end
    return out


def apply_fixes(text: str, findings: Iterable[Finding]) -> str:
    """Bulguların düzeltmelerini metne uygular. Ofsetler ``text`` içindedir (rapordaki gibi)."""
    parts: list[str] = []
    pos = 0
    for fx in applicable_fixes(findings, len(text)):
        parts.append(text[pos : fx.start])
        parts.append(fx.text)
        pos = fx.end
    parts.append(text[pos:])
    return "".join(parts)


class ReadabilityScore(BaseModel):
    name: str
    value: float | None
    level: str
    description: str
    grade: str | None = None


class CategoryScore(BaseModel):
    category: Category
    score: int | None  # metinde cümle yoksa None
    penalty: float
    finding_count: int


class RuleContribution(BaseModel):
    rule_id: str
    rule_name: str
    category: Category
    count: int
    penalty: float


class ComplianceScore(BaseModel):
    value: int | None  # metinde cümle yoksa None: skor hesaplanamaz
    # Yoksayılan bulgular da sayılsaydı skor ne olurdu? Yoksayma yoksa value ile aynı.
    raw_value: int | None = None
    ignored_count: int = 0
    penalty: float
    normalized: float
    k: float
    sentence_count: int
    reliable: bool = True
    note: str | None = None
    formula: str = ""
    weights: dict[str, float] = Field(default_factory=dict)
    by_category: list[CategoryScore] = Field(default_factory=list)
    contributions: list[RuleContribution] = Field(default_factory=list)


class Scores(BaseModel):
    atesman: ReadabilityScore
    cetinkaya_uzun: ReadabilityScore
    bezirci_yilmaz: ReadabilityScore
    compliance: ComplianceScore


class Stats(BaseModel):
    word_count: int
    sentence_count: int
    paragraph_count: int
    heading_count: int
    syllable_count: int
    avg_sentence_length: float
    avg_syllables_per_word: float
    longest_sentence_words: int
    longest_sentence_index: int | None


class Report(BaseModel):
    tool: str = "kolaymetin"
    version: str
    profile: str
    profile_title: str
    created_at: str
    morphology: str
    text: str
    sentences: list[Sentence]
    findings: list[Finding]
    # Kullanıcının "Yoksay" dediği bulgular: skora girmez ama raporda gösterilir.
    ignored_findings: list[Finding] = Field(default_factory=list)
    scores: Scores
    stats: Stats
    notes: list[str] = Field(default_factory=list)

    def __str__(self) -> str:
        """Kısa özet. ``print(report)`` bütün modeli değil, okunur bir özet yazar.

        Özet yalnızca Türkçe Windows konsolunun (cp1254) yazabildiği karakterleri içerir;
        ayrıntılar için ``to_markdown()`` ya da ``to_json()`` kullanın.
        """
        c = self.scores.compliance
        lines = [
            f"kolaymetin {self.version} - {self.profile_title}",
            f"Uyum skoru: {'—' if c.value is None else c.value}/100" + ("" if c.reliable else " (cümle az, güvenilir değil)"),
            f"Ateşman: {self.scores.atesman.value} ({self.scores.atesman.level})",
            f"{self.stats.word_count} kelime, {self.stats.sentence_count} cümle, "
            f"{len(self.findings)} bulgu",
        ]
        lines += [f"  {f}" for f in self.findings]
        return "\n".join(lines)

    def fixed_text(self) -> str:
        """Bütün otomatik düzeltmeler uygulanmış metin. Yoksayılan bulgular düzeltilmez."""
        return apply_fixes(self.text, self.findings)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_json(self, indent: int | None = 2) -> str:
        return self.model_dump_json(indent=indent)

    def to_markdown(self, base_url: str = "") -> str:
        """base_url: rehber bağlantılarının önüne eklenen adres ("https://…")."""
        from kolaymetin.io.exporters import to_markdown

        return to_markdown(self, base_url)

    def to_html(self, base_url: str = "") -> str:
        from kolaymetin.io.exporters import to_html

        return to_html(self, base_url)


@dataclass
class Document:
    """Kuralların üzerinde çalıştığı çözümlenmiş metin (normalleştirilmiş koordinatlarda)."""

    original: str
    normalized: NormalizedText
    paragraphs: list[Paragraph]
    sentences: list[Sentence]
    lexicon: Lexicon
    profile: Profile
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.normalized.text

    @property
    def body_sentences(self) -> list[Sentence]:
        """Başlık olmayan cümleler."""
        return [s for s in self.sentences if not s.is_heading]

    def words(self) -> list[Token]:
        return [t for s in self.sentences for t in s.words]

    def is_suppressed(self, rule_id: str, paragraph_index: int | None) -> bool:
        if paragraph_index is None or paragraph_index >= len(self.paragraphs):
            return False
        sup = self.paragraphs[paragraph_index].suppressed
        return "*" in sup or rule_id in sup
