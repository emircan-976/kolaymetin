"""Bir kelimenin yerine başkasını, eklerini koruyarak yazmak: "müracaatlarınızı" → "başvurularınızı".

zeyrek yalnızca çözümler, kelime üretmez. Burada ekleri morfem kimliklerinden (A3pl, P2pl, Acc …)
ünlü uyumu, ünsüz benzeşmesi ve kaynaştırma harfleriyle yeniden kurarız. Düzensizlikler
(yumuşama, geniş zaman ünlüsü, edilgen eki) için birkaç aday üretilir; adaylar zeyrek'e geri
çözümletilir. Yeni kelimeyle ve özgün kelimeyle aynı morfem dizisine çözümlenen ilk aday seçilir.
Doğrulanamayan biçim için düzeltme verilmez: yanlış bir kelime yazmaktan iyidir.
"""

from __future__ import annotations

from functools import lru_cache
from itertools import product

from kolaymetin.models import Analysis
from kolaymetin.text import morphology
from kolaymetin.text.normalize import turkish_lower

VOWELS = "aeıioöuü"
_BACK = "aıou"
_ROUND = "oöuü"
_VOICELESS = "çfhkpsşt"
_SOFT = {"p": "b", "ç": "c", "t": "d", "k": "ğ"}
_MAX_CANDIDATES = 256

# Morfem kimliği → olası ek kalıpları (yeğlenen önce). Kalıp harfleri:
#   A: a/e   I: ı/i/u/ü   D: d/t   Y, N, S: ünlüden sonra y, n, s (kaynaştırma)
#   ~: ardından gelen ünlü, kelime ünlüyle bitiyorsa düşer ("konu-m", "işlem-im")
#   @: kelimenin son ünlüsü düşer ("bekle" + "@Iyor" → "bekliyor")
# Yüzeyi olmayan işaretler (sözcük türü değişimi, "Zero") boş kalıptır.
_TEMPLATES: dict[str, tuple[str, ...]] = {
    # ad çekimi
    "A3sg": ("",), "Pnon": ("",), "Nom": ("",), "A3pl": ("lAr",),
    "P1sg": ("~Im",), "P2sg": ("~In",), "P3sg": ("SI",), "P1pl": ("~ImIz",), "P2pl": ("~InIz",),
    "P3pl": ("lArI", "~I"),
    "Acc": ("YI",), "Dat": ("YA",), "Loc": ("DA",), "Abl": ("DAn",), "Gen": ("NIn",),
    "Ins": ("YlA",), "Rel": ("ki",),
    # sözcük türü işaretleri
    "Noun": ("",), "Adj": ("",), "Verb": ("",), "Zero": ("",), "Pres": ("",), "Pos": ("",),
    "Cop": ("DIr",),
    # fiil
    "Imp": ("",), "Neg": ("mA",), "Pass": ("Il", "In", "n"), "Able": ("YAbil",),
    "Past": ("DI",), "Narr": ("mIş",), "Fut": ("YAcAk",), "Prog1": ("@Iyor",), "Prog2": ("mAktA",),
    "Aor": ("Ir", "Ar", "r"), "Neces": ("mAlI",), "Cond": ("YsA",), "Opt": ("YA",), "Desr": ("sA",),
    # ad-fiil, sıfat-fiil, zarf-fiil
    "Inf1": ("mAk",), "Inf2": ("mA",), "Inf3": ("YIş",),
    "PastPart": ("DIk",), "FutPart": ("YAcAk",), "PresPart": ("YAn",), "NarrPart": ("mIş",),
    "AorPart": ("Ir", "Ar", "r"),
    "ByDoingSo": ("YArAk",), "AfterDoingSo": ("YIp",), "WithoutHavingDoneSo": ("mAdAn",),
}
# Kişi ekleri: "k" dizisi (geçmiş zaman, şart) ve "z" dizisi (öteki zamanlar).
_PERSON_K = {"A1sg": "m", "A2sg": "n", "A3sg": "", "A1pl": "k", "A2pl": "nIz", "A3pl": "lAr"}
_PERSON_Z = {"A1sg": "YIm", "A2sg": "sIn", "A3sg": "", "A1pl": "YIz", "A2pl": "sInIz", "A3pl": "lAr"}
# Emir kipinde kişi: Kolay Dil kısa emri yeğler ("doldurunuz" → "doldurun").
_PERSON_IMP = {"A2sg": ("",), "A2pl": ("YIn", "YInIz"), "A3sg": ("sIn",), "A3pl": ("sInlAr",)}
_TENSES = frozenset({"Past", "Narr", "Fut", "Prog1", "Prog2", "Aor", "Neces", "Cond", "Opt", "Desr"})
# İyelikten sonra gelen hâl eki "n" kaynaştırmasıyla başlar: "konusu-na", "konusu-nda".
_AFTER_P3 = {"Acc": ("nI",), "Dat": ("nA",), "Loc": ("nDA",), "Abl": ("nDAn",)}


