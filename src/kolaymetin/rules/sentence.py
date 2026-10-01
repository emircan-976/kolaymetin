"""Cümle düzeyi kurallar (KD-C01 … KD-C11)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from kolaymetin.models import Analysis, Document, Finding, Sentence, Severity, Token
from kolaymetin.profiles import RuleConfig
from kolaymetin.rules.base import (
    Rule,
    body_sentences,
    join_quoted,
    lexicon_covered,
    quote,
    register,
    word_tokens,
)
from kolaymetin.text.morphology import all_lemmas
from kolaymetin.text.normalize import turkish_lower

VOWELS = "aeıioöuüâîû"
CLAUSE_CONNECTORS = frozenset({"çünkü", "ancak", "fakat", "ama", "ki", "oysa", "halbuki", "zira"})
SPLIT_WORDS = CLAUSE_CONNECTORS | {"ve", "veya", "ya", "ayrıca", "böylece"}
PREDICATE_WORDS = frozenset({"var", "yok", "değil"})
# Fiil okuması da olan edat ve bağlaçlar yüklem değildir: "için" (iç-in, emir), "göre",
# "kadar", "üzere", "rağmen" … "iyi bir eğitim için, …" noktayla bitirilemez.
NON_PREDICATES = frozenset(
    {"için", "göre", "kadar", "gibi", "üzere", "rağmen", "karşın", "dolayı", "beri", "diye",
     "ile", "ise", "bile", "sonra", "önce"}
)
NEGATIVE_WORDS = frozenset({"değil", "yok", "hiç", "hiçbir"})


# Biçimce zarf-fiil ya da sıfat-fiil olan ama yan cümle kurmayan kelimeler: "birey olarak",
# "küresel olarak", "olabildiğince", "giderek artıyor".
LEXICAL_ADVERBS = frozenset({"olarak", "olabildiğince", "giderek", "gittikçe", "olmaksızın"})


def _is_lexical_adverb(words: list[Token], i: int) -> bool:
    low = words[i].lower
    if low in LEXICAL_ADVERBS:
        return True
    # "dâhil olmak üzere", "başta olmak üzere": kalıp, ad-fiil değil
    return low == "olmak" and i + 1 < len(words) and words[i + 1].lower == "üzere"


def _wa(token: Token) -> Analysis | None:
    return token.analysis if token.kind == "word" else None


def _split_hint(sentence: Sentence) -> str | None:
    """Cümlenin ortasına en yakın bölme noktasını önerir."""
    words = sentence.words
    if len(words) < 4:
        return None
    middle = len(words) / 2
    candidates: list[tuple[float, str]] = []
    idx = 0
    prev_word: Token | None = None
    embedded = _embedded(sentence)
    word_list = word_tokens(sentence)
    lexical = {w.start for i, w in enumerate(word_list) if _is_lexical_adverb(word_list, i)}
    for tok in sentence.tokens:
        if tok.is_wordlike:
            idx += 1
        # Yalnızca bir yan cümlenin bittiği yerde bölmeyi öner. "Çorum Belediyesi," ya da
        # "verilere göre," sonrasında bölmek cümlenin yüklemsiz bir parçasını bırakır. Noktalı
        # virgülden önce de yüklem olmalı: "Bağış aralığı ortalama; …", "gününden itibaren; …"
        # noktayla bitirilince cümle olmaz.
        clause_before = (
            prev_word is not None
            and (_ends_clause(prev_word) or turkish_lower(prev_word.text) in PREDICATE_WORDS)
            and prev_word.start not in embedded
            and prev_word.start not in lexical
        )
        if tok.kind == "punct" and tok.text in ",;:" and 1 < idx < len(words) - 1:
            if clause_before:
                assert prev_word is not None
                # Zarf-fiilden ("edildiğinde,", "çizerek,") sonra nokta konunca yüklemsiz bir
                # parça kalır; fiili çekimlemek gerekir: "bölün".
                pa = prev_word.analysis
                converb = pa is not None and pa.is_converb and not pa.is_finite
                if converb:
                    candidates.append((abs(idx - middle) + 0.5, f"{quote(prev_word.text)} kelimesinden sonra bölün"))
                else:
                    candidates.append((abs(idx - middle), f"{quote(prev_word.text)} kelimesinden sonra nokta koyun"))
        elif tok.kind == "word" and 1 < idx < len(words) and tok.start not in embedded and (
            _split_connector(tok)
            or (turkish_lower(tok.text) in SPLIT_WORDS - {"ki"} and clause_before)
        ):
            candidates.append((abs(idx - middle), f"{quote(tok.text)} kelimesinden önce nokta koyun"))
        elif (
            tok.kind == "word" and _ends_clause(tok) and tok.start not in embedded
            and tok.start not in lexical
            and 1 < idx < len(words) - 1
        ):
            candidates.append((abs(idx - middle) + 0.5, f"{quote(tok.text)} kelimesinden sonra bölün"))
        if tok.kind == "word":
            prev_word = tok
    if not candidates:
        return None
    hint = min(candidates, key=lambda c: c[0])[1]
    return hint[:1].upper() + hint[1:] + "."


def _split_connector(tok: Token) -> bool:
    """Önünden bölünebilen bağlaç. "ki" değil: "De ki:", "Unutmayalım ki," ve "dedi ki"
    kalıplarında "ki" önceki kelimeye bağlıdır; önünden bölmek anlamsız bir parça bırakır."""
    return tok.lower in CLAUSE_CONNECTORS and tok.lower != "ki"


def _ends_clause(tok: Token) -> bool:
    a = tok.analysis
    return a is not None and (a.is_converb or a.is_finite) and tok.lower not in NON_PREDICATES


_QUOTE_CHARS = frozenset("\"'‘’“”«»")


def _embedded(sentence: Sentence) -> set[int]:
    """Ana cümlenin yüklemi olamayacak kelimelerin başlangıç konumları.

    - Parantez içindekiler: "Uygulamayı seç (Emniyet yazsın)."
    - "diye"den önceki yüklem: "Kimse görmesin diye kapıyı kilitlerim."
    - Aktarılan söz: "'UZAK DUR' diye bağırırım", "'UZAK DUR' derim".
    """
    toks = sentence.tokens
    out: set[int] = set(_quoted(sentence))
    depth = 0
    for i, t in enumerate(toks):
        if t.kind == "punct" and t.text == "(":
            depth += 1
            continue
        if t.kind == "punct" and t.text == ")":
            depth = max(0, depth - 1)
            continue
        if t.kind != "word":
            continue
        if depth:
            out.add(t.start)
            continue
        j = i + 1
        quoted = False
        comma = False
        while j < len(toks) and toks[j].kind != "word" and toks[j].text in _SPEECH_GAP:
            quoted = quoted or toks[j].text in _QUOTE_CHARS
            comma = comma or toks[j].text == ","
            j += 1
        if j >= len(toks) or toks[j].kind != "word":
            continue
        nxt = turkish_lower(toks[j].text)
        nxt_analysis = toks[j].analysis
        nxt_lemma = nxt_analysis.lemma if nxt_analysis is not None else ""
        # "Yalan çok fenadır, dedi.", "Hep Pervin'le otursun! diye haykırdı.", "…, derdim."
        says = nxt_lemma == "demek" or (
            (comma or quoted) and _last_word(toks, j) and "demek" in all_lemmas(toks[j].text)
        )
        speech = says and (quoted or (comma and _last_word(toks, j)))
        if nxt == "diye" or speech:
            out.add(t.start)
    return out


_SPEECH_GAP = _QUOTE_CHARS | {",", "!", "?", "…"}


def _last_word(toks: list[Token], j: int) -> bool:
    return not any(t.kind == "word" for t in toks[j + 1 :])


def _quoted(sentence: Sentence) -> set[int]:
    """Cümlenin içine alıntılanmış sözün kelimeleri: “De ki: Hiç bilenlerle bilmeyenler bir
    olur mu?” ayeti … Alıntının yüklemi, olumsuzluğu ve bağlacı yazarın cümlesine ait değildir.
    Bütün cümle tırnak içindeyse (konuşma) alıntı sayılmaz."""
    toks = sentence.tokens
    words = [t for t in toks if t.kind == "word"]
    out: set[int] = set()
    open_at: int | None = None
    ascii_open: int | None = None
    spans: list[tuple[int, int]] = []
    for i, t in enumerate(toks):
        if t.text == "“":
            open_at = i
        elif t.text == "”" and open_at is not None:
            spans.append((open_at, i))
            open_at = None
        elif t.text == '"':
            if ascii_open is None:
                ascii_open = i
            else:
                spans.append((ascii_open, i))
                ascii_open = None
    for a, b in spans:
        inside = [t for t in toks[a + 1 : b] if t.kind == "word"]
        if inside and len(inside) < len(words):
            out.update(t.start for t in inside)
    return out


@register
class LongSentence(Rule):
    id = "KD-C01"
    name = "Uzun cümle"
    level = "cümle"
    default_severity = "uyarı"
    summary = "Cümle çok fazla kelime içeriyor."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        warn = int(cfg.get("warn_above", 8))
        err = int(cfg.get("error_above", 12))
        for s in body_sentences(doc):
            n = s.word_count
            if n <= warn:
                continue
            sev: Severity = "hata" if n > err else "uyarı"
            hint = _split_hint(s)
            yield self.finding(
                doc, cfg, s.start, s.end,
                message=f"Bu cümle çok uzun: {n} kelime. En fazla {warn} kelime yazın.",
                explanation=(
                    "Uzun cümleyi okumak ve akılda tutmak zordur. "
                    "Her cümlede tek bir bilgi verin."
                ),
                suggestion=hint or "Cümleyi iki ya da üç kısa cümleye bölün.",
                sentence=s,
                severity=sev,
            )


@register
class ManyClauses(Rule):
    id = "KD-C02"
    name = "Tek cümlede birden fazla bilgi"
    level = "cümle"
    default_severity = "uyarı"
    summary = "Cümlede birden fazla çekimli yüklem ya da bağlaçla bağlanmış yan cümle var."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        max_pred = int(cfg.get("max_predicates", 1))
        for s in body_sentences(doc):
            words = word_tokens(s)
            embedded = _embedded(s)
            final = _clause_final(s)
            predicates: list[Token] = []
            for i, t in enumerate(words):
                if t.start in embedded:
                    continue
                low = turkish_lower(t.text)
                a = t.analysis
                is_pred = (
                    a is not None and a.is_finite and a.conf("is_finite") >= 0.5
                    and low not in NON_PREDICATES
                ) or low in PREDICATE_WORDS
                # Türkçede yüklem yan cümlenin sonundadır: ardından virgül, bağlaç ya da cümle
                # sonu gelir. Arada duran "çekimli" okuma ("boşa" = boşamak) yüklem değildir.
                if not is_pred or t.start not in final:
                    continue
                nxt = words[i + 1] if i + 1 < len(words) else None
                if nxt is not None and nxt.analysis is not None and nxt.analysis.lemma == "olmak":
                    continue  # "yapmış olacak" gibi birleşik çekim: tek yüklem
                if predicates and turkish_lower(predicates[-1].text) == low:
                    continue  # "Yok, yok!", "Gel, gel.": yineleme tek bilgidir
                if nxt is not None and turkish_lower(nxt.text) == "ki":
                    continue  # "Unutmayalım ki, …", "Biliyorum ki …": ardındaki cümleyi açar
                predicates.append(t)
            connectors = [
                t for t in words[1:]
                if _split_connector(t) and t.start not in embedded
            ]
            split_connectors = connectors
            infos = len(predicates)
            if connectors and predicates and _connector_between(s, connectors):
                infos = max(infos, 2)
            if infos <= max_pred:
                continue
            first_pred = predicates[0] if predicates else None
            if split_connectors:
                split = f"Cümleyi {quote(split_connectors[0].text)} kelimesinden önce bölün."
            elif first_pred is not None and first_pred is not words[-1]:
                split = f"{quote(first_pred.text)} kelimesinden sonra nokta koyun."
            else:
                split = "Cümleyi bilgi sayısı kadar kısa cümleye bölün."
            yield self.finding(
                doc, cfg, s.start, s.end,
                message=f"Bu cümlede {infos} ayrı bilgi var. Her bilgiyi ayrı bir cümleye yazın.",
                explanation=(
                    "Bir cümlede birden fazla bilgi olunca okur hangisinin önemli olduğunu "
                    "anlamakta zorlanır."
                ),
                suggestion=split,
                sentence=s,
            )


_CLAUSE_FOLLOWERS = CLAUSE_CONNECTORS | {"ve", "veya", "ya", "yahut", "yoksa", "diye", "de", "da"}


def _clause_final(sentence: Sentence) -> set[int]:
    """Bir yan cümleyi ya da cümleyi bitirebilecek kelimelerin başlangıç konumları: son kelime
    ve ardından noktalama (, ; : ! ? …) ya da bağlaç gelen kelimeler."""
    toks = sentence.tokens
    out: set[int] = set()
    words = [i for i, t in enumerate(toks) if t.kind == "word"]
    if words:
        out.add(toks[words[-1]].start)
    for i in words:
        j = i + 1
        while j < len(toks) and toks[j].kind == "punct" and toks[j].text in _QUOTE_CHARS | {")"}:
            j += 1
        if j >= len(toks):
            out.add(toks[i].start)
            continue
        nxt = toks[j]
        if (nxt.kind == "punct" and nxt.text in ",;:!?….-") or (
            nxt.kind == "word" and turkish_lower(nxt.text) in _CLAUSE_FOLLOWERS
        ):
            out.add(toks[i].start)
    return out


def _connector_between(sentence: Sentence, connectors: list[Token]) -> bool:
    """Bağlacın iki yanında da en az iki kelime var mı?"""
    words = sentence.words
    for c in connectors:
        pos = next((i for i, w in enumerate(words) if w.start == c.start), -1)
        if pos >= 2 and len(words) - pos - 1 >= 2:
            return True
    return False


def active_form(a: Analysis) -> str | None:
    """Edilgen biçimden etken biçim üretir: alınacaktır → alacak. Emin değilse None."""
    if "Pass" not in a.suffixes or not a.stem_surface:
        return None
    idx = a.suffixes.index("Pass")
    rest_ids = a.suffixes[idx + 1 :]
    if "Pass" in rest_ids or "Aor" in rest_ids[:3] or "AorPart" in rest_ids[:3]:
        return None
    before = turkish_lower(a.stem_surface + "".join(a.suffix_surfaces[:idx]))
    after = turkish_lower("".join(a.suffix_surfaces[idx + 1 :]))
    if not after or not before:
        return None
    if after[0] not in VOWELS and before.endswith("d"):
        before = before[:-1] + "t"  # ed-il-mek → et-mek
    if re.match(r"[ıiuü]yor", after) and before[-1] in VOWELS:
        # bekle-n-iyor → bekl-iyor: gövde ünlüsü düşer, -yor ünlüsü öncekine uyar.
        if len(before) <= 2:
            return None  # ye-n-iyor → yiyor, de-n-iyor → diyor: düzensiz
        before = before[:-1]
        last = next((c for c in reversed(before) if c in VOWELS), "e")
        after = {"a": "ı", "ı": "ı", "e": "i", "i": "i", "o": "u", "u": "u", "ö": "ü", "ü": "ü"}.get(
            last, after[0]
        ) + after[1:]
    elif before[-1] in "çfhkpsşt" and after[0] in "dc":
        after = {"d": "t", "c": "ç"}[after[0]] + after[1:]  # ed-il-diği → et-tiği, yap-ıl-dı → yap-tı
    elif after[0] in VOWELS and before[-1] in VOWELS:
        after = "y" + after  # sağla-n-acak → sağla-y-acak
    result = before + after
    if any(x in rest_ids for x in ("Fut", "Past", "Narr")) and re.search(r"[dt][ıiuü]r$", result):
        result = result[:-3]
    return result


_ADDRESSEE = frozenset({"A1sg", "A2sg", "A1pl", "A2pl", "Imp"})


def _addressed_reflexive(a: Analysis) -> bool:
    """Dönüşlü okunabilen fiil okura ya da konuşana yöneltilmiş mi?

    "Soğuktan korunun", "Hazırlanın", "yıkanıyoruz": işi yapan okurun kendisidir. "Gripten
    korunmak için": mastar genel bir öğüttür. Bunlarda "Kim yapıyor?" sorusu yersizdir.
    Emir kipindeki edilgen de ("korunun") her zaman okura seslenir.
    """
    after = a.suffixes[a.suffixes.index("Pass") + 1 :] if "Pass" in a.suffixes else ()
    if "Imp" in after and ("A2sg" in after or "A2pl" in after):
        return True
    if not a.is_reflexive_candidate:
        return False
    return any(x in _ADDRESSEE for x in after) or "Inf1" in after


@register
class Passive(Rule):
    id = "KD-C03"
    name = "Edilgen yapı"
    level = "cümle"
    default_severity = "uyarı"
    summary = "İşi kimin yaptığı belli değil (edilgen çatı)."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        # "rica olunur" → "lütfen …": KD-K01 bütün kalıbı değiştirir; içindeki edilgen ayrıca sayılmaz.
        replaced = lexicon_covered(doc, ("jargon",))
        for s in body_sentences(doc):
            words = word_tokens(s)
            for idx, t in enumerate(words):
                a = t.analysis
                if a is None or not a.is_passive or t.is_abbreviation or t.start in replaced:
                    continue
                after_pass = a.suffixes[a.suffixes.index("Pass") :] if "Pass" in a.suffixes else ()
                if any(x in after_pass for x in ("Ness", "Inf3", "ActOf", "Agt")):
                    continue  # "okunabilirlik", "okunuş", "yüklenici" gibi sözlükleşmiş adlar
                if _addressed_reflexive(a):
                    continue  # "Soğuktan korunun.", "Gripten korunmak için": yapan belli
                ambiguous = a.is_reflexive_candidate or a.conf("is_passive") < 0.6
                adjectival = a.is_participle and not a.is_finite and not a.is_nominalized
                sev: Severity | None = "bilgi" if (ambiguous or adjectival) else None
                # Etken biçim yalnızca yüklem için önerilir. Sıfat-fiilde ve ad-fiilde çatıyı
                # değiştirmek anlamı bozar: "ambalajı açılmış ürün" → "ambalajı açmış ürün",
                # "öngörülenden erken" → "öngörenden erken". Dönüşlü fiilde de öyle:
                # "korunmak" ≠ "korumak".
                active = active_form(a) if a.is_finite and not ambiguous else None
                if active:
                    suggestion = (
                        f"Kim yapıyor? Onu cümlenin başına yazın ve {quote(active)} biçimini "
                        "kullanın."
                    )
                elif adjectival or a.is_nominalized:
                    suggestion = (
                        "Kim yapıyor? Yapanı söyleyen ayrı bir cümle kurun. Örnek: 'teslim "
                        "edilen belgeler' → 'Belgeleri teslim ettiniz.'"
                    )
                else:
                    suggestion = (
                        "Kim yapıyor? Onu cümlenin başına yazın. Örnek: 'Başvurular "
                        "alınacaktır.' → 'Belediye başvuruları alacak.'"
                    )
                agent = _agent_before(words, idx)
                if ambiguous:
                    message = (
                        f"{quote(t.text)} hem 'kendi kendine yapmak' hem 'başkası yapmak' "
                        "anlamına gelebilir. İşi kimin yaptığını kontrol edin."
                    )
                elif turkish_lower(agent) in ("kim", "kimler"):
                    # "Kim tarafından imzalanacak?": yapan bir soru kelimesi, özne yapılamaz.
                    message = "Bu soru edilgen. 'Kim tarafından' yerine doğrudan sorun."
                    suggestion = (
                        f"Soruyu etken kurun: 'Kim {active}?'" if active else
                        "Soruyu etken kurun. Örnek: 'Kim tarafından imzalanacak?' → 'Kim imzalayacak?'"
                    )
                elif agent:
                    # "Belediye tarafından yapılacak": yapan belli ama cümlenin ortasına itilmiş.
                    message = (
                        f"Bu cümle edilgen. İşi yapan ({quote(agent)}) 'tarafından' ile "
                        "söylenmiş. Yapanı özne yapın."
                    )
                    suggestion = (
                        f"'tarafından' kelimesini silin, {quote(agent)} özne olsun"
                        + (f" ve {quote(active)} biçimini kullanın." if active else ".")
                        + " Örnek: 'Belediye tarafından yapılacak.' → 'Belediye yapacak.'"
                    )
                else:
                    message = "Bu cümlede işi kimin yaptığı belli değil. Yapanı söyleyin."
                yield self.finding(
                    doc, cfg, t.start, t.end,
                    message=message,
                    explanation=(
                        f"{quote(t.text)} edilgen bir fiil. Edilgen cümlede işi yapan kişi ya da "
                        "kurum görünmez. Okur 'Bunu kim yapacak?' diye sorar."
                    ),
                    suggestion=suggestion,
                    sentence=s,
                    severity=sev,
                    confidence=a.conf("is_passive"),
                )


def _agent_before(words: list[Token], idx: int) -> str:
    """Edilgen fiilden hemen önce "X tarafından" varsa X ("belediye tarafından yapılacak").

    Arada en çok beş kelime olabilir ve başka bir fiil olmamalı: "işveren tarafından beğenilmeyen
    davranışların anlatıldığı" cümlesinde "anlatıldığı" fiilini işveren yapmaz."""
    for back in range(1, 7):
        j = idx - back
        if j < 1:
            break
        w = words[j]
        if w.lower == "tarafından":
            return words[j - 1].text
        a = w.analysis
        if a is not None and (a.is_finite or a.is_participle or a.is_converb or a.is_passive):
            break
    return ""


