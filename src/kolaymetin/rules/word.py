"""Kelime düzeyi kurallar (KD-K01 … KD-K08)."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable

from kolaymetin.lexicon import PhraseMatch
from kolaymetin.models import Document, Finding, Sentence, Token
from kolaymetin.profiles import RuleConfig
from kolaymetin.rules.base import (
    Rule,
    body_sentences,
    is_proper_noun,
    lexicon_covered,
    lexicon_matches,
    quote,
    register,
)
from kolaymetin.text.morphology import all_lemmas, heuristic_stem, vocabulary_keys
from kolaymetin.text.normalize import fold_circumflex, is_latin, turkish_lower, turkish_upper
from kolaymetin.text.syllables import count_vowels

ROMAN_RE = re.compile(r"^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$")


def _span(sentence: Sentence, m: PhraseMatch) -> tuple[int, int, str]:
    toks = sentence.tokens[m.start_token : m.end_token]
    start, end = toks[0].start, toks[-1].end
    return start, end, " ".join(t.text for t in toks if t.kind != "punct")


_lexicon_matches = lexicon_matches


@register
class Jargon(Rule):
    id = "KD-K01"
    name = "Bürokratik ifade / jargon"
    level = "kelime"
    default_severity = "uyarı"
    summary = "Resmî yazışma dilinden gelen, halkın zor anladığı ifade."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s, m in _lexicon_matches(doc, "jargon"):
            start, end, text = _span(s, m)
            oneri = m.entry.suggestion
            if oneri.startswith("(") and oneri.endswith(")"):
                # Karşılığı olmayan kalıp: öneri bir yönergedir, "tarafından" → "(işi yapanı
                # cümlenin başına yazın)".
                instruction = oneri[1:-1].strip()
                instruction = turkish_upper(instruction[:1]) + instruction[1:]
                yield self.finding(
                    doc, cfg, start, end,
                    message=f"{quote(text)} resmî ve eski bir ifade. {instruction}.",
                    explanation=(
                        "Bürokratik kalıpları çok kişi bilmez. Okurun her gün kullandığı "
                        "söyleyişi seçin."
                    ),
                    suggestion=f"{instruction}.",
                    sentence=s,
                )
                continue
            yield self.finding(
                doc, cfg, start, end,
                message=f"{quote(text)} resmî ve eski bir ifade. Yerine {quote(oneri)} yazın."
                if oneri else f"{quote(text)} resmî ve eski bir ifade. Günlük bir kelime seçin.",
                explanation=(
                    "Bürokratik kelimeleri çok kişi bilmez. Okurun her gün kullandığı "
                    "kelimeyi seçin."
                ),
                suggestion=f"{quote(text)} → {quote(oneri)}" if oneri else None,
                sentence=s,
            )
        yield from self._formal_imperatives(doc, cfg)

    def _formal_imperatives(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        """"-(y)InIz" ile kurulan resmî emir: "doldurunuz", "teslim ediniz" → "doldurun"."""
        covered = lexicon_covered(doc, ("jargon",))  # "müracaat ediniz" zaten işaretli
        for s in body_sentences(doc):
            for t in s.tokens:
                a = t.analysis
                if t.kind != "word" or a is None or t.start in covered:
                    continue
                if a.suffixes[-2:] != ("Imp", "A2pl") or not _FORMAL_IMPERATIVE_RE.search(
                    a.suffix_surfaces[-1] if a.suffix_surfaces else ""
                ):
                    continue
                plain = t.text[:-2]
                yield self.finding(
                    doc, cfg, t.start, t.end,
                    message=f"{quote(t.text)} resmî bir emir. Yerine {quote(plain)} yazın.",
                    explanation=(
                        "'-iniz' ile biten emir resmî yazışma dilidir. Kısa emir ('doldurun', "
                        "'gelin') hem kibar hem kolaydır."
                    ),
                    suggestion=f"{quote(t.text)} → {quote(plain)}",
                    sentence=s,
                )


_FORMAL_IMPERATIVE_RE = re.compile(r"[ıiuü]n[ıiuü]z$")


@register
class ForeignWord(Rule):
    id = "KD-K02"
    name = "Yabancı kelime"
    level = "kelime"
    default_severity = "uyarı"
    summary = "Türkçe karşılığı olan yabancı kökenli kelime."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s, m in _lexicon_matches(doc, "foreign"):
            start, end, text = _span(s, m)
            oneri = m.entry.suggestion
            yield self.finding(
                doc, cfg, start, end,
                message=f"{quote(text)} yabancı kökenli bir kelime. Türkçesini kullanın: {quote(oneri)}.",
                explanation=(
                    "Yabancı kelimeleri özellikle yaşlılar ve okuma güçlüğü yaşayanlar bilmeyebilir."
                ),
                suggestion=f"{quote(text)} → {quote(oneri)}" if oneri else None,
                sentence=s,
            )


def _is_roman(token: Token) -> bool:
    return bool(token.text) and bool(ROMAN_RE.match(token.text)) and token.text.isupper()


@register
class Abbreviation(Rule):
    id = "KD-K03"
    name = "Açıklanmamış kısaltma"
    level = "kelime"
    default_severity = "uyarı"
    summary = "Kısaltma, ilk geçtiği yerde açıklanmamış."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        seen: set[str] = set()
        folded_text = fold_circumflex(turkish_lower(doc.text))
        sentences = doc.sentences
        for si, s in enumerate(sentences):
            # Açılım kısaltmadan önce ya da hemen sonraki cümlede olabilir:
            # "TBMM'yi Tanıyalım" başlığı, ardından "TBMM: Türkiye Büyük Millet Meclisi demek."
            limit = sentences[min(si + 1, len(sentences) - 1)].end
            toks = s.tokens
            for i, t in enumerate(toks):
                if t.kind != "word" or not t.is_abbreviation or _is_roman(t):
                    continue
                if doc.text[t.end : t.end + 1].isdigit():
                    continue  # kodun parçası: IBAN "TR12 0006 …", "H1N1", "A4"
                key = t.base.rstrip(".")
                if key in seen:
                    continue
                seen.add(key)
                entry = doc.lexicon.find_abbreviation(t.base) or doc.lexicon.find_abbreviation(key)
                if entry is not None and entry.well_known:
                    continue
                if self._explained(toks, i, entry, folded_text, limit):
                    continue
                if entry is not None and entry.expansion:
                    suggestion = (
                        f"İlk geçtiği yerde açık yazın: '{entry.expansion} ({key})'. "
                        f"Ya da yalnızca {quote(entry.expansion)} yazın."
                    )
                else:
                    suggestion = "Kısaltmanın açık hâlini ilk geçtiği yerde parantez içinde yazın."
                yield self.finding(
                    doc, cfg, t.start, t.end,
                    message=f"{quote(t.base)} bir kısaltma. Metinde ilk geçtiği yerde açıklayın.",
                    explanation=(
                        "Okur kısaltmanın ne anlama geldiğini bilmeyebilir. Harf harf okunan "
                        "kısaltmalar ekran okuyucularda da anlaşılmaz."
                    ),
                    suggestion=suggestion,
                    sentence=s,
                )

    @staticmethod
    def _explained(
        toks: list[Token], i: int, entry: object, folded_text: str, limit: int
    ) -> bool:
        # "Sosyal Güvenlik Kurumu (SGK)" → kısaltma parantez içinde, önünde büyük harfli kelimeler
        if i > 0 and toks[i - 1].text == "(" and i + 1 < len(toks) and toks[i + 1].text == ")":
            caps = [t for t in toks[max(0, i - 6) : i - 1] if t.kind == "word" and t.is_capitalized]
            # Açılımın bir kelimesi kısaltmanın ilk harfiyle başlamalı: "Peygamber Efendimiz
            # (s.a.s)" bir açıklama değildir.
            initial = turkish_lower(toks[i].text[:1])
            if len(caps) >= 2 and any(turkish_lower(t.text[:1]) == initial for t in caps):
                return True
        # "SGK (Sosyal Güvenlik Kurumu)" → ardından parantez içinde en az iki kelime
        if i + 1 < len(toks) and toks[i + 1].text == "(":
            words = 0
            for t in toks[i + 2 :]:
                if t.text == ")":
                    break
                if t.kind == "word":
                    words += 1
            if words >= 2:
                return True
        expansion = getattr(entry, "expansion", "")
        if expansion:
            needle = fold_circumflex(turkish_lower(expansion))
            idx = folded_text.find(needle)
            if 0 <= idx < limit:
                return True
        return False


# Kelimenin sonundan atılabilen çekim ekleri (ve yüzeyi olmayan sözcük türü işaretleri).
_TRAILING_INFLECTIONS = frozenset(
    {"A1sg", "A2sg", "A3sg", "A1pl", "A2pl", "A3pl", "P1sg", "P2sg", "P3sg", "P1pl", "P2pl",
     "P3pl", "Acc", "Dat", "Loc", "Abl", "Gen", "Ins", "Equ", "Nom", "Cop", "Pnon", "Noun", "Adj",
     "Verb", "Pres"}
)
_COUNTED_INFLECTIONS = frozenset(
    {"A3pl", "P1sg", "P2sg", "P3sg", "P1pl", "P2pl", "P3pl", "Acc", "Dat", "Loc", "Abl", "Gen",
     "Ins", "Equ"}
)


def _core(t: Token) -> tuple[str, int]:
    """Çekim ekleri atılmış gövde ve atılan (yüzeyi olan) çekim eki sayısı.

    "ellerinizi" → ("el", 3), "alınacaktır" → ("alınacak", 1),
    "değerlendirilmesinden" → ("değerlendirilme", 2).
    """
    a = t.analysis
    word = fold_circumflex(turkish_lower(t.base))
    if a is None or a.source != "zeyrek" or not a.stem_surface:
        stem, count = heuristic_stem(t.base)
        return stem, count
    ids = list(a.suffixes)
    surfaces = list(a.suffix_surfaces)
    removed = 0
    while ids and ids[-1] in _TRAILING_INFLECTIONS:
        if surfaces[-1] and ids[-1] in _COUNTED_INFLECTIONS:
            removed += 1
        ids.pop()
        surfaces.pop()
    core = turkish_lower(a.stem_surface + "".join(surfaces))
    return (core if core else word), removed


def _long_word_hint(t: Token, core: str) -> str:
    """Kelimeyi uzatan şeye göre öneri: edilgen, ad-fiil, "-ebil", iyelik/çoğul, uzun kök."""
    a = t.analysis
    ids = a.suffixes if a is not None else ()
    word = quote(t.text)
    if "Pass" in ids:
        return (
            f"{word} edilgen ekle uzamış. İşi yapanı söyleyin ve kısa bir fiil kullanın. "
            "Örnek: 'verilebilecektir' → 'Belediye verecek.'"
        )
    if any(x in ids for x in ("Inf1", "Inf2", "Inf3", "ActOf")):
        return (
            f"{word} bir eylemin ada dönüşmüş hâli. Eylemi fiille söyleyin. Örnek: 'teslim "
            "edilmesinden sonra' → 'Teslim edin. Sonra …'"
        )
    if "Able" in ids or "Unable" in ids:
        return (
            f"{word} '-ebil' ekiyle uzamış. Doğrudan söyleyin. Örnek: 'başvurabilirsiniz' → "
            "'başvurun'."
        )
    if a is not None and any(x in ids for x in ("P1pl", "P2pl", "P3pl")) and "A3pl" in ids:
        root = quote(turkish_lower(a.lemma))
        return (
            f"Çoğul ve iyelik ekleri kelimeyi uzatıyor. Kökü {root}. Okura 'siz' diye seslenin "
            "ya da tekil söyleyin. Örnek: 'vatandaşlarımıza' → 'size'."
        )
    if a is not None and a.suffix_count > 2 and "-" not in a.lemma:
        return f"Ekleri azaltın ya da cümleyi ikiye bölün. Kelimenin kökü {quote(turkish_lower(a.lemma))}."
    if a is not None and a.suffix_count > 2:
        return "Ekleri azaltın ya da cümleyi ikiye bölün."  # "siyah-beyazlılara": kök güvenilmez
    return f"{word} yerine daha kısa ve herkesin bildiği bir kelime seçin."


@register
class LongWord(Rule):
    id = "KD-K04"
    name = "Uzun kelime"
    level = "kelime"
    default_severity = "uyarı"
    summary = "Kelimede çok hece ya da çok ek var."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        max_syl = int(cfg.get("max_syllables", 4))
        max_suf = int(cfg.get("max_suffixes", 3))
        known_root_suffixes = int(cfg.get("known_root_max_suffixes", 2))
        lex = doc.lexicon
        vocabulary = lex.common_words | lex.known_words
        replaced = lexicon_covered(doc, ("jargon", "foreign"))  # "ivedilikle" → "hemen"
        for s in body_sentences(doc):
            for t in s.tokens:
                if t.kind != "word" or t.is_abbreviation or is_proper_noun(t) or t.start in replaced:
                    continue
                if not is_latin(t.text):
                    continue  # Arapça, Kiril …: hece sayısı anlamsız
                a = t.analysis
                keys = vocabulary_keys(t.text)
                if fold_circumflex(turkish_lower(t.base)) in lex.known_words:
                    continue
                suffixes = a.suffix_count if a is not None else 0
                core, inflections = _core(t)
                core_syl = count_vowels(core) or t.syllables
                root_known = bool(keys & vocabulary)
                # Türkçe eklemeli bir dildir: "el-ler-iniz-i" 5 hece olur ama okunması kolaydır.
                # Uzunluk, çoğul/iyelik/hâl/kişi ekleri çıkarılmış gövdeye göre ölçülür. Bu
                # eklerden üçü birden gelirse ve kelime yine de uzunsa ("başvurularınızın",
                # "vatandaşlarımıza") kelime ayrıca işaretlenir.
                # Bilinen kısa bir köke en fazla iki ek gelmişse ("yapmalısınız") uzunluk sorun
                # değildir. Kökün kendisi uzunsa ("meteoroloji") bilinse de uzun kelimedir.
                root_syl = count_vowels(a.lemma.removesuffix("mak").removesuffix("mek")) if a else core_syl
                long_core = core_syl > max_syl and not (
                    root_known and root_syl <= max_syl and suffixes <= known_root_suffixes
                )
                heavy = inflections >= 3 and t.syllables > max_syl + 1
                too_many_suf = suffixes > max_suf and (a is None or a.confidence >= 0.6)
                if not (long_core or heavy or too_many_suf):
                    continue
                if too_many_suf:
                    message = (
                        f"{quote(t.text)} kelimesinde çok ek var ({suffixes} ek). "
                        "Ekleri azaltın ya da cümleyi değiştirin."
                    )
                elif long_core:
                    message = (
                        f"{quote(t.text)} uzun bir kelime ({t.syllables} hece). "
                        "Daha kısa bir kelime seçin."
                    )
                else:
                    message = (
                        f"{quote(t.text)} çok ekli, uzun bir kelime ({t.syllables} hece). "
                        "Ekleri azaltın."
                    )
                yield self.finding(
                    doc, cfg, t.start, t.end,
                    message=message,
                    explanation=(
                        "Uzun ve çok ekli kelimeleri okumak zordur. Okur kelimeyi hecelemek "
                        "zorunda kalır ve anlamı kaybeder."
                    ),
                    suggestion=_long_word_hint(t, core),
                    sentence=s,
                    confidence=a.confidence if (a is not None and too_many_suf) else 1.0,
                )


@register
class Idiom(Rule):
    id = "KD-K05"
    name = "Deyim ve mecaz"
    level = "kelime"
    default_severity = "uyarı"
    summary = "Deyim ya da mecazlı söyleyiş."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s, m in _lexicon_matches(doc, "idioms"):
            entry = m.entry
            if entry.literal_cues and _has_cue(s, entry.literal_cues):
                continue  # "Otobüs yola çıktı", "Kapıyı açın", "Kırmızı düğmeye basın"
            start, end, text = _span(s, m)
            meaning = entry.suggestion
            suggestion: str | None
            if entry.ambiguous:
                message = (
                    f"{quote(text)} bir deyim olabilir. Mecaz anlamda kullandıysanız düz "
                    "anlamıyla söyleyin."
                )
                suggestion = (
                    f"Mecaz anlamı: {quote(meaning)}. Bu anlamda kullandıysanız cümleyi buna "
                    "göre yazın. Gerçek anlamında kullandıysanız değiştirmeyin."
                    if meaning else "Gerçek anlamında kullandıysanız değiştirmeyin."
                )
            else:
                message = f"{quote(text)} bir deyim. Düz anlamıyla söyleyin."
                suggestion = (
                    f"Düz anlamı: {quote(meaning)}. Cümleyi bu anlamla yeniden yazın."
                    if meaning else None
                )
            yield self.finding(
                doc, cfg, start, end,
                message=message,
                explanation=(
                    "Deyimler kelimelerin gerçek anlamıyla söylenmez. Okur onları kelimesi "
                    "kelimesine anlayabilir."
                ),
                suggestion=suggestion,
                sentence=s,
                severity="bilgi" if entry.ambiguous else None,
            )


# Önünde sayı varsa ifade kesin bir süre bildirir. "bir", "birkaç", "birçok" belirsiz kalır.
_COUNT_WORDS = frozenset(
    {"iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz", "on", "yirmi", "otuz", "kırk",
     "elli", "altmış", "yetmiş", "seksen", "doksan", "yüz", "bin"}
)


def _counted(s: Sentence, start_token: int) -> bool:
    if start_token == 0:
        return False
    prev = s.tokens[start_token - 1]
    if prev.kind == "number":
        return True
    if prev.kind == "word" and turkish_lower(prev.text) in _COUNT_WORDS:
        return True
    # "en geç 3 iş günü içinde", "beş iş günü içinde": arada tek bir niteleyici kelime olabilir
    if start_token >= 2 and prev.kind == "word" and turkish_lower(prev.text) in ("iş", "takvim", "tam"):
        before = s.tokens[start_token - 2]
        return before.kind == "number" or (
            before.kind == "word" and turkish_lower(before.text) in _COUNT_WORDS
        )
    return False


def _has_cue(s: Sentence, cues: tuple[str, ...]) -> bool:
    words = [fold_circumflex(turkish_lower(t.text)) for t in s.tokens if t.kind == "word"]
    return any(w.startswith(cue) for w in words for cue in cues if " " not in cue) or any(
        cue in fold_circumflex(turkish_lower(s.text)) for cue in cues if " " in cue
    )


@register
class RareWord(Rule):
    id = "KD-K06"
    name = "Seyrek kelime"
    level = "kelime"
    default_severity = "bilgi"
    summary = "Temel kelime listesinde olmayan kelime."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        lex = doc.lexicon
        covered = lexicon_covered(doc, ("jargon", "foreign", "idioms", "vague"))
        vocabulary = lex.common_words | lex.known_words
        seen: set[str] = set()
        for s in body_sentences(doc):
            for t in s.tokens:
                if t.kind != "word" or t.is_abbreviation or is_proper_noun(t):
                    continue
                if t.start in covered or len(t.text) <= 2 or not is_latin(t.text):
                    continue
                keys = vocabulary_keys(t.text)
                # Bağlamsız seçilmeyen okumalar da sayılır: "Bul.", "Düğmeye bas." emir kipidir.
                if keys & vocabulary or all_lemmas(t.text) & vocabulary:
                    continue
                low = fold_circumflex(turkish_lower(t.text))
                if low in seen:
                    continue
                seen.add(low)
                a = t.analysis
                conf = 0.8 if (a is not None and a.source == "zeyrek") else 0.6
                yield self.finding(
                    doc, cfg, t.start, t.end,
                    message=f"{quote(t.text)} az kullanılan bir kelime olabilir. Okurlarınız bu kelimeyi biliyor mu?",
                    explanation=(
                        "Bu kelime temel kelime listesinde yok. Kolay Dil'de herkesin bildiği "
                        "kelimeler kullanılır."
                    ),
                    suggestion="Daha sık kullanılan bir kelime seçin ya da kelimeyi bir cümleyle açıklayın.",
                    sentence=s,
                    confidence=conf,
                )


@register
class VagueExpression(Rule):
    id = "KD-K07"
    name = "Belirsiz zaman / miktar ifadesi"
    level = "kelime"
    default_severity = "uyarı"
    summary = "'En kısa sürede', 'gerekli belgeler' gibi belirsiz ifade."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s, m in _lexicon_matches(doc, "vague"):
            if _counted(s, m.start_token):
                continue  # "14 gün içinde", "üç gün içinde": kesin bir süre
            start, end, text = _span(s, m)
            yield self.finding(
                doc, cfg, start, end,
                message=f"{quote(text)} belirsiz bir ifade. Okur tam olarak ne zaman ya da ne olduğunu bilemez.",
                explanation="Belirsiz ifadeler okuru tahmin etmeye zorlar. Kesin bilgi verin.",
                suggestion=m.entry.suggestion or "Tarih, sayı ya da liste verin.",
                sentence=s,
            )


@register
class TermConsistency(Rule):
    id = "KD-K08"
    name = "Terim tutarsızlığı"
    level = "kelime"
    default_severity = "uyarı"
    summary = "Aynı kavram için farklı kelimeler kullanılmış."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        by_group: dict[str, list[tuple[Sentence, PhraseMatch, str]]] = defaultdict(list)
        for s, m in _lexicon_matches(doc, "synonym_entries"):
            by_group[m.entry.note].append((s, m, m.entry.phrase))
        for _gid, items in by_group.items():
            members = Counter(phrase for _s, _m, phrase in items)
            if len(members) < 2:
                continue
            first_seen: dict[str, int] = {}
            for _s, _m, phrase in items:
                first_seen.setdefault(phrase, len(first_seen))
            dominant = max(members, key=lambda p: (members[p], -first_seen[p]))
            preferred = items[0][1].entry.suggestion or dominant
            others = sorted(members, key=lambda p: first_seen[p])
            for s, m, phrase in items:
                if phrase == dominant:
                    continue
                start, end, _text = _span(s, m)
                yield self.finding(
                    doc, cfg, start, end,
                    message=(
                        f"Bu metinde aynı şey için {' ve '.join(quote(o) for o in others)} "
                        "kelimeleri geçiyor. Hep aynı kelimeyi kullanın."
                    ),
                    explanation=(
                        "Kolay Dil'de aynı şeye hep aynı ad verilir. Farklı kelime görünce okur "
                        "başka bir şeyden söz edildiğini düşünebilir."
                    ),
                    suggestion=f"Metnin her yerinde {quote(preferred)} yazın.",
                    sentence=s,
                )