def _last_vowel(text: str) -> str:
    for c in reversed(text):
        if c in VOWELS:
            return c
    return "e"


def _realize(form: str, template: str) -> str:
    """Kalıbı kelimenin sonuna uyumla ekler."""
    out = form
    skip_vowel = False
    for ch in template:
        ends_vowel = bool(out) and out[-1] in VOWELS
        if ch == "~":
            skip_vowel = ends_vowel
            continue
        if ch == "@":
            if ends_vowel:
                out = out[:-1]
            continue
        if ch == "A":
            if not skip_vowel:
                out += "a" if _last_vowel(out) in _BACK else "e"
        elif ch == "I":
            if not skip_vowel:
                v = _last_vowel(out)
                out += ("u" if v in _ROUND else "ı") if v in _BACK else ("ü" if v in _ROUND else "i")
        elif ch == "D":
            out += "t" if out and out[-1] in _VOICELESS else "d"
        elif ch in "YNS":
            if ends_vowel:
                out += ch.lower()
        else:
            out += ch
        skip_vowel = False
    return out


def _options(ids: tuple[str, ...], k: int, verbal: bool) -> tuple[str, ...] | None:
    m = ids[k]
    prev = next((x for x in reversed(ids[:k]) if x not in ("Verb", "Noun", "Adj", "Zero")), "")
    if m in _AFTER_P3 and prev in ("P3sg", "P3pl"):
        return _AFTER_P3[m]
    if verbal and m in _PERSON_K:
        if prev == "Imp":
            return _PERSON_IMP.get(m)
        if prev in ("Past", "Cond", "Desr"):
            return (_PERSON_K[m],)
        if prev in _TENSES:
            return (_PERSON_Z[m],)
    if m == "Aor" and prev == "Neg":
        return ("z",)
    return _TEMPLATES.get(m)


def _candidates(stem: str, ids: tuple[str, ...], verbal: bool) -> list[str]:
    """Bütün kalıp seçenekleri ve ünsüz yumuşaması (kitap-ı / kitab-ı) için adaylar."""
    choices: list[tuple[str, ...]] = []
    for k in range(len(ids)):
        opts = _options(ids, k, verbal)
        if opts is None:
            return []
        choices.append(opts)
    out: list[str] = []
    for combo in product(*choices):
        forms = [stem]
        for template in combo:
            nxt: list[str] = []
            for f in forms:
                piece = _realize(f, template)[len(f) :] if not template.startswith("@") else None
                if piece is None:
                    nxt.append(_realize(f, template))
                    continue
                nxt.append(f + piece)
                if piece[:1] in VOWELS and f[-1:] in _SOFT and len(f) > 2:
                    soft = f[:-2] + "ng" if f.endswith("nk") else f[:-1] + _SOFT[f[-1]]
                    nxt.append(soft + piece)
            forms = nxt
        out.extend(forms)
        if len(out) > _MAX_CANDIDATES:
            break
    return list(dict.fromkeys(out))


def _readings(word: str) -> list[Analysis]:
    return [a for a, sec in morphology._analyze_cached(word) if sec not in ("Prop", "Abbrv")]


_VERB_BASE = ("Inf1", "Noun", "A3sg")


