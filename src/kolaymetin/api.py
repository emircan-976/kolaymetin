"""Herkese açık kütüphane API'si.

    from kolaymetin import analyze
    report = analyze(text, profile="kolay-dil")
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Any

from kolaymetin import __version__
from kolaymetin import rules as _rules  # noqa: F401  (kuralları kayda ekler)
from kolaymetin.lexicon import Lexicon, load_lexicon
from kolaymetin.models import (
    SEVERITY_ORDER,
    Document,
    Finding,
    Paragraph,
    Report,
    Scores,
    Sentence,
    Stats,
    Token,
)
from kolaymetin.profiles import Profile, load_profile
from kolaymetin.readability import atesman, bezirci_yilmaz, cetinkaya_uzun, compliance, count
from kolaymetin.rules.base import all_rules
from kolaymetin.text import morphology
from kolaymetin.text.normalize import (
    fold_circumflex,
    is_latin,
    is_upper_word,
    normalize,
    turkish_lower,
)
from kolaymetin.text.segment import segment
from kolaymetin.text.syllables import syllable_count
from kolaymetin.text.tokenize import tokenize

MAX_CHARS = 100_000
DISCLAIMER = (
    "Bu araç yardımcıdır, hakem değildir. Bir Kolay Dil metnini ancak hedef okurlar doğrulayabilir. "
    "Metni hedef okurlarla test edin."
)


class InputTooLong(ValueError):
    """Metin izin verilen uzunluğu aşıyor."""


class EmptyInput(ValueError):
    """Metinde denetlenecek bir şey yok. Komut satırı ve web arayüzü aynı hatayı verir."""


LexiconSource = str | Path | dict[str, Any] | None


def build_document(
    text: str, profile: Profile, lexicon: Lexicon
) -> Document:
    """Metni normalleştirir, böler, sözcüklere ayırır ve çözümler."""
    nt = normalize(text)
    seg = segment(nt.text, lexicon.dotted_abbreviations())
    readings = lexicon.abbreviation_readings()
    paragraphs = [
        Paragraph(index=p.index, start=p.start, end=p.end, suppressed=set(p.suppressed))
        for p in seg.paragraphs
    ]
    sentences: list[Sentence] = []
    spans = [(span, tokenize(seg.text, span.start, span.end, readings)) for span in seg.sentences]
    proper_forms = _proper_forms([t for _span, toks in spans for t in toks], lexicon)
    for span, tokens in spans:
        words = [t for t in tokens if t.kind == "word"]
        exclamation = seg.text[span.start : span.end].rstrip().endswith("!")
        last_word = words[-1] if words else None
        clause_end = {
            tokens[i].start for i in range(len(tokens) - 1)
            if tokens[i].kind == "word"
            and turkish_lower(tokens[i + 1].text) in (";", ",", ":", "ve", "ama", "fakat", "ancak", "çünkü")
            # "yer yer ve zaman zaman": ikilemenin ikinci kelimesi yüklem değildir
            and not (i > 0 and turkish_lower(tokens[i - 1].text) == turkish_lower(tokens[i].text))
        }
        necessity = {
            words[i].start for i in range(len(words) - 1)
            if turkish_lower(words[i + 1].text).startswith(("gerek", "lazım", "şart"))
        }
        after_break = _after_break(tokens)
        contexts: dict[int, morphology.WordContext] = {}
        for t in words:
            if t.is_abbreviation and (
                _is_emphasized_word(t, readings) or _is_lowercase_word(t, lexicon)
            ):
                # "BUZLANMA VE DON UYARISI", "ÇÖK, KAPAN, TUTUN": vurgu için büyük harf
                t.is_abbreviation = False
                t.syllables = syllable_count(t.text, t.kind, False, readings)
            if t.is_abbreviation:
                continue
            initial = t.sentence_initial or t.start in after_break
            all_caps = _all_caps(t)
            proper = morphology.proper_position(
                t.is_capitalized, all_caps, initial, t is last_word, t.text
            )
            t.is_proper_name = proper or (
                t.is_capitalized and not all_caps and _form(t) in proper_forms
            )
            # "Numan Kurtulmuş konuştu. Kurtulmuş, … söyledi.": metnin başka yerinde özel ad olarak
            # geçen kelime cümle başında da fiil değildir.
            proper = proper or (t.is_proper_name and t is not last_word)
            ctx = morphology.WordContext(
                is_last=t is last_word,
                clause_end=t.start in clause_end,
                capitalized=t.is_capitalized,
                sentence_initial=initial,
                exclamation=exclamation,
                before_necessity=t.start in necessity,
                proper_noun=proper,
            )
            contexts[t.start] = ctx
            t.analysis = morphology.best(t.text, ctx)
        _coordinated_participles(words, contexts)
        # "New York'ta …", "Hijyen Kurulu …": cümle başındaki bilinmeyen kelime, ardından gelen
        # özel adın parçasıdır.
        for a, b in pairwise(words):
            if (
                a.sentence_initial and a.is_capitalized and not a.is_proper_name
                and b.is_proper_name and not b.sentence_initial
                and _form(a) not in lexicon.common_words
                and not morphology.is_dictionary_word(_form(a))
            ):
                a.is_proper_name = True
        s = Sentence(
            index=len(sentences),
            paragraph_index=span.paragraph_index,
            start=span.start,
            end=span.end,
            text=seg.text[span.start : span.end],
            is_heading=span.is_heading,
            is_list_item=span.is_list_item,
            tokens=tokens,
        )
        sentences.append(s)
        paragraphs[span.paragraph_index].sentence_indices.append(s.index)
    _unheading_trailing_sentences(sentences)
    return Document(
        original=text,
        normalized=nt,
        paragraphs=paragraphs,
        sentences=sentences,
        lexicon=lexicon,
        profile=profile,
    )


def _unheading_trailing_sentences(sentences: list[Sentence]) -> None:
    """Başlığın altında metin olur. Metnin sonunda, altında hiçbir cümle olmayan ve çekimli
    fiil taşıyan "başlık" ("Başvuruların ivedilikle yapılması gerekmektedir") noktası
    unutulmuş bir cümledir; başlık sayılırsa cümle kurallarının hiçbiri çalışmaz. Fiilsiz
    kapanış satırları ("Saygılarımızla", "Fen İşleri Müdürlüğü") başlık olarak kalır."""
    for s in reversed(sentences):
        if not s.is_heading:
            break
        if any(t.kind == "word" and t.analysis is not None and t.analysis.is_finite for t in s.tokens):
            s.is_heading = False


def _coordinated_participles(
    words: list[Token], contexts: dict[int, morphology.WordContext]
) -> None:
    """"soruları cevaplamış ve uygun bulunmuş kişiler": "ve" ile bağlanan iki sıfat-fiilden
    ilki, bağlaçtan önce geldiği için çekimli fiil (yüklem) sanılır. Eşi aynı ekle bitip bir adı
    niteliyorsa ("bulunmuş kişiler") ya da koşul kuruyorsa ("oluşmuş ise") o da sıfat-fiildir."""
    for k, t in enumerate(words[:-1]):
        a = t.analysis
        ctx = contexts.get(t.start)
        if a is None or ctx is None or not a.is_finite or not ctx.clause_end:
            continue
        if k == 0 and morphology.has_noun_reading(t.text):
            # "Astım ve akciğerde …", "Ürünün, …": cümlenin ilk kelimesi tek başına bir yan
            # cümle olamaz; ad okuması varsa ("astım", "ürün-ün") o seçilir.
            t.analysis = morphology.best(t.text, replace(ctx, clause_end=False))
            continue
        low = turkish_lower(t.text)
        if len(low) < 5:
            continue
        for u in words[k + 1 : k + 6]:
            if u is words[-1]:
                break
            b = u.analysis
            if _harmonic(turkish_lower(u.text))[-3:] == _harmonic(low)[-3:] and b is not None and not b.is_finite:
                t.analysis = morphology.best(t.text, replace(ctx, clause_end=False))
                break


_HARMONY = str.maketrans("ıiuüae", "IIIIAA")


def _harmonic(word: str) -> str:
    """Ünlü uyumunu yok sayan biçim: "cevaplamış" ile "bulunmuş" aynı ekle biter."""
    return word.translate(_HARMONY)


# Bu işaretlerden sonra gelen kelime yeni bir söz başlatır; büyük harfle başlaması onu özel ad
# yapmaz: "Dikkat: Kapılar kapanıyor", "“Gelmeyin” dedi", "(Evet)".
_BREAK_CHARS = frozenset(":\"'“”‘’«»([{-–—•…")


def _after_break(tokens: list[Token]) -> set[int]:
    out: set[int] = set()
    for prev, t in pairwise(tokens):
        if prev.kind in ("punct", "symbol") and prev.text in _BREAK_CHARS:
            out.add(t.start)
    return out


def _all_caps(token: Token) -> bool:
    return sum(1 for c in token.base if c.isalpha()) >= 2 and is_upper_word(token.base)


def _form(token: Token) -> str:
    return fold_circumflex(turkish_lower(token.base))


def _proper_forms(tokens: list[Token], lexicon: Lexicon) -> frozenset[str]:
    """Metinde özel ad olarak kullanılan kelime biçimleri.

    - Ad listesindeki adlar ("Ali", "Ayşe").
    - Ek alırken kesme işareti alan büyük harfli kelimeler ("Pıtır'ın", "Merkür'e").
    - Cümle başında en az iki kez büyük harfle geçen, metinde hiç küçük harfle geçmeyen ve
      temel kelime listesinde olmayan kelimeler (masal kahramanı "Pıtır").
    Cümle ortasındaki büyük harfli kelimeler konumlarından zaten özel ad sayılır.
    """
    names = morphology.known_names()
    vocabulary = lexicon.common_words | lexicon.known_words
    lower_seen: set[str] = set()
    caps_count: dict[str, int] = {}
    out: set[str] = set()
    for t in tokens:
        if t.kind != "word" or t.is_abbreviation or _all_caps(t):
            continue
        form = _form(t)
        if not t.is_capitalized:
            lower_seen.add(form)
            continue
        if form in names or "'" in t.text:
            out.add(form)
        caps_count[form] = caps_count.get(form, 0) + 1
    for form, n in caps_count.items():
        if n >= 2 and form not in lower_seen and form not in vocabulary:
            out.add(form)
    return frozenset(out)


def _is_emphasized_word(token: Token, readings: Mapping[str, str]) -> bool:
    """Tamamı büyük harfle yazılmış ama kısaltma değil, sıradan bir Türkçe kelime mi?

    Sözlükteki kısaltmalar ve noktalı kısaltmalar kısaltma kalır. Geri kalanı zeyrek
    kısaltma dışında bir çözümleme buluyorsa kelimedir ("VE", "DON", "ACİL", "ANKARA").
    """
    base = token.base
    low = turkish_lower(base)
    if "." in base or base in readings or low in readings:
        return False
    # "Keçiören/ANKARA", "TÜRKSAT": büyük harfle yazılmış özel ad, kısaltma değil
    return morphology.is_dictionary_word(low) or (len(low) >= 4 and morphology.is_proper_name(low))


def _is_lowercase_word(token: Token, lexicon: Lexicon) -> bool:
    """Küçük harfle yazılmış "kit", "ego", "ab" kelimedir; sözlükte büyük harfle geçen "KİT",
    "EGO", "AB" kısaltmalarıyla karışmaz. "kg", "vb" gibi küçük harfli girdiler kısaltma kalır."""
    base = token.base
    if "." in base or base != turkish_lower(base):
        return False
    entry = lexicon.find_abbreviation(base)
    return entry is not None and entry.short != turkish_lower(entry.short)


def _ignored_key(rule_id: str, text: str) -> tuple[str, str]:
    return rule_id, " ".join(turkish_lower(text).split())


def run_rules(doc: Document, ignored: Iterable[Mapping[str, str]] = ()) -> list[Finding]:
    """Profilde açık olan bütün kuralları çalıştırır."""
    ignore = {_ignored_key(str(i.get("rule_id", "")), str(i.get("text", ""))) for i in ignored}
    out: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in all_rules():
        cfg = doc.profile.rule(rule.id)
        if not cfg.enabled:
            continue
        for f in rule.check(doc, cfg):
            if doc.is_suppressed(f.rule_id, f.paragraph_index):
                continue
            key = (f.rule_id, f.start, f.end)
            if key in seen:
                continue
            seen.add(key)
            if _ignored_key(f.rule_id, f.text) in ignore:
                continue
            out.append(f)
    return out


def _to_original(doc: Document, findings: list[Finding], sentences: list[Sentence]) -> None:
    nt = doc.normalized
    for f in findings:
        f.start, f.end = nt.to_original(f.start, f.end)
        f.text = doc.original[f.start : f.end]
    for s in sentences:
        s.start, s.end = nt.to_original(s.start, s.end)
        s.text = doc.original[s.start : s.end]


NOT_TURKISH = (
    "Bu metin Türkçe görünmüyor. kolaymetin yalnızca Türkçe metinleri denetler. "
    "Skorlar ve bulgular yanlış olabilir."
)
# Türkçede kelime olarak geçmeyen İngilizce işlev kelimeleri ("on", "at", "can" Türkçe de olur).
_ENGLISH_FUNCTION_WORDS = frozenset(
    {"the", "and", "of", "to", "is", "are", "was", "were", "will", "be", "for", "with", "you",
     "your", "this", "that", "from", "have", "has", "please", "we", "our", "they", "not",
     "what", "which", "there", "would", "should", "been"}
)


def _looks_turkish(doc: Document) -> bool:
    """Metin Latin dışı bir yazıyla (Arapça, Kiril …) ya da İngilizce yazılmışsa False."""
    words = [t.text for s in doc.sentences for t in s.tokens if t.kind == "word"]
    if len(words) < 3:
        return True
    letters = [c for w in words for c in w if c.isalpha()]
    foreign_script = sum(1 for c in letters if not is_latin(c))
    if foreign_script * 2 > len(letters):
        return False
    english = sum(1 for w in words if turkish_lower(w) in _ENGLISH_FUNCTION_WORDS)
    return not (english >= 3 and english * 5 >= len(words))


def _stats(doc: Document) -> Stats:
    body = [s for s in doc.sentences if not s.is_heading and s.word_count]
    words = sum(s.word_count for s in body)
    syl = sum(t.syllables for s in body for t in s.words)
    longest = max(body, key=lambda s: s.word_count, default=None)
    return Stats(
        word_count=sum(s.word_count for s in doc.sentences),
        sentence_count=len(body),
        paragraph_count=len(doc.paragraphs),
        heading_count=sum(1 for s in doc.sentences if s.is_heading),
        syllable_count=syl,
        avg_sentence_length=round(words / len(body), 1) if body else 0.0,
        avg_syllables_per_word=round(syl / words, 2) if words else 0.0,
        longest_sentence_words=longest.word_count if longest else 0,
        longest_sentence_index=longest.index if longest else None,
    )


def analyze(
    text: str,
    profile: str | Profile | dict[str, Any] = "kolay-dil",
    custom_lexicon: LexiconSource | list[LexiconSource] = None,
    ignored: Iterable[Mapping[str, str]] = (),
    max_chars: int | None = MAX_CHARS,
) -> Report:
    """Metni denetler ve bir Rapor döndürür.

    profile: "kolay-dil", "sade-dil", bir YAML dosyasının yolu ya da Profile nesnesi.
    custom_lexicon: ek sözlük (YAML dosya yolu, YAML metni ya da dict) veya bunların listesi.
    ignored: [{"rule_id": "KD-K01", "text": "müracaat"}] biçiminde yoksayılacak bulgular.
    """
    if max_chars is not None and len(text) > max_chars:
        raise InputTooLong(
            f"Metin çok uzun: {len(text):,} karakter. En fazla {max_chars:,} karakter "
            "denetlenebilir. Metni bölümlere ayırın.".replace(",", ".")
        )
    if not text.strip():
        raise EmptyInput("Metin boş. Denetlemek için bir metin yazın ya da yapıştırın.")
    prof = load_profile(profile)
    extras = custom_lexicon if isinstance(custom_lexicon, list) else [custom_lexicon]
    lexicon = load_lexicon(*extras)
    doc = build_document(text, prof, lexicon)
    findings = run_rules(doc, ignored)
    findings.sort(key=lambda f: (f.start, SEVERITY_ORDER[f.severity], f.rule_id))

    tc = count(doc.sentences)
    body_count = sum(1 for s in doc.sentences if not s.is_heading and s.word_count)
    scores = Scores(
        atesman=atesman.score(tc),
        cetinkaya_uzun=cetinkaya_uzun.score(tc),
        bezirci_yilmaz=bezirci_yilmaz.score(tc),
        compliance=compliance.compute(findings, body_count, prof.compliance_k, prof.weights),
    )
    stats = _stats(doc)
    sentences = [s.model_copy() for s in doc.sentences]
    _to_original(doc, findings, sentences)

    notes = [DISCLAIMER]
    if not _looks_turkish(doc):
        notes.append(NOT_TURKISH)
    if scores.compliance.note:
        notes.append(scores.compliance.note)
    backend = morphology.backend_name()
    if backend != "zeyrek":
        notes.append(
            "Morfolojik çözümleyici (zeyrek) kullanılamadı; ek tabanlı sezgisel çözümleme "
            "kullanıldı. Bazı bulguların güveni düşüktür."
        )
    return Report(
        version=__version__,
        profile=prof.name,
        profile_title=prof.title or prof.name,
        created_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        morphology=backend,
        text=text,
        sentences=sentences,
        findings=findings,
        scores=scores,
        stats=stats,
        notes=notes,
    )