def _negation_hint(t: Token, s: Sentence) -> str:
    """Olumsuzluğun türüne göre öneri: yasak, "değil", "yok", "-emez", düz olumsuz bilgi."""
    low = turkish_lower(t.base or t.text)
    a = t.analysis
    ids = a.suffixes if a is not None else ()
    if "Imp" in ids and "Neg" in ids:
        return (
            "Ne yapılmaması gerektiğini değil, ne yapılması gerektiğini söyleyin. Örnek: "
            "'Suyu boşa harcamayın.' → 'Suyu az kullanın.'"
        )
    if low.startswith("değil"):
        return "Olumlu karşılığını yazın. Örnek: 'Bu hizmet ücretli değil.' → 'Bu hizmet ücretsiz.'"
    if low == "yok":
        return (
            "Olmayanı değil, olanı söyleyin. Örnek: 'Bu hafta pazar yok.' → 'Pazar gelecek hafta "
            "kurulacak.'"
        )
    if low.startswith(("hiç", "hiçbir")):
        return "Olumlu ve kesin söyleyin. Örnek: 'Hiçbir ücret alınmaz.' → 'Bu hizmet ücretsiz.'"
    if "Unable" in ids:
        return (
            "Okurun neyi yapabileceğini söyleyin. Örnek: 'Açılmış ürün iade edilemez.' → 'Kapalı "
            "ürünü geri verebilirsiniz.'"
        )
    if s.text.rstrip().endswith("?"):
        return "Soruyu olumlu sorun. Örnek: 'Gelmeyecek misiniz?' → 'Gelecek misiniz?'"
    return (
        "Olumlu söyleyebiliyorsanız olumlu söyleyin. Olumsuzluk önemli bir bilgiyse cümleyi kısa "
        "tutun. Örnek: 'Su kesilmeyecek.' → 'Su akmaya devam edecek.'"
    )


