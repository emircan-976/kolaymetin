"""Morfolojik çözümleme: zeyrek sarmalayıcısı ve ek tabanlı sezgisel geri dönüş.

Önce zeyrek (Zemberek'in Python portu) denenir. zeyrek kurulu değilse, başlatılamazsa ya da
bir kelimeyi tanımazsa, ünlü uyumuna dayalı sezgisel bir çözümleyici devreye girer. Sezgisel
çözümlemelerin güveni (confidence) 1.0'dan düşüktür.

Ortam değişkeni KOLAYMETIN_MORFOLOJI=sezgisel verilirse zeyrek hiç yüklenmez.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, ClassVar

from kolaymetin.models import Analysis
from kolaymetin.text.normalize import fold_circumflex, turkish_lower

log = logging.getLogger(__name__)

CONVERBS = frozenset(
    {
        "ByDoingSo", "When", "AfterDoingSo", "WithoutHavingDoneSo",
        "WithoutBeingAbleToHaveDoneSo", "While", "SinceDoingSo", "AsLongAs",
        "Adamantly", "AsIf", "EverSince", "InsteadOfDoingSo",
    }
)
PARTICIPLES = frozenset({"PastPart", "FutPart", "PresPart", "NarrPart", "AorPart"})
# Fiilden ad yapan ekler. "Ness" (-lIk) addan ad yapar ("müdürlük", "sıcaklık"); eylem
# isimleştirmesi değildir, bu yüzden listede yok.
NOMINALIZERS = frozenset({"Inf1", "Inf2", "Inf3", "ActOf", "NotState"})
# Ad-fiilden sonra gelip kelimeyi sıfata/başka ada çeviren türetme ekleri ("yağışlı").
_AFTER_NOMINAL_DERIVATIONS = frozenset({"With", "Without", "Rel", "Related", "Agt", "Ness", "JustLike"})
FINITE_MARKERS = frozenset(
    {"Past", "Narr", "Fut", "Prog1", "Prog2", "Aor", "Imp", "Opt", "Neces", "Cop", "Pres"}
)
PERSON_MARKERS = frozenset({"A1sg", "A2sg", "A1pl", "A2pl"})
# Biçimce edilgen/dönüşlü görünen ama günlük dilde kendi anlamıyla kullanılan fiiller.
# Bu fiillerin sözlükteki (sözlükleşmiş) çözümlemesi korunur ve tercih edilir.
LEXICALIZED_KEEP = frozenset(
    {
        "bulunmak", "görünmek", "katılmak", "ayrılmak", "kurtulmak", "dayanmak", "üzülmek",
        "kalkınmak", "yakınmak", "çekinmek", "sevinmek", "dinlenmek", "eğlenmek", "alışmak",
        "tanışmak", "kavuşmak", "sarılmak", "yanılmak", "bağlanmak", "yaslanmak", "yerleşmek",
        "başlamak", "kazanmak", "uzanmak", "yetinmek", "övünmek", "giyinmek", "soyunmak",
        "ilgilenmek", "evlenmek", "hastalanmak", "sinirlenmek", "yorulmak", "kaçınmak",
        "bozulmak", "zorlanmak", "taşınmak", "kırılmak", "yıkılmak", "dağılmak", "sıkılmak",
        "kapanmak", "takılmak", "seslenmek", "söylenmek", "beslenmek", "tamamlanmak",
        "dokunmak", "kaynaklanmak", "buzlanmak", "yaralanmak", "parçalanmak", "dökülmek",
        "yaşanmak", "sallanmak", "yayılmak", "tıkanmak", "dolanmak",
        # zeyrek bu fiilleri tanımıyor, edilgen sanıyor: "yendi" (yenmek) "yemek"in edilgeni,
        # "bayılma" "baymak"ın, "eğilirdim" "eğmek"in edilgeni değildir.
        "yenmek", "bayılmak", "eğilmek", "boğulmak",
    }
)

_V = "aeıioöuü"
_TR_LETTERS = frozenset("abcçdefgğhıijklmnoöprsştuüvyz")


@dataclass(frozen=True)
class WordContext:
    """Belirsizlik gidermede kullanılan bağlam bilgisi."""

    is_last: bool = False
    capitalized: bool = False
    sentence_initial: bool = False
    exclamation: bool = False
    clause_end: bool = False  # ardından ; , : gelir (yan cümle ya da cümle sınırı)
    before_necessity: bool = False  # ardından "gerek…", "lazım", "şart" gelir: "korumam gerekiyor"
    # Cümle ortasında büyük harfle başlayan kelime ("Ali Korkmaz", "Birleşmiş Milletler") ya da
    # bilinen bir ad: Türkçede bu bir özel addır; fiil çözümlemesi ("korkmaz" = korkmak) alınmaz.
    proper_noun: bool = False


# --------------------------------------------------------------------------- veri


def _read_data_lines(*parts: str) -> list[str]:
    try:
        ref = resources.files("kolaymetin").joinpath("data", *parts)
        text = ref.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):  # pragma: no cover - paket bozuksa
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


@lru_cache(maxsize=1)
def reflexive_verbs() -> frozenset[str]:
    """Dönüşlü okunabilen fiiller (yıkanmak, giyinmek ...)."""
    return frozenset(turkish_lower(w) for w in _read_data_lines("lexicon", "reflexive_verbs.txt"))


@lru_cache(maxsize=1)
def known_verb_stems() -> frozenset[str]:
    """Sık kelime listesindeki fiillerin kökleri (sezgisel çözümleyici için)."""
    stems = set()
    for line in _read_data_lines("lexicon", "common_words.txt"):
        for w in line.split():
            w = turkish_lower(w)
            if w.endswith(("mak", "mek")) and len(w) > 4:
                stems.add(w[:-3])
    return frozenset(stems)


# --------------------------------------------------------------------------- zeyrek


class _ZeyrekState:
    lock = threading.Lock()
    analyzer: Any = None
    failed: str | None = None
    tried = False


def _build_fast_analyzer(morphotactics: Any) -> Any:
    """zeyrek'in arama döngüsünün günlük (log) çağrısı yapmayan kopyası.

    Orijinal kod her adımda hata ayıklama metinleri biçimlendirir; bu, süreyi ~3 kat uzatır.
    Algoritma aynıdır.
    """
    from zeyrek.attributes import PhoneticAttribute, calculate_phonetic_attributes
    from zeyrek.morphotactics import SurfaceTransition, generate_surface
    from zeyrek.rulebasedanalyzer import RuleBasedAnalyzer

    class FastRuleBasedAnalyzer(RuleBasedAnalyzer):
        def search(self, current_paths: list[Any]) -> list[Any]:
            if len(current_paths) > 30:
                current_paths = self.prune_cyclic_paths(current_paths)
            result = []
            cannot = PhoneticAttribute.CannotTerminate
            while current_paths:
                all_new: list[Any] = []
                for path in current_paths:
                    if not path.tail and path.is_terminal and cannot not in path.phonetic_attributes:
                        result.append(path)
                        continue
                    all_new.extend(self.advance(path))
                current_paths = all_new
            return result

        # (durum, ses özellikleri, kalan metnin ilk harfi) → o harfle başlayabilecek geçişler ve
        # yüzey biçimleri, özgün sırasıyla. Yüzey biçimi yalnızca geçişe ve ses özelliklerine
        # bağlıdır; ilk harfi tutmayan geçişler (çoğunluk) hiç denenmez. Sonuçlar ve sıraları
        # özgün döngüyle aynıdır.
        _candidates: ClassVar[dict[tuple[int, frozenset[Any], str], tuple[tuple[Any, str], ...]]] = {}

        def _transitions(self, path: Any, attrs_key: frozenset[Any], first: str) -> tuple[tuple[Any, str], ...]:
            key = (id(path.current_state), attrs_key, first)
            found = self._candidates.get(key)
            if found is None:
                items = []
                for transition in path.current_state.outgoing:
                    if not first and transition.has_surface_form:
                        continue
                    surface = generate_surface(transition, path.phonetic_attributes)
                    if surface and surface[0] != first:
                        continue
                    items.append((transition, surface))
                found = tuple(items)
                self._candidates[key] = found
            return found

        def advance(self, path: Any) -> list[Any]:
            new_paths = []
            tail = path.tail
            attrs_key = frozenset(path.phonetic_attributes)
            for transition, surface in self._transitions(path, attrs_key, tail[:1]):
                if not tail.startswith(surface):
                    continue
                if not transition.can_pass(path):
                    continue
                if not transition.has_surface_form:
                    new_paths.append(
                        path.copy(SurfaceTransition("", transition), path.phonetic_attributes)
                    )
                    continue
                st = SurfaceTransition(surface, transition)
                # Özgün kod burada yolun (ve ilk adımda sözlükteki kökün) özellik kümesini
                # yerinde değiştirir; bu, sonraki çözümlemeleri bozar. Kopya ile çalışıyoruz.
                attributes = (
                    set(path.phonetic_attributes)
                    if tail == surface
                    else set(
                        calculate_phonetic_attributes(surface, tuple(path.phonetic_attributes))
                    )
                )
                if PhoneticAttribute.CannotTerminate in attributes:
                    attributes.discard(PhoneticAttribute.CannotTerminate)
                last_token = transition.last_template_token
                if last_token.type_ == "LAST_VOICED":
                    attributes.add(PhoneticAttribute.ExpectsConsonant)
                elif last_token.type_ == "LAST_NOT_VOICED":
                    attributes.add(PhoneticAttribute.ExpectsVowel)
                    attributes.add(PhoneticAttribute.CannotTerminate)
                new_paths.append(path.copy(st, attributes))
            return new_paths

    return FastRuleBasedAnalyzer(morphotactics)


def backend_name() -> str:
    """Kullanılan çözümleyicinin adı: 'zeyrek' ya da 'sezgisel'."""
    return "zeyrek" if _get_zeyrek() is not None else "sezgisel"


def backend_problem() -> str | None:
    """zeyrek kullanılamıyorsa nedeni."""
    _get_zeyrek()
    return _ZeyrekState.failed


def _get_zeyrek() -> Any:
    if _ZeyrekState.tried:
        return _ZeyrekState.analyzer
    with _ZeyrekState.lock:
        if _ZeyrekState.tried:
            return _ZeyrekState.analyzer
        if os.environ.get("KOLAYMETIN_MORFOLOJI", "").lower() == "sezgisel":
            _ZeyrekState.failed = "KOLAYMETIN_MORFOLOJI=sezgisel ayarlı"
        else:
            try:
                logging.getLogger("zeyrek").setLevel(logging.ERROR)
                import zeyrek

                analyzer = zeyrek.MorphAnalyzer()
                analyzer.analyzer = _build_fast_analyzer(analyzer.morphotactics)
                _ZeyrekState.analyzer = analyzer
            except Exception as exc:  # pragma: no cover - ortam bağımlı
                _ZeyrekState.failed = f"zeyrek yüklenemedi: {exc!r}"
                log.warning("zeyrek yüklenemedi, sezgisel çözümleyici kullanılacak: %s", exc)
        _ZeyrekState.tried = True
    return _ZeyrekState.analyzer


def warm_up() -> str:
    """Çözümleyiciyi önceden yükler (sunucu açılışında çağrılır)."""
    return backend_name()


def _convert_zeyrek(word: str, single: Any) -> tuple[Analysis, list[tuple[str, str]]]:
    morphemes = [(m.id_, surface) for m, surface in single.morphemes]
    ids = [mid for mid, _ in morphemes]
    item = single.dict_item
    secondary = getattr(getattr(item, "secondary_pos", None), "value", "") or ""
    pos = getattr(single.pos, "value", str(single.pos))
    # Son çekim grubunu bul (son türetme ekinden sonrası).
    last_ig = 0
    for i, (_mid, _s) in enumerate(morphemes):
        m_obj = single.morphemes[i][0]
        if i > 0 and m_obj.derivational:
            last_ig = i
    last_ids = ids[last_ig:]
    is_finite = (
        pos == "Verb"
        and any(x in FINITE_MARKERS for x in last_ids)
        and "Cond" not in last_ids
        and not any(x in PARTICIPLES or x in CONVERBS or x in NOMINALIZERS for x in last_ids)
    )
    suffix_count = sum(1 for _mid, s in morphemes[1:] if s)
    is_passive = "Pass" in ids
    reflexive = "Reflex" in ids
    if is_passive and item.primary_pos.value == "Verb":
        idx = ids.index("Pass")
        stem_plus = morphemes[0][1] + morphemes[idx][1]
        infinitive = stem_plus + ("mak" if _last_vowel_back(stem_plus) else "mek")
        if infinitive in LEXICALIZED_KEEP:
            is_passive = False  # "bozuldu", "taşındı": günlük dilde kendi anlamıyla kullanılır
        elif infinitive in reflexive_verbs():
            reflexive = True
    converb = any(x in CONVERBS for x in ids)
    if "PastPart" in ids and ids[-1] == "Loc":
        converb = True  # -DIğIndA
    return (
        Analysis(
            word=word,
            root=item.root,
            lemma=item.lemma,
            pos=pos,
            suffixes=tuple(ids[1:]),
            stem_surface=morphemes[0][1],
            suffix_surfaces=tuple(sf for _mid, sf in morphemes[1:]),
            is_passive=is_passive,
            is_negative="Neg" in ids or "Unable" in ids,
            is_causative="Caus" in ids,
            is_converb=converb,
            is_participle=any(x in PARTICIPLES for x in ids),
            is_nominalized=_is_nominalized(ids),
            is_finite=is_finite,
            is_genitive=bool(ids) and ids[-1] == "Gen",
            is_proper=secondary == "Prop",
            is_reflexive_candidate=reflexive,
            suffix_count=suffix_count,
            source="zeyrek",
        ),
        morphemes,
    )


def _is_nominalized(ids: list[str]) -> bool:
    """Fiil ad-fiile dönüşmüş ve sonra sıfata/başka ada türetilmemiş mi?"""
    idx = next((i for i, x in enumerate(ids) if x in NOMINALIZERS), -1)
    if idx < 0:
        return False
    return not any(x in _AFTER_NOMINAL_DERIVATIONS for x in ids[idx + 1 :])


def _last_vowel_back(text: str) -> bool:
    for c in reversed(text):
        if c in "aıou":
            return True
        if c in "eiöü":
            return False
    return True


# Türkçenin bilinen en uzun kelimesi 70 harf kadardır. Daha uzun bir "kelime" (boşluksuz
# yapıştırılmış bir dizi) çözümlenmez: önek araması kelime uzunluğunun karesiyle büyür.
MAX_WORD_LENGTH = 80


def _zeyrek_analyses(word: str) -> list[tuple[Analysis, list[tuple[str, str]], str]]:
    analyzer = _get_zeyrek()
    if analyzer is None or len(word) > MAX_WORD_LENGTH:
        return []
    normalized = fold_circumflex(turkish_lower(word)).replace("'", "")
    try:
        results = analyzer.analyzer.analyze(normalized)
    except Exception:  # pragma: no cover - zeyrek iç hatası
        return []
    out = []
    for single in results:
        if single is None:
            continue
        analysis, morphemes = _convert_zeyrek(word, single)
        secondary = getattr(getattr(single.dict_item, "secondary_pos", None), "value", "") or ""
        out.append((analysis, morphemes, secondary))
    return _drop_lexicalized_duplicates(out)


def _drop_lexicalized_duplicates(
    items: list[tuple[Analysis, list[tuple[str, str]], str]],
) -> list[tuple[Analysis, list[tuple[str, str]], str]]:
    """'alınmak' gibi sözlükleşmiş edilgen kökleri, 'al+ın' edilgen çözümlemesi varken eler."""
    passive_stems = set()
    for a, morphemes, _ in items:
        if a.is_passive:
            ids = [m for m, _ in morphemes]
            idx = ids.index("Pass")
            passive_stems.add(morphemes[0][1] + morphemes[idx][1])
    if not passive_stems:
        return items
    kept = []
    for a, morphemes, sec in items:
        # Yalnızca kökü edilgen gövdenin kendisi olan fiil düşer: "alınmak" (alın-mak). "yeniliyor"
        # kelimesindeki "yenilemek" (yenile-iyor) ayrı bir fiildir; gövdesi yüzeyde "yenil" olsa da
        # "yenmek" fiilinin edilgeni değildir.
        if (
            a.lemma not in LEXICALIZED_KEEP
            and not a.is_passive
            and "Reflex" not in a.suffixes
            and a.lemma.endswith(("mak", "mek"))
            and morphemes[0][1] in passive_stems
            and a.lemma[:-3] == morphemes[0][1]
        ):
            continue
        kept.append((a, morphemes, sec))
    return kept or items


# zeyrek sözlüğünde olan ama gündelik dilde neredeyse hiç geçmeyen kökler: "açılıyor" →
# "açılamak" değil "aç-ıl-ıyor" ("açıldı" ile aynı okuma).
RARE_LEMMAS = frozenset({"açılamak"})


def _penalty(a: Analysis, secondary: str, ctx: WordContext) -> float:
    p = 0.1 * len(a.suffixes)
    if a.lemma in RARE_LEMMAS:
        p += 1.0
    ids = a.suffixes
    if "Zero" in ids:
        # Addan fiil ("üzgün-sün", "yaşlı-lar" = onlar yaşlıdır) nadir okumadır; sıfattan ad
        # ("boş-a" = boşa, "iyi-ye") ise olağandır ve "boşa" emir kipine (boşamak) yenilmemeli.
        zero_idx = ids.index("Zero")
        p += 2.0 if "Verb" in ids[zero_idx + 1 : zero_idx + 2] else 0.5
    if "P2sg" in ids or "P1sg" in ids:
        p += 1.0
    if "Imp" in ids and "A2sg" in ids:
        # Cümle sonundaki "unutma", "koşma" olumsuz emirdir; yalın ad-fiil ("unutma") orada
        # neredeyse hiç yüklem olmaz.
        negative_command = "Neg" in ids and ctx.is_last
        p += 0.2 if (ctx.exclamation or negative_command) else 1.5
    if "Imp" in ids and "A2pl" in ids and "Pass" in ids and not (ctx.is_last or ctx.exclamation):
        # "ağrının ve/veya ateşin azalmaması": "ağrı-nın" ilgi ekli addır, "ağrı-n-ın"
        # (edilgen emir) değil. Cümle sonundaki "Soğuktan korunun." etkilenmez.
        p += 1.5
    if "Acquire" in ids or "Become" in ids:
        p += 1.5
    if "Desr" in ids:
        p += 1.0
    if "Opt" in ids and "A3sg" in ids:
        p += 1.0  # "göre" (görmek, istek kipi) değil, "göre" edatı
    if "Dim" in ids or "JustLike" in ids:
        p += 1.0
    if secondary in ("Prop", "Abbrv"):
        if not ctx.capitalized:
            p += 3.0
        elif not ctx.sentence_initial:
            p -= 0.5
    if secondary == "Abbrv":
        p += 1.0
    # Addan türeyen yüklem ("yaşlı-lar" = "onlar yaşlıdır") virgülden önce neredeyse hep
    # bir sıralamanın öğesidir: "Yaşlılar, bebekler ve …". Yan cümle sonu ona yüklem saydırmaz.
    nominal_predicate = "Zero" in ids and "Pres" in ids and not ctx.is_last
    if (ctx.is_last or (ctx.clause_end and not nominal_predicate)) and a.is_finite:
        p -= 0.5
    if not (ctx.is_last or ctx.clause_end) and a.is_finite and ids and ids[-1] not in ("Cop",):
        p += 0.3
    if ctx.before_necessity:
        # "korumam gerekiyor": ad-fiil + iyelik ("benim korumam"), olumsuz geniş zaman değil
        if any(x in NOMINALIZERS for x in ids):
            p -= 1.0
        elif a.is_finite:
            p += 1.0
    return p


# --------------------------------------------------------------------------- sezgisel

_TENSE = (
    r"(?:[ıiuü]yor|[ae]c[ae]k|[ae]c[ae]ğ|[dt][ıiuü]|m[ıiuü]ş|[ıiuü]r|m[ae]kt[ae]|m[ae]l[ıi]"
    r"|s[ae]|[ae]r)"
)
_NONFINITE = (
    r"(?:m[ae]k|m[ae]|[ae]n|[dt][ıiuü][kğ]|[ae]c[ae][kğ]|[ae]r[ae]k|[ıiuü]p|[ıiuü]nc[ae]|[ıiuü]ş)"
)
# "-mAlI" gereklilik ekidir ("olmalıyım"); olumsuzu "-mAmAlI"dır ("olmamalı").
_NEG_RE = re.compile(
    r"(?:m[ae](?:[dt][ıi]|y[ae]c[ae][kğ]|m[ıi]ş|z|s[ıi]n|m[ae]l[ıi]|y[ıi]n|y[ıi]z|s[ae]|[dt][ıi][kğ]|y[ae]n)"
    r"|m[ıiuü]yor)"
)
_CONVERB_RE = re.compile(
    r"(?:y?[ae]r[ae]k|y?[ıiuü]nc[ae]|m[ae]d[ae]n|[dt][ıiuü]ğ[ıiuü]n?d[ae]|(?<=[^aeıioöuü])[ıiuü]p|y[ıiuü]p|[ıi]?ken)$"
)
_PARTICIPLE_RE = re.compile(
    r"(?:y?[ae]n(?:l[ae]r)?(?:[ıi]n?|[ae]|d[ae]|d[ae]n)?|[dt][ıiuü][kğ](?:[ıiuü]|l[ae]r)?.*|y?[ae]c[ae]ğ[ıiuü].*)$"
)
_NOMINAL_RE = re.compile(
    r"(?:m[ae](?:s[ıi](?:n[ae]|n[ıi]n|nd[ae]|yl[ae]|n[ıi])?|y[ae]|d[ae]n|l[ıi]d[ıi]r)?"
    r"|m[ae]k(?:t[ae](?:n)?|l[ae])?|y?[ıiuü]ş(?:[ıiuü]|l[ae]r[ıi]?)?|m[ae]l[ıi][kğ]"
    r"|l[ıiuü][kğ](?:[ıiuü]|l[ae]r)?)$"
)
_GENITIVE_RE = re.compile(rf"(?:(?<=[{_V}])n[ıiuü]n|(?<=[^{_V}])[ıiuü]n)$")
_FINITE_RE = re.compile(
    rf"(?:{_TENSE}(?:[ıiuü]m|s[ıiuü]n|[ıiuü]z|s[ıiuü]n[ıiuü]z|l[ae]r|k|n[ıiuü]z|m)?"
    r"(?:[dt][ıiuü]r)?|[dt][ıiuü]r(?:l[ae]r)?|[ıiuü]n(?:[ıiuü]z)?)$"
)
_INFLECTIONS = sorted(
    {
        "lar", "ler", "ları", "leri", "ların", "lerin", "ımız", "imiz", "umuz", "ümüz",
        "ınız", "iniz", "unuz", "ünüz", "nın", "nin", "nun", "nün", "ın", "in", "un", "ün",
        "ndan", "nden", "dan", "den", "tan", "ten", "nda", "nde", "da", "de", "ta", "te",
        "na", "ne", "ya", "ye", "yla", "yle", "la", "le", "sı", "si", "su", "sü",
        "dır", "dir", "dur", "dür", "tır", "tir", "tur", "tür", "ı", "i", "u", "ü", "a", "e",
    },
    key=len,
    reverse=True,
)
# Zaman / ad-fiil ekinden sonra gelebilecek çekim ekleri, Türkçedeki sırasıyla. Kelimenin
# geri kalanı bunlarla bitmiyorsa ("Valdivia", "kontinü", "travertensert") kelime fiil değildir.
_PERSON = r"(?:[ıiuü]?m|s[ıiuü]n(?:[ıiuü]z)?|[ıiuü]z|l[ae]r|k|n[ıiuü]z|y[ıiuü][mz])"
_POSS = r"(?:l[ae]r)?(?:[ıiuü]?m(?:[ıiuü]z)?|[ıiuü]?n(?:[ıiuü]z)?|s[ıiuü]|[ıiuü]|l[ae]r[ıi])?"
_CASE = r"(?:n?[ıiuü]|n?[ae]|n?[dt][ae]n?|n?[ıiuü]n|y?l[ae]|y[ıiuü]|y[ae])?"
_COP = r"(?:[dt][ıiuü]r|y?ken|k[ıi])?"
_VERB_TAIL = rf"(?:{_TENSE}{_PERSON}?{_COP}(?:l[ae]r)?|{_NONFINITE}{_POSS}{_CASE}{_COP})"
_PASSIVE_RE = re.compile(
    rf"^(?P<stem>.{{2,}}?)(?P<pass>[ıiuü]l|[ıiuü]n|(?<=[{_V}])n|(?<=[{_V}])l){_VERB_TAIL}$"
)
_AR_AORIST_TAIL_RE = re.compile(r"[ae]r(?:l[ae]r[ıi]?|d[ıi]|s[ae]|[ıi]m|s[ıi]n|[ıi]z|s[ıi]n[ıi]z)?$")
_LEXICALIZED_N_L = frozenset(
    {
        "bulun", "görün", "dayan", "katıl", "kurtul", "ayrıl", "dinlen", "eğlen", "sevin",
        "üzül", "yakın", "kazan", "başla", "çekin", "övün", "gel", "bil",
        "kal", "ol", "sal", "dol", "bul", "del", "sil", "dil", "yol", "kul", "okul", "bel",
        "kalın", "ilan", "zaman", "insan", "meydan", "orman", "liman",
    }
)


def _soften_final(stem: str) -> str:
    table = {"b": "p", "c": "ç", "d": "t", "ğ": "k", "g": "k"}
    if stem and stem[-1] in table and len(stem) > 2:
        return stem[:-1] + table[stem[-1]]
    return stem


@lru_cache(maxsize=100_000)
def heuristic_stem(word: str) -> tuple[str, int]:
    """Çekim eklerini sondan soyarak yaklaşık bir gövde ve ek sayısı döndürür."""
    w = fold_circumflex(turkish_lower(word)).replace("'", "")
    count = 0
    changed = True
    while changed and count < 5:
        changed = False
        for suf in _INFLECTIONS:
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                rest = w[: -len(suf)]
                if not any(c in _V for c in rest):
                    continue
                w = rest
                count += 1
                changed = True
                break
    return _soften_final(w), count


def _verbal_stem_known(prefix: str) -> bool:
    stems = known_verb_stems()
    return prefix in stems or _soften_final(prefix) in stems


def heuristic_analyze(word: str, ctx: WordContext | None = None) -> Analysis:
    """Ünlü uyumuna ve ek kalıplarına dayalı yaklaşık çözümleme (güven < 1)."""
    ctx = ctx or WordContext()
    w = fold_circumflex(turkish_lower(word)).split("'", 1)[0]
    stem, count = heuristic_stem(word)
    # Yabancı kelime ("sintió", "Wikipedia") ya da cümle içinde büyük harfli özel ad ("Valdivia"):
    # Türkçe ek kalıpları bunlara uygulanmaz.
    if any(c.isalpha() and c not in _TR_LETTERS for c in w) or ctx.proper_noun or (
        ctx.capitalized and not ctx.sentence_initial
    ):
        return Analysis(
            word=word, root=stem, lemma=stem, pos="Unknown",
            is_proper=ctx.proper_noun or (ctx.capitalized and not ctx.sentence_initial),
            suffix_count=count, source="sezgisel", confidence=0.6,
        )

    passive = False
    reflexive = False
    stem_surface = ""
    suffix_surfaces: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    m = _PASSIVE_RE.match(w)
    if m:
        pstem = m.group("stem")
        full = pstem + m.group("pass")
        # Edilgen gövde çok hecelidir; geniş zamanı "-Ir" olur ("silinir"). "-il-er" biçimi
        # edilgen değil, çoğul addır: "siyanobakteri-ler", "aile-ler".
        aorist_ar = _AR_AORIST_TAIL_RE.match(w[m.end("pass"):]) is not None
        if (
            full not in _LEXICALIZED_N_L
            and len(pstem) >= 2
            and any(c in _V for c in pstem)
            and not aorist_ar
        ):
            passive = True
            stem_surface = pstem
            suffixes = ("Pass", "Rest")
            suffix_surfaces = (m.group("pass"), w[m.end("pass"):])
            if full + ("mak" if _last_vowel_back(full) else "mek") in reflexive_verbs():
                reflexive = True

    negative = w in ("değil", "yok", "hiç") or w.startswith(("değil", "hiçbir")) or bool(
        _NEG_RE.search(w[2:])
    )
    converb = bool(_CONVERB_RE.search(w)) and len(w) >= 5
    participle = False
    pm = _PARTICIPLE_RE.search(w)
    if pm and pm.start() >= 2:
        participle = _verbal_stem_known(w[: pm.start()]) or passive
    nominal = False
    nm = _NOMINAL_RE.search(w)
    if nm and nm.start() >= 2:
        prefix = w[: nm.start()]
        is_ness = nm.group(0).startswith(("lı", "li", "lu", "lü"))
        nominal = is_ness or _verbal_stem_known(prefix) or passive
    finite = ctx.is_last and bool(_FINITE_RE.search(w)) and not nominal
    if ctx.is_last and w.endswith(("acak", "ecek")):
        participle = False
        finite = True
    genitive = bool(_GENITIVE_RE.search(w)) and len(w) > 4 and not finite
    return Analysis(
        word=word,
        root=stem,
        lemma=stem,
        pos="Verb" if finite else "Unknown",
        suffixes=suffixes,
        stem_surface=stem_surface,
        suffix_surfaces=suffix_surfaces,
        is_passive=passive,
        is_negative=negative,
        is_converb=converb,
        is_participle=participle,
        is_nominalized=nominal,
        is_finite=finite,
        is_genitive=genitive,
        is_proper=ctx.capitalized and not ctx.sentence_initial,
        is_reflexive_candidate=reflexive,
        suffix_count=count + (1 if passive else 0) + (1 if negative and not w.startswith("değil") else 0),
        source="sezgisel",
        confidence=0.6,
    )


# --------------------------------------------------------------------------- genel API


@lru_cache(maxsize=100_000)
def _analyze_cached(word: str) -> tuple[tuple[Analysis, str], ...]:
    items = _zeyrek_analyses(word)
    return tuple((a, sec) for a, _m, sec in items)


def is_dictionary_word(word: str) -> bool:
    """zeyrek kelimeyi özel ad ya da kısaltma dışında bir sözlük girdisiyle çözümlüyor mu?"""
    return any(sec not in ("Prop", "Abbrv") for _a, sec in _analyze_cached(word))


def has_noun_reading(word: str) -> bool:
    """zeyrek kelimeyi fiilden türemeyen bir ad olarak da çözümlüyor mu ("astım", "ürünün")?"""
    return any(
        a.pos == "Noun" and sec not in ("Prop", "Abbrv")
        and not any(x in ("Verb", "Zero") or x in NOMINALIZERS for x in a.suffixes)
        for a, sec in _analyze_cached(word)
    )


def is_proper_name(word: str) -> bool:
    """zeyrek kelimeyi yalnızca özel ad olarak mı tanıyor ("ankara", "keçiören")? Kısaltma değil."""
    items = _analyze_cached(word)
    return bool(items) and all(sec == "Prop" for _a, sec in items)


def analyze_word(word: str) -> list[Analysis]:
    """Kelimenin olası bütün çözümlemeleri. zeyrek tanımazsa tek bir sezgisel çözümleme."""
    items = _analyze_cached(word)
    if items:
        return [a for a, _ in items]
    return [heuristic_analyze(word)]


_FLAG_NAMES = (
    "is_passive", "is_negative", "is_converb", "is_participle",
    "is_nominalized", "is_finite", "is_genitive", "is_causative",
)


@lru_cache(maxsize=200_000)
def best(word: str, context: WordContext | None = None) -> Analysis | None:
    """Bağlama göre en olası çözümleme. Belirsizlik varsa confidence < 1.0 olur."""
    ctx = context or WordContext()
    if not word or not any(c.isalpha() for c in word):
        return None
    items = _analyze_cached(word)
    if not items:
        return heuristic_analyze(word, ctx)
    scored = sorted(((_penalty(a, sec, ctx), a) for a, sec in items), key=lambda x: x[0])
    top_score, chosen = scored[0]
    candidates = [a for s, a in scored if s <= top_score + 0.75]
    flag_conf: dict[str, float] = {}
    for flag in _FLAG_NAMES:
        if getattr(chosen, flag):
            agree = sum(1 for c in candidates if getattr(c, flag)) / len(candidates)
            flag_conf[flag] = round(agree, 2)
    if chosen.is_passive and chosen.is_reflexive_candidate:
        flag_conf["is_passive"] = min(flag_conf.get("is_passive", 1.0), 0.5)
    # Sözlükleşmiş biçimler ("gelen" sıfatı) türetmeyi gizler: adayların en az yarısı
    # yapısal bir işareti taşıyorsa işareti düşük güvenle ekle.
    update_flags: dict[str, Any] = {}
    # Türetme eki taşımayan yalın ad ("alan", "sandık", "çakmak") sözlükte ad olarak geçer;
    # rastlantısal fiil çözümlemesi ("al-an", "san-dık") ona yapısal işaret eklemesin.
    plain_noun = chosen.pos == "Noun" and not any(
        x in NOMINALIZERS or x in PARTICIPLES or x in CONVERBS or x in NOUN_DERIVATIONS
        or x in ("Pass", "Verb", "Zero")
        for x in chosen.suffixes
    )
    for flag in ("is_participle", "is_converb", "is_nominalized"):
        if not plain_noun and not getattr(chosen, flag) and len(candidates) > 1:
            agree = sum(1 for c in candidates if getattr(c, flag)) / len(candidates)
            if agree >= 0.5:
                update_flags[flag] = True
                flag_conf[flag] = round(agree, 2)
    conf = min(flag_conf.values()) if flag_conf else 1.0
    update: dict[str, Any] = {"confidence": round(conf, 2), "flag_confidence": flag_conf, **update_flags}
    # Özel ad bayrağı yalnızca büyük harfle başlayan kelimede geçerli.
    if chosen.is_proper and not ctx.capitalized:
        update["is_proper"] = False
    if ctx.proper_noun:
        update.update(_PROPER_NOUN_UPDATE)
        update["flag_confidence"] = {k: v for k, v in flag_conf.items() if k == "is_genitive"}
        update["confidence"] = flag_conf.get("is_genitive", 1.0)
    return chosen.model_copy(update=update)


# Özel adda fiil işaretleri anlamsızdır ("Korkmaz" olumsuz değil, "Birleşmiş" yan cümle değil).
# İlgi eki korunur: "Su İşleri Müdürlüğünün" tamlama zincirinin parçasıdır.
_PROPER_NOUN_UPDATE: dict[str, Any] = {
    "is_proper": True, "is_passive": False, "is_negative": False, "is_causative": False,
    "is_converb": False, "is_participle": False, "is_nominalized": False, "is_finite": False,
    "is_reflexive_candidate": False,
}


@lru_cache(maxsize=1)
def known_names() -> frozenset[str]:
    """Sık kullanılan kişi adları ve soyadları (küçük harfli). Bir kısmı fiile benzer:
    "Korkmaz", "Sönmez", "Yaşar", "Güler", "Doğan", "Aydoğdu"."""
    return frozenset(
        fold_circumflex(turkish_lower(w))
        for line in _read_data_lines("lexicon", "names.txt")
        for w in line.split()
    )


def proper_position(
    capitalized: bool, all_caps: bool, sentence_initial: bool, is_last: bool, word: str
) -> bool:
    """Kelime konumuna göre özel ad mı?

    Cümle ortasında büyük harfle başlayan kelime Türkçede özel addır (tamamı büyük harfle
    yazılmış vurgu hariç). Cümle başında yalnızca bilinen bir ad, cümlenin son kelimesi
    (yüklemi) değilse özel ad sayılır: "Korkmaz ailesi geldi." ama "Korkmaz."
    """
    if not capitalized or all_caps:
        return False
    if not sentence_initial:
        return True
    return not is_last and fold_circumflex(turkish_lower(word.split("'", 1)[0])) in known_names()


NOUN_DERIVATIONS = frozenset(
    {"Ness", "With", "Without", "Agt", "Related", "Rel", "JustLike", "Dim", "Acquire", "Become", "Ly"}
)


def participle_stem(a: Analysis) -> str:
    """Sıfat-fiil gövdesi: "çalışanlarımız" → "çalışan". Ad gibi kullanılan sıfat-fiiller
    ("çalışan", "okur") sözlükte kendi başına bir kelimedir."""
    if a.pos == "Verb" or not a.stem_surface:
        return ""
    idx = next((i for i, x in enumerate(a.suffixes) if x in PARTICIPLES), -1)
    if idx < 0 or len(a.suffix_surfaces) <= idx:
        return ""
    return fold_circumflex(turkish_lower(a.stem_surface + "".join(a.suffix_surfaces[: idx + 1])))


def derived_stem(a: Analysis) -> str:
    """Kök + türetme ekleri (çekim ekleri hariç): görev+li+ye → görevli."""
    last = -1
    for i, sid in enumerate(a.suffixes):
        if sid in NOUN_DERIVATIONS:
            last = i
    if last < 0 or not a.stem_surface:
        return ""
    return _soften_final(turkish_lower(a.stem_surface + "".join(a.suffix_surfaces[: last + 1])))


@lru_cache(maxsize=100_000)
def lemma_keys(word: str, strict: bool = False) -> frozenset[str]:
    """Sözlük eşlemesi için anahtarlar: yüzey biçim, lemma(lar), türetilmiş gövde.

    strict=True yalnızca en olası çözümlemeyi kullanır (sözlük girdileri için).
    Aksi hâlde en olası çözümlemeye yakın (ceza farkı ≤ 1) bütün çözümlemeler kullanılır.
    """
    w = fold_circumflex(turkish_lower(word))
    keys = {w}
    if not strict:
        keys.add(w.split("'", 1)[0])
    items = _analyze_cached(word)
    if items:
        ctx = WordContext()
        scored = sorted(((_penalty(a, sec, ctx), a) for a, sec in items), key=lambda x: x[0])
        top = scored[0][0]
        chosen = [scored[0][1]] if strict else [a for sc, a in scored if sc <= top + 1.0]
        for a in chosen:
            lemma = fold_circumflex(turkish_lower(a.lemma))
            # "-ki" (Rel) ve küçültme (Dim) anlamı değiştirmez: "resimdeki" → "resim", "kutucuk" → "kutu". "-ıcı", "-lık" gibi
            # türetmeler yeni bir kelime kurar: "yüklenici" "yüklemek" değildir.
            derivational = any(sid in NOUN_DERIVATIONS and sid not in ("Rel", "Dim") for sid in a.suffixes)
            if a.pos == "Verb" or not derivational:
                keys.add(lemma)
            derived = derived_stem(a)
            if derived:
                keys.add(fold_circumflex(derived))
            part = participle_stem(a)
            if part:
                keys.add(part)
    elif not strict:
        # Sözlük girdisinde sezgisel gövde kullanılmaz: "login" → "log" değildir.
        stem, _ = heuristic_stem(word)
        keys.add(stem)
    return frozenset(keys)


# Anlamı kökten kolayca çıkan türetmeler: "süre-li", "tuz-suz", "sağ-lık", "çocuk-ça", "ev-deki".
_TRANSPARENT_DERIVATIONS = frozenset({"With", "Without", "Ness", "Ly", "JustLike", "Rel", "Dim", "Related"})


@lru_cache(maxsize=100_000)
def vocabulary_keys(word: str) -> frozenset[str]:
    """Temel kelime listesinde aranacak anahtarlar (KD-K06, KD-K04).

    lemma_keys'e ek olarak türetmenin her ara gövdesi ("sağlıklı" → "sağlık") ve türetmeleri
    anlamca saydam olan kelimelerin kökü ("süreli" → "süre", "kuvvetli" → "kuvvet") eklenir.
    Okur kökü biliyorsa bu kelimeyi de anlar.
    """
    keys = set(lemma_keys(word))
    items = _analyze_cached(word)
    if not items:
        return frozenset(keys)
    ctx = WordContext()
    scored = sorted(((_penalty(a, sec, ctx), a) for a, sec in items), key=lambda x: x[0])
    top = scored[0][0]
    for sc, a in scored:
        if sc > top + 1.0 or not a.stem_surface:
            continue
        stem = a.stem_surface
        for sid, surface in zip(a.suffixes, a.suffix_surfaces, strict=False):
            stem += surface
            if sid in NOUN_DERIVATIONS or sid in NOMINALIZERS:
                keys.add(_soften_final(fold_circumflex(turkish_lower(stem))))
        derivations = {sid for sid in a.suffixes if sid in NOUN_DERIVATIONS}
        if derivations and derivations <= _TRANSPARENT_DERIVATIONS:
            keys.add(fold_circumflex(turkish_lower(a.lemma)))
    return frozenset(keys)


_INFLECTION_TAGS = frozenset(
    {"A1sg", "A2sg", "A1pl", "A2pl", "A3pl", "P1sg", "P2sg", "P3sg", "P1pl", "P2pl", "P3pl",
     "Acc", "Dat", "Loc", "Abl", "Gen", "Ins", "Equ"}
)


_CASE_TAGS = ("Acc", "Dat", "Loc", "Abl", "Gen", "Ins", "Equ")


@lru_cache(maxsize=100_000)
def case_set(word: str) -> frozenset[str] | None:
    """Kelimenin olası ad durumları ("önüne" → {Dat}, "önünü" → {Acc}, "göz" → {Nom}).

    Deyim ve kalıp eşlemesinde kullanılır: "önünü almak" (engellemek) deyimi "önüne almak"
    değildir, "hak sahibi" "haklara sahip" değildir. Kelime fiilse ya da çözümlenemiyorsa None.
    """
    items = _analyze_cached(word)
    if not items:
        return None
    scored = sorted(((_penalty(a, sec, WordContext()), a) for a, sec in items), key=lambda x: x[0])
    top = scored[0][0]
    cases = set()
    for sc, a in scored:
        if sc > top + 1.0 or a.pos == "Verb":
            continue
        found = [x for x in a.suffixes if x in _CASE_TAGS]
        cases.add(found[-1] if found else "Nom")
    return frozenset(cases) or None


@lru_cache(maxsize=10_000)
def entry_keys(word: str) -> frozenset[str]:
    """Tek kelimelik sözlük girdisi için anahtarlar.

    Girdi çekimli yazılmışsa ("hükmünde", "suretiyle") yalnızca o biçim eşleşir; kökü
    ("hüküm", "suret") eşleşirse "Kanun hükümleri" gibi masum kullanımlar da işaretlenir.
    """
    keys = set(lemma_keys(word, strict=True))
    items = _analyze_cached(word)
    if items:
        scored = sorted(((_penalty(a, sec, WordContext()), a) for a, sec in items), key=lambda x: x[0])
        a = scored[0][1]
        lemma = fold_circumflex(turkish_lower(a.lemma))
        inflected = any(sid in _INFLECTION_TAGS for sid in a.suffixes)
        if inflected and a.pos != "Verb" and not lemma.endswith(("mak", "mek")):
            keys.discard(lemma)
        if participle_stem(a) == fold_circumflex(turkish_lower(word)):
            # "çalışan" girdisi "çalışanlar"la eşleşir, "çalışılır" fiiliyle eşleşmez.
            keys.discard(lemma)
    return frozenset(keys)


_VERB_ENDING_RE = re.compile(rf"^{_VERB_TAIL}$")


@lru_cache(maxsize=10_000)
def heuristic_verb_lemma(word: str) -> str:
    """zeyrek'in tanımadığı çekimli fiilin mastarı: "olmalıyım" → "olmak". Bulamazsa ""."""
    w = fold_circumflex(turkish_lower(word)).split("'", 1)[0]
    if len(w) > MAX_WORD_LENGTH:
        return ""
    stems = known_verb_stems()
    for k in range(len(w) - 1, 1, -1):
        stem, rest = w[:k], w[k:]
        if stem in stems and _VERB_ENDING_RE.match(rest):
            return stem + ("mak" if _last_vowel_back(stem) else "mek")
    return ""


def all_lemmas(word: str) -> frozenset[str]:
    """zeyrek'in bulduğu bütün çözümlemelerin lemmaları (özel ad ve kısaltmalar hariç).

    Emir kipi gibi bağlamsız seçilmeyen okumalar da dahildir: "bul", "bas" → "bulmak", "basmak".
    zeyrek kelimeyi tanımıyorsa bilinen bir fiil kökü aranır: "olmalıyım" → "olmak".
    """
    items = _analyze_cached(word)
    if not items:
        verb = heuristic_verb_lemma(word)
        return frozenset({verb} if verb else ())
    return frozenset(
        fold_circumflex(turkish_lower(a.lemma)) for a, sec in items if sec not in ("Prop", "Abbrv")
    )


def clear_caches() -> None:
    _analyze_cached.cache_clear()
    best.cache_clear()
    lemma_keys.cache_clear()
    vocabulary_keys.cache_clear()
    entry_keys.cache_clear()
    case_set.cache_clear()
    heuristic_verb_lemma.cache_clear()
    heuristic_stem.cache_clear()