def _base_prefix(a: Analysis, verbal: bool) -> tuple[str, ...] | None:
    """Sözlük biçiminin (çekimsiz kelimenin) kendi türetme ekleri: "etkinlik" → (Ness, Noun)."""
    ids = a.suffixes
    if verbal:
        return ids[: -len(_VERB_BASE)] if ids[-len(_VERB_BASE) :] == _VERB_BASE else None
    if a.pos != "Noun" or "Inf1" in ids:
        return None
    return ids[:-1] if ids[-1:] == ("A3sg",) else None


def _tails(word: str, lemma_word: str, verbal: bool) -> set[tuple[str, ...]]:
    """Özgün kelimenin, sözlük biçimine göre çekim ekleri. Kelimenin birden fazla okunuşu
    olabilir ("müracaatın": ilgi hâli ya da "senin müracaatın")."""
    out: set[tuple[str, ...]] = set()
    for base in _readings(lemma_word):
        prefix = _base_prefix(base, verbal)
        if prefix is None:
            continue
        for a in _readings(word):
            if a.root == base.root and a.suffixes[: len(prefix)] == prefix:
                out.add(a.suffixes[len(prefix) :])
    return out


@lru_cache(maxsize=20_000)
def inflect_like(new: str, old_word: str, old_lemma: str) -> str | None:
    """``old_word`` (sözlük biçimi ``old_lemma``) hangi eklerle çekimlenmişse ``new`` kelimesini
    aynı eklerle çekimler. Çok kelimeli ``new``in yalnızca son kelimesi çekimlenir.

    inflect_like("başvuru", "müracaatlarınızı", "müracaat") → "başvurularınızı"
    inflect_like("başvurmak", "ediniz", "etmek") → "başvurun"
    Özgün kelimenin okunuşları farklı çekimler veriyorsa ya da biçim doğrulanamazsa None.
    """
    if morphology.backend_name() != "zeyrek":
        return None
    words = new.split()
    old_word, old_lemma = turkish_lower(old_word), turkish_lower(old_lemma)
    if not words or old_word == old_lemma:
        return new
    head = turkish_lower(words[-1])
    verbal = head.endswith(("mak", "mek")) and old_lemma.endswith(("mak", "mek"))
    tails = _tails(old_word, old_lemma, verbal)
    if not tails:
        return None
    # "müracaatın", "mükelleflerin": ilgi hâli ya da "senin …". Kamu metni okura "siz" diye
    # seslenir; başka bir okunuş varsa "sen" okunuşu atılır.
    if len(tails) > 1 and any("P2sg" not in t for t in tails):
        tails = {t for t in tails if "P2sg" not in t}
    # "mükellef" sıfat da olabilir: sıfattan ada geçen okunuş ("Zero Noun A3pl …") aynı kelimedir.
    if len(tails) > 1 and any(t[:1] != ("Zero",) for t in tails):
        tails = {t for t in tails if t[:1] != ("Zero",)}
    if len(words) > 1 and any(t.startswith("P") and t[1:2] in "123" for tail in tails for t in tail):
        # "Valilik koordinasyonunda" → "Valilik birlikte çalışmasında": iyelik eki çok
        # kelimeli karşılığın yalnızca son kelimesine bağlanınca anlam bozulur.
        return None
    results = {_inflect_head(head, tail, verbal) for tail in tails}
    if len(results) != 1:
        return None  # okunuşlar farklı sonuç veriyor: hangisi doğru, yazar bilir
    result = results.pop()
    if result is None:
        return None
    return " ".join([*words[:-1], result])


def _inflect_head(head: str, tail: tuple[str, ...], verbal: bool) -> str | None:
    if tail in ((), ("A3sg",)):
        return head
    stem = head[:-3] if verbal else head
    for base in _readings(head):
        prefix = _base_prefix(base, verbal)
        if prefix is None:
            continue
        expected = prefix + tail
        for cand in _candidates(stem, tail, verbal):
            if any(a.root == base.root and a.suffixes == expected for a in _readings(cand)):
                return cand
    return None