@register
class Negation(Rule):
    id = "KD-C04"
    name = "Olumsuz anlatım"
    level = "cümle"
    default_severity = "uyarı"
    summary = "Cümle olumsuz kurulmuş."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s in body_sentences(doc):
            hits: list[tuple[Token, float]] = []
            quoted = _quoted(s)
            for t in word_tokens(s):
                if t.is_proper_name or t.start in quoted:
                    continue  # "Ali Korkmaz", "Mehmet Sönmez"; alıntılanan söz
                low = turkish_lower(t.base or t.text)
                a = t.analysis
                if low == "yok" and _is_predicate(s, t):
                    # "Yarın su yok.": bunun daha sade olumlu bir söyleyişi yoktur.
                    continue
                lexical = low in NEGATIVE_WORDS or low.startswith(("değil", "hiçbir"))
                morph = a is not None and a.is_negative and a.conf("is_negative") >= 0.5
                if not (lexical or morph):
                    continue
                hits.append((t, 1.0 if lexical else (a.conf("is_negative") if a is not None else 0.6)))
            if not hits:
                continue
            # Cümle başına tek bulgu: olumsuz kelime sayısı kadar ceza kesmek aynı sorunu
            # birkaç kez saymak olur.
            t = hits[0][0]
            listed = join_quoted(h.text for h, _c in hits)
            yield self.finding(
                doc, cfg, t.start, t.end,
                message="Bu cümle olumsuz. Olumlu söylemeyi deneyin.",
                explanation=(
                    f"{listed} olumsuz bir anlam taşıyor. Olumsuz cümleyi anlamak daha "
                    "zordur. Okur neyi yapması gerektiğini bilmek ister."
                ),
                suggestion=_negation_hint(t, s),
                sentence=s,
                confidence=max(c for _h, c in hits),
            )


