"""Sözlük verilerinin yüklenmesi ve metin içinde eşleştirilmesi.

Yerleşik sözlükler ``kolaymetin/data/lexicon`` altındadır. Kullanıcılar (ör. belediyeler)
``--sozluk ek.yaml`` ile kendi girdilerini ekleyebilir.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from kolaymetin.models import Token
from kolaymetin.text.morphology import case_set, entry_keys, lemma_keys
from kolaymetin.text.normalize import fold_circumflex, turkish_lower


class LexiconError(ValueError):
    """Sözlük dosyası okunamadı ya da geçersiz."""


@dataclass(frozen=True)
class PhraseEntry:
    phrase: str
    suggestion: str = ""
    note: str = ""
    kind: str = ""
    keys: tuple[frozenset[str], ...] = ()
    # Deyimler: gerçek anlamıyla da sık kullanılır mı, cümlede gerçek anlamı gösteren kelimeler.
    ambiguous: bool = False
    literal_cues: tuple[str, ...] = ()
    # Çok kelimeli girdide her ad kelimesinin durumu (None: denetlenmez). Bkz. case_set.
    cases: tuple[frozenset[str] | None, ...] = ()
    # Sabit terim ("asgari ücret", "emlak vergisi"): en uzun eşleşme olarak içindeki kelimeyi
    # ("asgari") korur, kendisi uyarı vermez. Herkesin bildiği yasal adlar değiştirilemez.
    exempt: bool = False

    @property
    def length(self) -> int:
        return len(self.keys)


@dataclass(frozen=True)
class Abbreviation:
    short: str
    expansion: str = ""
    reading: str = ""
    well_known: bool = False


@dataclass(frozen=True)
class SynonymGroup:
    members: tuple[str, ...]
    preferred: str = ""


@dataclass(frozen=True)
class IndirectPattern:
    pattern: re.Pattern[str]
    suggestion: str
    label: str


@dataclass(frozen=True)
class PhraseMatch:
    entry: PhraseEntry
    start_token: int
    end_token: int  # hariç


@dataclass
class Lexicon:
    jargon: list[PhraseEntry] = field(default_factory=list)
    foreign: list[PhraseEntry] = field(default_factory=list)
    idioms: list[PhraseEntry] = field(default_factory=list)
    vague: list[PhraseEntry] = field(default_factory=list)
    abbreviations: dict[str, Abbreviation] = field(default_factory=dict)
    synonyms: list[SynonymGroup] = field(default_factory=list)
    synonym_entries: list[PhraseEntry] = field(default_factory=list)
    indirect: list[IndirectPattern] = field(default_factory=list)
    common_words: set[str] = field(default_factory=set)
    known_words: set[str] = field(default_factory=set)
    _indexes: dict[str, dict[str, list[PhraseEntry]]] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ yardımcılar
    def abbreviation_readings(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, ab in self.abbreviations.items():
            out[key] = ab.reading
        return out

    def dotted_abbreviations(self) -> frozenset[str]:
        """Cümle bölmede kullanılan noktalı kısaltmalar (küçük harfli, noktalı)."""
        out = set()
        for ab in self.abbreviations.values():
            if ab.short.endswith("."):
                out.add(turkish_lower(ab.short))
        return frozenset(out)

    def find_abbreviation(self, text: str) -> Abbreviation | None:
        return self.abbreviations.get(text) or self.abbreviations.get(turkish_lower(text))

    def is_common(self, token: Token) -> bool:
        keys = token_keys(token)
        return bool(keys & self.common_words) or bool(keys & self.known_words)

    def is_known(self, token: Token) -> bool:
        return bool(token_keys(token) & self.known_words)

    def _index(self, name: str) -> dict[str, list[PhraseEntry]]:
        if name not in self._indexes:
            idx: dict[str, list[PhraseEntry]] = defaultdict(list)
            for entry in getattr(self, name):
                for k in entry.keys[0]:
                    idx[k].append(entry)
            self._indexes[name] = dict(idx)
        return self._indexes[name]

    def match(self, name: str, tokens: list[Token]) -> Iterator[PhraseMatch]:
        """Sözcük dizisinde bir sözlüğün girdilerini arar. En uzun eşleşme kazanır."""
        index = self._index(name)
        words = [(i, t) for i, t in enumerate(tokens) if t.kind == "word"]
        pos = 0
        while pos < len(words):
            i, tok = words[pos]
            keys = token_keys(tok)
            candidates: list[PhraseEntry] = []
            for k in keys:
                candidates.extend(index.get(k, ()))
            best: PhraseEntry | None = None
            # En uzun eşleşme; eşit uzunlukta yüzey biçimi birebir tutan girdi ("suretiyle"
            # girdisi "suret" girdisinden önce), sonra sabit bir sıra (sonuç her çalıştırmada aynı).
            surface = fold_circumflex(turkish_lower(tok.text))
            ordered = sorted(
                set(candidates),
                key=lambda e: (-e.length, surface not in e.keys[0], e.phrase, e.suggestion),
            )
            for entry in ordered:
                if pos + entry.length > len(words):
                    continue
                ok = True
                for j in range(1, entry.length):
                    # Çok kelimeli ifadenin kelimeleri bitişik olmalı: araya noktalama, tire,
                    # parantez ya da sayı girerse ("söz - konusu", "adım (veya) adım") eşleşme yok.
                    if words[pos + j][0] != words[pos + j - 1][0] + 1:
                        ok = False
                        break
                    if not (token_keys(words[pos + j][1]) & entry.keys[j]):
                        ok = False
                        break
                if ok and entry.cases:
                    ok = all(
                        _case_agrees(words[pos + j][1], entry.cases[j]) for j in range(entry.length)
                    )
                if ok:
                    best = entry
                    break
            if best is not None:
                last_i = words[pos + best.length - 1][0]
                yield PhraseMatch(best, i, last_i + 1)
                pos += best.length
            else:
                pos += 1


def _case_agrees(token: Token, cases: frozenset[str] | None) -> bool:
    if cases is None:
        return True
    found = case_set(token.text)
    return found is None or bool(found & cases)


def _entry_cases(phrase: str) -> tuple[frozenset[str] | None, ...]:
    words = [w for w in re.split(r"\s+", phrase.strip()) if w]
    if len(words) < 2:
        return ()
    cases = [None if "'" in w else case_set(w) for w in words]
    # Tamlamanın baş adı her durumu alabilir: "hak sahibi" → "hak sahiplerinin". Son kelime
    # durum ekliyse ("el altından") ek korunur: "eli altında" başka bir anlamdır.
    if cases[-1] is not None and "Nom" in cases[-1]:
        cases[-1] = None
    return tuple(cases)


def token_keys(token: Token) -> frozenset[str]:
    if token.kind != "word":
        return frozenset()
    return lemma_keys(token.text)


def _entry_keys(phrase: str) -> tuple[frozenset[str], ...]:
    words = [w for w in re.split(r"\s+", phrase.strip()) if w]
    out = []
    for w in words:
        base = fold_circumflex(turkish_lower(w))
        if "'" in w:
            keys = {base, base.replace("'", "")}
        else:
            word_keys = entry_keys(w) if len(words) == 1 else lemma_keys(w, strict=True)
            keys = set(word_keys) | {base}
        out.append(frozenset(keys))
    return tuple(out)


def _phrase_entries(items: Iterable[Any] | None, kind: str, key: str = "ifade") -> list[PhraseEntry]:
    out = []
    for item in items or []:
        if isinstance(item, str):
            phrase, suggestion, note = item, "", ""
        elif isinstance(item, dict):
            phrase = str(item.get(key) or item.get("ifade") or item.get("kelime") or "").strip()
            suggestion = str(item.get("oneri") or item.get("anlam") or "").strip()
            note = str(item.get("not") or item.get("aciklama") or "").strip()
            if kind == "idiom" and item.get("anlam") and item.get("oneri"):
                note = str(item.get("anlam"))
        else:
            continue
        if not phrase:
            continue
        variants = [phrase]
        ambiguous = False
        exempt = False
        cues: tuple[str, ...] = ()
        if isinstance(item, dict):
            variants += [str(v) for v in item.get("bicimler") or []]
            ambiguous = bool(item.get("iki_anlamli", False))
            exempt = bool(item.get("sabit", False))
            cues = tuple(fold_circumflex(turkish_lower(str(c))) for c in item.get("gercek") or [])
        for v in variants:
            out.append(PhraseEntry(phrase=phrase, suggestion=suggestion, note=note, kind=kind,
                                   keys=_entry_keys(v), ambiguous=ambiguous, literal_cues=cues,
                                   cases=_entry_cases(v), exempt=exempt))
    return out


def _abbreviations(items: Iterable[Any] | None) -> dict[str, Abbreviation]:
    out: dict[str, Abbreviation] = {}
    for item in items or []:
        if not isinstance(item, dict) or not item.get("kisaltma"):
            continue
        short = str(item["kisaltma"]).strip()
        ab = Abbreviation(
            short=short,
            expansion=str(item.get("acilim") or "").strip(),
            reading=str(item.get("okunus") or "").strip(),
            well_known=bool(item.get("bilinir", False)),
        )
        for key in {short, short.rstrip("."), turkish_lower(short), turkish_lower(short.rstrip("."))}:
            out[key] = ab
    return out


def _synonyms(items: Iterable[Any] | None) -> list[SynonymGroup]:
    out = []
    for item in items or []:
        if isinstance(item, list):
            members, preferred = [str(x) for x in item], ""
        elif isinstance(item, dict):
            members = [str(x) for x in item.get("grup") or []]
            preferred = str(item.get("tercih") or "")
        else:
            continue
        if len(members) < 2:
            continue
        out.append(SynonymGroup(members=tuple(members), preferred=preferred or members[0]))
    return out


def _synonym_entries(groups: list[SynonymGroup], offset: int = 0) -> list[PhraseEntry]:
    """Her grup üyesi için bir ifade girdisi; note alanı grup numarasını taşır."""
    out = []
    for gi, group in enumerate(groups, start=offset):
        for member in group.members:
            out.append(PhraseEntry(phrase=member, suggestion=group.preferred, note=str(gi),
                                   kind="synonym", keys=_entry_keys(member),
                                   cases=_entry_cases(member)))
    return out


def _indirect(items: Iterable[Any] | None) -> list[IndirectPattern]:
    out = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("desen"):
            continue
        try:
            rx = re.compile(str(item["desen"]), re.IGNORECASE)
        except re.error as exc:
            raise LexiconError(f"Geçersiz desen: {item['desen']!r}: {exc}") from exc
        out.append(
            IndirectPattern(rx, str(item.get("oneri") or ""), str(item.get("ad") or item["desen"]))
        )
    return out


def _words(items: Iterable[Any] | None) -> set[str]:
    """Kelime kümesi; bir öğe boşlukla ayrılmış birden fazla kelime içerebilir."""
    out: set[str] = set()
    for item in items or []:
        for w in str(item).split():
            out.add(fold_circumflex(turkish_lower(w)))
    return out


def _data_text(*parts: str) -> str:
    return resources.files("kolaymetin").joinpath("data", *parts).read_text(encoding="utf-8")


def _yaml_data(*parts: str) -> Any:
    return yaml.safe_load(_data_text(*parts))


def _lines(*parts: str) -> list[str]:
    return [
        ln.strip()
        for ln in _data_text(*parts).splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]


@lru_cache(maxsize=1)
def _builtin() -> Lexicon:
    groups = _synonyms(_yaml_data("lexicon", "synonyms.yaml"))
    return Lexicon(
        jargon=_phrase_entries(_yaml_data("lexicon", "jargon.yaml"), "jargon"),
        foreign=_phrase_entries(_yaml_data("lexicon", "foreign.yaml"), "foreign", key="kelime"),
        idioms=_phrase_entries(_yaml_data("lexicon", "idioms.yaml"), "idiom"),
        vague=_phrase_entries(_yaml_data("lexicon", "vague.yaml"), "vague"),
        abbreviations=_abbreviations(_yaml_data("lexicon", "abbreviations.yaml")),
        synonyms=groups,
        synonym_entries=_synonym_entries(groups),
        indirect=_indirect(_yaml_data("lexicon", "indirect.yaml")),
        common_words=_words(_lines("lexicon", "common_words.txt")),
        known_words=_words(_lines("lexicon", "known_words.txt")),
    )


CUSTOM_KEYS = {
    "jargon": "jargon",
    "yabanci": "foreign",
    "deyimler": "idioms",
    "belirsiz": "vague",
    "kisaltmalar": "abbreviations",
    "es_anlamlilar": "synonyms",
    "dolayli_hitap": "indirect",
    "sik_kelimeler": "common_words",
    "bilinen": "known_words",
}


def _check_sections(data: dict[str, Any]) -> dict[str, Any]:
    unknown = set(data) - set(CUSTOM_KEYS)
    if unknown:
        raise LexiconError(
            "Bilinmeyen sözlük bölümü: " + ", ".join(sorted(unknown))
            + ". Geçerli bölümler: " + ", ".join(CUSTOM_KEYS)
        )
    return data


def _read_custom(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return _check_sections(source)
    text: str
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source
                                    and source.strip().endswith((".yaml", ".yml"))):
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise LexiconError(f"Sözlük dosyası bulunamadı: {path}") from exc
    else:
        text = str(source)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LexiconError(f"Sözlük okunamadı (YAML hatası): {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise LexiconError("Sözlük dosyası bir sözlük (anahtar: değer) içermeli.")
    return _check_sections(data)


def load_lexicon(*extra: str | Path | dict[str, Any] | None) -> Lexicon:
    """Yerleşik sözlüğü yükler; verilen ek sözlükleri (dosya yolu, YAML metni ya da dict) ekler."""
    base = _builtin()
    extras = [e for e in extra if e]
    if not extras:
        return base
    lex = Lexicon(
        jargon=list(base.jargon),
        foreign=list(base.foreign),
        idioms=list(base.idioms),
        vague=list(base.vague),
        abbreviations=dict(base.abbreviations),
        synonyms=list(base.synonyms),
        synonym_entries=list(base.synonym_entries),
        indirect=list(base.indirect),
        common_words=set(base.common_words),
        known_words=set(base.known_words),
    )
    for source in extras:
        data = _read_custom(source)
        lex.jargon += _phrase_entries(data.get("jargon"), "jargon")
        lex.foreign += _phrase_entries(data.get("yabanci"), "foreign", key="kelime")
        lex.idioms += _phrase_entries(data.get("deyimler"), "idiom")
        lex.vague += _phrase_entries(data.get("belirsiz"), "vague")
        lex.abbreviations.update(_abbreviations(data.get("kisaltmalar")))
        new_groups = _synonyms(data.get("es_anlamlilar"))
        lex.synonym_entries += _synonym_entries(new_groups, offset=len(lex.synonyms))
        lex.synonyms += new_groups
        lex.indirect += _indirect(data.get("dolayli_hitap"))
        lex.common_words |= _words(data.get("sik_kelimeler"))
        lex.known_words |= _words(data.get("bilinen"))
    return lex


def builtin_counts() -> dict[str, int]:
    """Yerleşik sözlüklerdeki girdi sayıları (tekil ifadeler)."""
    lex = _builtin()
    return {
        "jargon": len({e.phrase for e in lex.jargon if not e.exempt}),
        "yabanci": len({e.phrase for e in lex.foreign if not e.exempt}),
        "deyimler": len({e.phrase for e in lex.idioms}),
        "belirsiz": len({e.phrase for e in lex.vague}),
        "kisaltmalar": len({a.short for a in lex.abbreviations.values()}),
        "es_anlamlilar": len(lex.synonyms),
        "dolayli_hitap": len(lex.indirect),
        "sik_kelimeler": len(lex.common_words),
        "bilinen": len(lex.known_words),
    }


def rehber_data_path() -> Path:
    return Path(str(resources.files("kolaymetin").joinpath("data")))
