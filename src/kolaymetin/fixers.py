"""Kurallardan sonra çalışan düzeltmeler: bir kuralın kendisinin veremediği, ama bulgunun
gösterdiği yerde kesin olarak yapılabilen dönüşümler.

- Resmî zaman ekleri (KD-K04 uzun kelime, KD-C04, KD-C03 bulgularında):
  "beklenmektedir" → "bekleniyor", "alınmayacaktır" → "alınmayacak",
  "oluşturulmuştur" → "oluşturuldu", "yapılmalıdır" → "yapılmalı".
- Dolaylı seslenme (KD-C11, KD-C07 bulgularında):
  "Formların doldurulması gerekmektedir." → "Formları doldurun."
  "Vatandaşlarımızın suyu temin etmeleri rica olunur." → "Lütfen suyu temin edin."

Her yeni kelime ek üreteciyle kurulur ve zeyrek'le doğrulanır (bkz. text/inflect.py).
"""

from __future__ import annotations

from kolaymetin.models import Document, Finding, Fix, Sentence, Token
from kolaymetin.text.inflect import inflect_verb, recase
from kolaymetin.text.normalize import turkish_lower, turkish_upper

VOWELS = "aeıioöuüâîû"
_BACK = "aıouâû"

# "-mAktAdIr" (şimdiki zaman, resmî) → "-Iyor"; "-AcAktIr" → "-AcAk"; "-mIştIr" → "-DI".
_TENSE_SIMPLIFY: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("Prog2", "A3sg", "Cop"), ("Prog1", "A3sg")),
    (("Prog2", "A3pl", "Cop"), ("Prog1", "A3pl")),
    (("Fut", "A3sg", "Cop"), ("Fut", "A3sg")),
    (("Fut", "A3pl", "Cop"), ("Fut", "A3pl")),
    (("Narr", "A3sg", "Cop"), ("Past", "A3sg")),
    (("Neces", "A3sg", "Cop"), ("Neces", "A3sg")),
)
_WORD_RULES = ("KD-K04", "KD-C04", "KD-C03")  # öncelik sırası; bir kelimeye tek düzeltme

# Okura dolaylı seslenen yardımcı söz: "… doldurulması gerekmektedir", "… rica olunur".
_NECESSITY = frozenset({"gerekmektedir", "gerekir", "gerekiyor", "gerekmekte", "zorunludur",
                        "şarttır", "lazımdır", "gereklidir", "gerekli"})
_REQUEST = (("önemle", "rica", "olunur"), ("önemle", "rica", "ederiz"),  # uzun kalıp önce
            ("rica", "olunur"), ("rica", "ederiz"), ("rica", "ediyoruz"))


def _infinitive(root: str) -> str:
    v = next((c for c in reversed(root) if c in VOWELS), "e")
    return root + ("mak" if v in _BACK else "mek")


def _keep_case(old: str, new: str) -> str:
    return turkish_upper(new[:1]) + new[1:] if old[:1].isupper() else new


def simplify_verb(tok: Token) -> str | None:
    """Resmî zaman ekini konuşma diline çevirir; doğrulanamazsa None."""
    a = tok.analysis
    if a is None or a.source != "zeyrek" or a.pos != "Verb" or tok.text != tok.base:
        return None
    for old, new in _TENSE_SIMPLIFY:
        if a.suffixes[-len(old) :] == old:
            word = inflect_verb(_infinitive(turkish_lower(a.root)), a.suffixes[: -len(old)] + new)
            return _keep_case(tok.text, word) if word else None
    return None


def _adverbial(t: Token) -> bool:
    """Zarf öbeğini bitiren kelime: "sonra", "için", "süresince", "tarihinde"."""
    a = t.analysis
    return a is not None and (a.pos in ("Adv", "Postp") or a.suffixes[-1:] in (
        ("Loc",), ("Abl",), ("Equ",), ("Ins",)))


def _words(s: Sentence) -> list[Token]:
    return [t for t in s.tokens if t.kind == "word"]