def _is_predicate(s: Sentence, t: Token) -> bool:
    """Kelime cümlenin ya da bir yan cümlenin son kelimesi mi ("Su yok, elektrik yok.")?"""
    toks = s.tokens
    i = next((k for k, x in enumerate(toks) if x is t), -1)
    rest = [x for x in toks[i + 1 :] if x.kind == "word" or x.text in ",;"]
    return not rest or rest[0].text in ",;"


_WITHOUT_RE = re.compile(r"(?:s[ıiuü]z)(?:l[ıiuü][kğ])?", re.IGNORECASE)


@register
class DoubleNegation(Rule):
    id = "KD-C05"
    name = "Çifte olumsuzluk"
    level = "cümle"
    default_severity = "hata"
    summary = "Aynı cümlede iki olumsuzluk birbirini etkiliyor."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s in body_sentences(doc):
            words = word_tokens(s)
            for i, first in enumerate(words):
                a = first.analysis
                low = turkish_lower(first.base or first.text)
                inner = a is not None and a.is_negative and (
                    a.is_nominalized or a.is_participle or a.is_converb
                )
                without = bool(_WITHOUT_RE.search(low)) and low.endswith(("sız", "siz", "suz", "süz"))
                if not (inner or without):
                    continue
                for second in words[i + 1 : i + 7]:
                    b = second.analysis
                    low2 = turkish_lower(second.base or second.text)
                    outer = low2.startswith(("değil", "yok")) or low2 in ("olmaz", "olamaz") or (
                        b is not None and b.is_negative and b.is_finite
                    )
                    # "ameliyat olmamış, dövme yaptırmamış": aynı biçimde sıralanmış iki olumsuz
                    # eylem birbirini olumluya çevirmez.
                    if outer and inner and len(low) > 4 and low2.endswith(low[-4:]):
                        break
                    if outer:
                        yield self.finding(
                            doc, cfg, first.start, second.end,
                            message=(
                                "Bu cümlede iki olumsuzluk var. Okur anlamı kolayca karıştırır."
                            ),
                            explanation=(
                                f"{quote(first.text)} ve {quote(second.text)} birlikte olumlu bir "
                                "anlam kurar. Bunu çözmek için iki kez düşünmek gerekir."
                            ),
                            suggestion=(
                                "Olumlu söyleyin. Örnek: 'Başvurmamak mümkün değildir.' → "
                                "'Herkes başvurmalı.'"
                            ),
                            sentence=s,
                        )
                        break
                else:
                    continue
                break


def _cp_conf(a: Analysis) -> float:
    flags = [f for f in ("is_converb", "is_participle") if getattr(a, f)]
    return max((a.conf(f) for f in flags), default=0.0)


@register
class ConverbStack(Rule):
    id = "KD-C06"
    name = "Zarf-fiil / sıfat-fiil yığını"
    level = "cümle"
    default_severity = "uyarı"
    summary = "Cümlede çok sayıda zarf-fiil ya da sıfat-fiil var."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        threshold = int(cfg.get("threshold", 2))
        for s in body_sentences(doc):
            words = word_tokens(s)
            quoted = _quoted(s)
            hits = [
                t for i, t in enumerate(words)
                if t.analysis is not None
                and not _is_ne_demek(words, i)
                and not _is_lexical_adverb(words, i)
                and t.start not in quoted
                and (t.analysis.is_converb or t.analysis.is_participle)
                and not t.analysis.is_finite
                and _cp_conf(t.analysis) >= 0.3
            ]
            if len(hits) < threshold:
                continue
            conf = min(_cp_conf(h.analysis) for h in hits if h.analysis is not None)
            yield self.finding(
                doc, cfg, hits[0].start, hits[-1].end,
                message=(
                    f"Bu cümlede {len(hits)} yan cümle var ({join_quoted(h.text for h in hits)}). "
                    "Bunları ayrı cümleler yapın."
                ),
                explanation=(
                    "'-arak', '-ınca', '-madan', '-an', '-dık' gibi eklerle kurulan yan cümleler "
                    "bilgiyi iç içe geçirir. Okur hepsini aynı anda aklında tutmak zorunda kalır."
                ),
                suggestion=(
                    "Her eylemi ayrı cümleye yazın. Örnek: 'Belgeleri alarak gelen kişiler' → "
                    "'Belgelerinizi alın. Sonra gelin.'"
                ),
                sentence=s,
                confidence=conf,
            )