def necessity_fix(doc: Document, s: Sentence) -> tuple[Token, Fix] | None:
    """"X-in Y-ilmesi gerekmektedir" → "X-i Y-in". Döner: (fiil, düzeltme)."""
    words = _words(s)
    lows = [t.lower for t in words]
    aux_len = 0
    if lows and lows[-1] in _NECESSITY:
        aux_len = 1
    request = False
    for pat in _REQUEST:
        if tuple(lows[-len(pat) :]) == pat:
            aux_len, request = len(pat), True
            break
    if not aux_len or len(words) <= aux_len:
        return None
    verb = words[-aux_len - 1]
    a = verb.analysis
    if a is None or a.source != "zeyrek" or "Inf2" not in a.suffixes or verb.text != verb.base:
        return None
    ids = a.suffixes
    tail_ok = ids[-1:] in (("P3sg",), ("P3pl",)) or (request and ids[-2:] in (("P3sg", "Acc"), ("P3pl", "Acc")))
    if not tail_ok:
        return None
    stem_ids = ids[: ids.index("Inf2")]
    passive = "Pass" in stem_ids
    if passive:
        stem_ids = stem_ids[: stem_ids.index("Pass")]
    while stem_ids[-1:] == ("Verb",):
        stem_ids = stem_ids[:-1]
    imperative = inflect_verb(_infinitive(turkish_lower(a.root)), (*stem_ids, "Imp", "A2pl"))
    if imperative is None:
        return None
    # İlgi hâlindeki ad: edilgende nesne ("Formların" → "Formları"), etkende özne (düşer).
    before = words[: len(words) - aux_len - 1]
    gen = None
    for t in reversed(before):
        ta = t.analysis
        if ta is not None and ta.is_finite:
            break
        if ta is not None and ta.suffixes[-1:] == ("Gen",):
            gen = t
            break
    changes: list[tuple[int, int, str]] = []
    first = words[0]
    if passive:
        if gen is not None:
            assert gen.analysis is not None
            acc = recase(gen.text, gen.analysis.root, gen.analysis.suffixes,
                         (*gen.analysis.suffixes[:-1], "Acc"))
            if acc is None:
                return None
            changes.append((gen.start, gen.end, acc))
    else:
        if gen is None:
            return None
        gi = words.index(gen)
        nxt = words[gi + 1]
        if gen is first:
            changes.append((gen.start, nxt.start + 1, turkish_upper(nxt.text[:1])))
        elif _adverbial(words[gi - 1]) or doc.text[words[gi - 1].end : gen.start].strip() == ",":
            changes.append((gen.start, nxt.start, ""))  # "Kesinti süresince vatandaşlarımızın"
        else:
            return None  # öznenin önünde niteleyen kelimeler olabilir: "yaşlı seçmenlerimizin"
    # "… tedbirleri almaları ve suyu bulmaları rica olunur": bağlanan ad-fiiller de emir olur.
    vi = words.index(verb)
    for j in range(1, vi):
        prev, conj = words[j - 1], words[j]
        pa = prev.analysis
        if conj.lower != "ve" or pa is None or "Inf2" not in pa.suffixes:
            continue
        if pa.suffixes[-1:] != ids[-1:] or ("Pass" in pa.suffixes) != passive:
            continue
        p_ids = pa.suffixes[: pa.suffixes.index("Inf2")]
        if passive:
            p_ids = p_ids[: p_ids.index("Pass")]
        while p_ids[-1:] == ("Verb",):
            p_ids = p_ids[:-1]
        other = inflect_verb(_infinitive(turkish_lower(pa.root)), (*p_ids, "Imp", "A2pl"))
        if other is None:
            return None
        changes.append((prev.start, prev.end, other))
    end = words[-1].end
    changes.append((verb.start, end, imperative))
    if request:
        a0, b0, t0 = changes[0]
        head = t0 or doc.text[a0:b0]
        if a0 == first.start:
            proper = first.is_proper_name or first.is_abbreviation
            lowered = head if proper else turkish_lower(head[:1]) + head[1:]
            changes[0] = (a0, b0, "Lütfen " + lowered)
        else:
            changes.insert(0, (first.start, first.start + 1, "Lütfen " + (
                first.text[:1] if first.is_proper_name else turkish_lower(first.text[:1]))))
    changes.sort()
    parts, pos = [], changes[0][0]
    for x, y, text in changes:
        if x < pos:
            return None
        parts.append(doc.text[pos:x] + text)
        pos = y
    return verb, Fix(start=changes[0][0], end=changes[-1][1], text="".join(parts))


def attach_fixes(doc: Document, findings: list[Finding]) -> None:
    """Düzeltmesi olmayan bulgulara yukarıdaki dönüşümleri bağlar (normalleştirilmiş ofsetlerde)."""
    by_start: dict[int, tuple[Sentence, Token]] = {
        t.start: (s, t) for s in doc.sentences for t in s.tokens if t.kind == "word"
    }
    done: set[int] = {f.fix.start for f in findings if f.fix is not None}
    # Dolaylı seslenme: cümle başına bir kez, KD-C11 ya da KD-C07 bulgusuna.
    seen: set[int] = set()
    for f in findings:
        if f.fix is not None or f.rule_id not in ("KD-C11", "KD-C07") or f.sentence_index is None:
            continue
        if f.sentence_index in seen:
            continue
        s = doc.sentences[f.sentence_index]
        found = necessity_fix(doc, s)
        if found is None:
            continue
        # Bulgu fiili ("doldurulması gerekmektedir") ya da dolaylı hitabı ("Vatandaşlarımızın")
        # işaretler; düzeltme ikisini birlikte değiştirir.
        verb, fix = found
        seen.add(f.sentence_index)
        f.fix = fix
        done.add(verb.start)
    # Resmî zaman ekleri: kelimeyi işaretleyen ilk bulguya.
    for rule in _WORD_RULES:
        for f in findings:
            if f.fix is not None or f.rule_id != rule or f.start in done:
                continue
            hit = by_start.get(f.start)
            if hit is None or hit[1].end != f.end:
                continue
            new = simplify_verb(hit[1])
            if new is not None and new != hit[1].text:
                f.fix = Fix(start=f.start, end=f.end, text=new)
                done.add(f.start)