_NOMINAL_PATTERNS = re.compile(
    r"\b\w+m[ae](?:s[ıi]|ler[ıi]|lar[ıi])\s+(?:gerek(?:mektedir|ir|mekte)|"
    r"zorunludur|önem\s+arz\s+etmektedir|beklenmektedir)"
    r"|\b\w+m[ae]s[ıi]n[ae]\s+yönelik"
    r"|\b\w+m[ae]s[ıi]\s+(?:amacıyla|maksadıyla)"
    r"|\b\w+[ıiuü][nl]m[ae]y[ae]\s+başlan\w*",  # "alınmaya başlanacaktır"
    re.IGNORECASE,
)


def _purpose_infinitive(words: list[Token], i: int) -> bool:
    """Yalın mastar + "için": "Bilgi almak için arayın." Amaç bildirmenin en yalın yoludur;
    isimleştirme yığını sayılmaz. "olmasını sağlamak için" içindeki "olmasını" sayılır."""
    a = words[i].analysis
    return (
        a is not None
        and words[i].lower.endswith(("mak", "mek"))
        and i + 1 < len(words)
        and words[i + 1].lower == "için"
        and not any(x in _POSSESSIVES or x in _CASES for x in a.suffixes)
    )


def _is_ne_demek(words: list[Token], i: int) -> bool:
    """'X ne demek?' kalıbındaki "demek" ad-fiil değildir ("… anlamına gelir")."""
    return (
        turkish_lower(words[i].text) == "demek"
        and i > 0
        and turkish_lower(words[i - 1].text) in ("ne", "yani")
    )


_NOMINALIZER_IDS = frozenset({"Inf1", "Inf2", "Inf3", "ActOf", "NotState"})
_POSSESSIVES = frozenset({"P1sg", "P2sg", "P3sg", "P1pl", "P2pl", "P3pl"})
_CASES = frozenset({"Acc", "Dat", "Loc", "Abl", "Gen", "Ins", "Equ"})


def _is_clausal_nominal(a: Analysis) -> bool:
    """Ad-fiil bir yan cümleyi mi taşıyor ("belgelerin teslim edilmesi", "gelmenizi")?

    İyelik ya da hâl eki almayan yalın "-mA/-Iş" biçimleri sözlükleşmiş addır: "Aydınlatma
    Metni", "temizleme işlemi", "ısınma yardımı". Çoğul biçimler de öyledir: "düzenlemeler",
    "gelişmeler", "uygulamalar". Yalın "-mAk" mastarı sayılır ("telefon kullanmak yasaktır").
    """
    if a.source != "zeyrek":
        return True  # sezgisel çözümlemede ek dizisi yok; eski davranış
    ids = a.suffixes
    idx = next((i for i, x in enumerate(ids) if x in _NOMINALIZER_IDS), -1)
    if idx < 0:
        return False  # işaret başka bir okumadan geldi ("unutma" = olumsuz emir)
    if ids[idx] in ("NotState", "Inf1"):
        return True
    after = ids[idx + 1 :]
    if "A3pl" in after:
        return False
    return any(x in _POSSESSIVES or x in _CASES for x in after)


@register
class NominalStack(Rule):
    id = "KD-C07"
    name = "Ad yığını / soyutlama"
    level = "cümle"
    default_severity = "uyarı"
    summary = "Eylemler isme dönüştürülmüş (isimleştirme yığını)."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        threshold = int(cfg.get("threshold", 2))
        for s in body_sentences(doc):
            words = word_tokens(s)
            hits = [
                t for i, t in enumerate(words)
                if t.analysis is not None
                and not _is_ne_demek(words, i)
                and not _is_lexical_adverb(words, i)
                and not _purpose_infinitive(words, i)
                and t.analysis.is_nominalized
                and t.analysis.conf("is_nominalized") >= 0.5
                and _is_clausal_nominal(t.analysis)
            ]
            pattern = _NOMINAL_PATTERNS.search(s.text)
            if len(hits) < threshold and not pattern:
                continue
            if hits:
                start, end = hits[0].start, hits[-1].end
            else:
                assert pattern is not None
                start, end = s.start + pattern.start(), s.start + pattern.end()
            if pattern:
                start = min(start, s.start + pattern.start())
                end = max(end, s.start + pattern.end())
            listed = join_quoted(h.text for h in hits) if hits else quote(pattern.group(0) if pattern else "")
            yield self.finding(
                doc, cfg, start, end,
                message=f"Bu cümlede eylemler isme dönüşmüş ({listed}). Fiili doğrudan kullanın.",
                explanation=(
                    "'-ma', '-mak', '-ış' ekleriyle isme dönüşen eylemler cümleyi soyut "
                    "ve ağır yapar. Kimin ne yapacağı belirsizleşir."
                ),
                suggestion=(
                    "Örnek: 'Belgelerin teslim edilmesi gerekmektedir.' → "
                    "'Belgelerinizi teslim edin.'"
                ),
                sentence=s,
            )


@register
class GenitiveChain(Rule):
    id = "KD-C08"
    name = "Uzun tamlama zinciri"
    level = "cümle"
    default_severity = "uyarı"
    summary = "Art arda gelen ilgi ekleriyle uzun tamlama zinciri kurulmuş."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        chain_len = int(cfg.get("chain", 3))
        for s in body_sentences(doc):
            words = [t for t in s.tokens if t.is_wordlike]
            chain: list[int] = []
            chains: list[list[int]] = []
            for i, t in enumerate(words):
                a = t.analysis if t.kind == "word" else None
                if a is not None and a.is_genitive and a.conf("is_genitive") >= 0.5:
                    if chain and i - chain[-1] > 3:
                        chains.append(chain)
                        chain = []
                    chain.append(i)
            if chain:
                chains.append(chain)
            for ch in chains:
                if len(ch) < chain_len:
                    continue
                first, last = words[ch[0]], words[min(ch[-1] + 1, len(words) - 1)]
                yield self.finding(
                    doc, cfg, first.start, last.end,
                    message=(
                        f"Bu cümlede {len(ch)} tamlama iç içe geçmiş. "
                        "Okur neyin neye ait olduğunu kaybeder."
                    ),
                    explanation=(
                        "'-ın, -in' ekiyle kurulan tamlamalar art arda gelince uzun bir zincir "
                        f"oluşur: {join_quoted(words[i].text for i in ch)}."
                    ),
                    suggestion=(
                        "Zinciri bölün. Örnek: 'Belediyemizin Su İşleri Müdürlüğünün ekibinin "
                        "çalışması' → 'Su İşleri ekibimiz çalışıyor.'"
                    ),
                    sentence=s,
                )


_PAREN_RE = re.compile(r"\(([^()]*)\)")
_PHONE_LIKE = re.compile(r"^[\d\s+./-]+$")


@register
class Parenthesis(Rule):
    id = "KD-C09"
    name = "Parantez içi ek bilgi"
    level = "cümle"
    default_severity = "uyarı"
    summary = "Cümle içinde parantezle ek bilgi verilmiş."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s in body_sentences(doc):
            for m in _PAREN_RE.finditer(s.text):
                inner = m.group(1).strip()
                words = inner.split()
                if not words or not any(c.isalpha() for c in inner):
                    continue
                if _PHONE_LIKE.match(inner):
                    continue
                if len(words) == 1 and (inner.isupper() or doc.lexicon.find_abbreviation(inner)):
                    continue  # "(SGK)" gibi kısaltma açıklaması
                start = s.start + m.start()
                yield self.finding(
                    doc, cfg, start, s.start + m.end(),
                    message="Bu cümlede parantez içinde ek bilgi var. Bu bilgiyi ayrı bir cümleye yazın.",
                    explanation=(
                        "Parantez okumayı böler. Okur parantezden sonra cümlenin başını "
                        "hatırlamakta zorlanır."
                    ),
                    suggestion=f"{quote(inner)} bilgisini yeni bir cümle olarak yazın.",
                    sentence=s,
                )


@register
class LatePredicate(Rule):
    id = "KD-C10"
    name = "Yüklemin çok geç gelmesi"
    level = "cümle"
    default_severity = "bilgi"
    summary = "İlk öğe ile yüklem arasında çok fazla kelime var."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        max_gap = int(cfg.get("max_gap", 6))
        for s in body_sentences(doc):
            if s.is_list_item:
                continue
            words = [t for t in s.tokens if t.is_wordlike]
            embedded = _embedded(s)
            pred_idx = None
            for i in range(len(words) - 1, -1, -1):
                a = words[i].analysis if words[i].kind == "word" else None
                if a is not None and a.is_finite and words[i].start not in embedded:
                    pred_idx = i
                    break
            if pred_idx is None:
                continue
            gap = pred_idx - 1
            if gap <= max_gap:
                continue
            # Yüklemin sonda olması Türkçenin olağan dizilişidir: "Eski zamanlarda küçük bir
            # köyde tatlı bir kız yaşarmış." Okuru zorlayan, yüklemden önce bir yan cümlenin
            # (zarf-fiil, sıfat-fiil, ad-fiil) akılda tutulmasıdır.
            word_list = word_tokens(s)
            lexical = {w.start for i, w in enumerate(word_list) if _is_lexical_adverb(word_list, i)}
            clauses = [
                w for w in words[:pred_idx]
                if w.kind == "word" and w.analysis is not None and w.start not in embedded
                and w.start not in lexical
                and not w.is_proper_name
                and (
                    w.analysis.is_converb or w.analysis.is_participle
                    or (w.analysis.is_nominalized and _is_clausal_nominal(w.analysis))
                )
                and not w.analysis.is_finite
            ]
            if not clauses:
                continue
            pred = words[pred_idx]
            yield self.finding(
                doc, cfg, words[0].start, pred.end,
                message=(
                    f"Yüklem ({quote(pred.text)}) çok geç geliyor. Arada {gap} kelime ve bir yan "
                    f"cümle ({join_quoted(w.text for w in clauses)}) var."
                ),
                explanation=(
                    "Türkçede yüklem sondadır. Önünde bir yan cümle ve çok kelime olunca okur, "
                    "cümlenin ne söylediğini ancak en sonda anlar."
                ),
                suggestion=(
                    f"Yan cümleyi ({quote(clauses[0].text)}) ayrı bir cümle yapın. Böylece her "
                    "cümlenin yüklemi erken gelir."
                ),
                sentence=s,
            )


@register
class IndirectAddress(Rule):
    id = "KD-C11"
    name = "Dolaylı hitap"
    level = "cümle"
    default_severity = "uyarı"
    summary = "Okura doğrudan seslenilmiyor ('rica olunur', 'ilgililere duyurulur')."

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        for s in body_sentences(doc):
            taken: list[tuple[int, int]] = []
            for pat in doc.lexicon.indirect:
                for m in pat.pattern.finditer(s.text):
                    a, b = m.start(), m.end()
                    if any(a < y and x < b for x, y in taken):
                        continue
                    taken.append((a, b))
                    yield self.finding(
                        doc, cfg, s.start + a, s.start + b,
                        message="Bu cümle okura doğrudan seslenmiyor. 'Siz' diye seslenin.",
                        explanation=(
                            f"{quote(m.group(0))} gibi kalıplar resmî ve uzaktır. Okur, sözün "
                            "kendisine söylendiğini anlamayabilir."
                        ),
                        suggestion=pat.suggestion or "Örnek: 'Lütfen belgelerinizi getirin.'",
                        sentence=s,
                    )
