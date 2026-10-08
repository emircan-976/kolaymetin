"""Cümleyi bir dil modeliyle Kolay Dil'e göre yeniden yazmak (isteğe bağlı).

Kural motoru cümle yapısını (uzun cümle, edilgen yapı, ad yığını …) işaretler ama yeniden
yazamaz. Bu modül cümleyi OpenAI uyumlu bir sohbet API'sine (Ollama, LM Studio, Gemini, Groq,
OpenRouter) gönderir, gelen öneriyi denetler ve yazara gösterir. Öneri metne kendiliğinden
yazılmaz.

Varsayılan olarak kapalıdır. Yerel model (Ollama, LM Studio) kullanılırsa metin bilgisayardan
çıkmaz; bulut sağlayıcısı seçilirse cümle o sağlayıcıya gönderilir.

Güvenlik ağı: önerideki sayılar, tarihler, saatler, adresler ve özel adlar özgün cümleyle
karşılaştırılır. Eksik ya da yeni (uydurulmuş) bilgi varsa öneri uygulanamaz olarak işaretlenir.
Öneri yeniden denetlenir; bulgu sayısı ve uyum skoru önce/sonra olarak verilir.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from kolaymetin.api import analyze, build_document
from kolaymetin.lexicon import load_lexicon
from kolaymetin.profiles import load_profile
from kolaymetin.text.normalize import fold_circumflex, turkish_lower
from kolaymetin.text.syllables import MONTHS

TIMEOUT = 90.0
MAX_SENTENCE_CHARS = 2000


@dataclass(frozen=True)
class Provider:
    id: str
    title: str
    url: str
    model: str  # önerilen model; kullanıcı değiştirebilir
    needs_key: bool
    local: bool  # metin bilgisayardan çıkmaz; çevrim içi sunucuda (Vercel) kullanılamaz
    key_url: str = ""


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        Provider("ollama", "Ollama (bu bilgisayarda)", "http://localhost:11434/v1", "gemma3:4b",
                 needs_key=False, local=True),
        Provider("lmstudio", "LM Studio (bu bilgisayarda)", "http://localhost:1234/v1", "",
                 needs_key=False, local=True),
        Provider("gemini", "Google Gemini (ücretsiz anahtar)",
                 "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash",
                 needs_key=True, local=False, key_url="https://aistudio.google.com/apikey"),
        Provider("groq", "Groq (ücretsiz anahtar)", "https://api.groq.com/openai/v1",
                 "llama-3.3-70b-versatile", needs_key=True, local=False,
                 key_url="https://console.groq.com/keys"),
        Provider("openrouter", "OpenRouter (ücretsiz modeller)", "https://openrouter.ai/api/v1", "",
                 needs_key=True, local=False, key_url="https://openrouter.ai/keys"),
    )
}
SERVER_PROVIDER = "sunucu"  # KOLAYMETIN_LLM_URL ile sunucuyu kuran kişinin seçtiği model


class RewriteError(Exception):
    """Kullanıcıya gösterilecek Türkçe hata. status: HTTP durum kodu."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def is_public_server() -> bool:
    """Çevrim içi sürüm (Vercel): yerel sağlayıcılar ve serbest adres kullanılamaz."""
    return bool(os.environ.get("VERCEL"))


def server_config() -> tuple[str, str, str] | None:
    """Sunucuyu kuran kişinin ortam değişkenleriyle verdiği model: (adres, model, anahtar)."""
    url = os.environ.get("KOLAYMETIN_LLM_URL", "").strip()
    if not url:
        return None
    return (url.rstrip("/"), os.environ.get("KOLAYMETIN_LLM_MODEL", "").strip(),
            os.environ.get("KOLAYMETIN_LLM_KEY", "").strip())


def available_providers() -> list[dict[str, Any]]:
    """Arayüzün seçim listesi: bu sunucuda kullanılabilen sağlayıcılar."""
    out = []
    cfg = server_config()
    if cfg is not None:
        out.append({"id": SERVER_PROVIDER, "title": "Sunucunun modeli", "model": cfg[1],
                    "needs_key": False, "local": False, "key_url": ""})
    public = is_public_server()
    for p in PROVIDERS.values():
        if p.local and public:
            continue
        out.append({"id": p.id, "title": p.title, "model": p.model, "needs_key": p.needs_key,
                    "local": p.local, "key_url": p.key_url})
    return out


def resolve(provider: str, model: str = "", key: str = "") -> tuple[str, str, str]:
    """Sağlayıcı kimliğinden (adres, model, anahtar). Adres kullanıcıdan alınmaz: çevrim içi
    sunucu kullanıcının verdiği bir adrese istek atarsa iç ağa erişim açığı (SSRF) doğar."""
    if provider == SERVER_PROVIDER:
        cfg = server_config()
        if cfg is None:
            raise RewriteError("Bu sunucuda dil modeli ayarlı değil.", 400)
        return cfg[0], model or cfg[1], cfg[2]
    p = PROVIDERS.get(provider)
    if p is None:
        raise RewriteError("Bilinmeyen sağlayıcı.", 400)
    if p.local and is_public_server():
        raise RewriteError(f"{p.title} yalnızca kendi bilgisayarınıza kurulan sürümde çalışır.", 400)
    if p.needs_key and not key:
        raise RewriteError(f"{p.title} için bir API anahtarı girin.", 400)
    model = model or p.model
    if not model:
        raise RewriteError("Model adını yazın.", 400)
    return p.url, model, key


SYSTEM_PROMPT = """Sen Türkçe Kolay Dil editörüsün. Kamu duyurularını zihinsel engelli bireyler, yaşlılar ve okumakta zorlanan herkes için yeniden yazarsın.

Sana bir cümle ve o cümlede bulunan sorunlar verilecek. Cümleyi şu kurallara göre yeniden yaz:
- Her cümle tek bir bilgi versin. Bir cümle en fazla 10 kelime olsun. Gerekirse birkaç kısa cümle yaz.
- Etken cümle kur. İşi kimin yaptığı metinde yazıyorsa onu özne yap. Yazmıyorsa yapan uydurma.
- Okura "siz" diye doğrudan seslen: "Başvurunuzu yapın."
- Günlük kelimeler kullan. Resmî, eski ve yabancı kelimeleri kullanma.
- Eylemi fiille söyle; "yapılması gerekmektedir" yerine "yapın" yaz.
- Sayıları, tutarları, tarihleri, saatleri, adresleri, telefon numaralarını, internet adreslerini ve özel adları değiştirmeden koru.
- Yeni bilgi ekleme. Hiçbir bilgiyi çıkarma.

Yalnızca yeniden yazılmış metni ver. Açıklama, başlık, tırnak ya da madde işareti ekleme."""


def build_messages(sentence: str, problems: list[str], before: str = "", after: str = "") -> list[dict[str, str]]:
    lines = [f"Cümle: {sentence}"]
    if problems:
        lines.append("Sorunlar:")
        lines += [f"- {p}" for p in problems]
    if before or after:
        lines.append("")
        lines.append("Bağlam (bu cümleleri değiştirme, yalnızca anlamak için):")
        if before:
            lines.append(f"Önceki cümle: {before}")
        if after:
            lines.append(f"Sonraki cümle: {after}")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n".join(lines)}]


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_LABEL_RE = re.compile(r"^(?:yeniden yazılmış (?:hâli|hali|metin)|kolay dil|öneri|cevap)\s*:\s*", re.I)


def clean_reply(text: str) -> str:
    """Modelin "düşünme" bölümünü, kod çitini, etiketi ve dış tırnakları atar."""
    text = _THINK_RE.sub("", text).strip()
    text = re.sub(r"^```\w*\s*|\s*```$", "", text).strip()
    text = _LABEL_RE.sub("", text).strip()
    if len(text) >= 2 and text[0] in "\"“'" and text[-1] in "\"”'":
        text = text[1:-1].strip()
    return re.sub(r"[ \t]+", " ", text)


def call_chat(url: str, model: str, key: str, messages: list[dict[str, str]]) -> str:
    """OpenAI uyumlu /chat/completions çağrısı (yalnızca standart kütüphane)."""
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.2}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(f"{url}/chat/completions", data=body, headers=headers, method="POST")
    try:
        # Adres sabit sağlayıcı listesinden ya da sunucunun ortam değişkeninden gelir.
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RewriteError("Sağlayıcı anahtarı kabul etmedi. API anahtarını denetleyin.") from exc
        if exc.code == 429:
            raise RewriteError(
                "Sağlayıcının ücretsiz kotası doldu ya da çok sık istek gönderildi. Biraz sonra "
                "yeniden deneyin.", 429
            ) from exc
        if exc.code == 404:
            raise RewriteError(f"Model bulunamadı: '{model}'. Model adını denetleyin.") from exc
        raise RewriteError(f"Sağlayıcı bir hata döndürdü (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if "localhost" in url:
            raise RewriteError(
                "Yerel modele ulaşılamadı. Ollama ya da LM Studio açık mı? Ollama için: "
                "'ollama serve', LM Studio'da: Developer → Start Server."
            ) from exc
        raise RewriteError("Sağlayıcıya ulaşılamadı. İnternet bağlantınızı denetleyin.") from exc
    except ValueError as exc:
        raise RewriteError("Sağlayıcının yanıtı okunamadı.") from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RewriteError("Sağlayıcının yanıtı beklenen biçimde değil.") from exc
    return str(content or "")


# --------------------------------------------------------------------------- bilgi denetimi

_MONTH_RE = "|".join(MONTHS)
_DATE_NUM_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_DATE_WORD_RE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_RE})(?:\s+(\d{{4}}))?", re.I)
_TIME_RE = re.compile(r"\b(\d{1,2})[.:](\d{2})\b")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+|[\w.+-]+@[\w-]+\.[\w.]+", re.I)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


def facts(text: str) -> set[str]:
    """Metindeki değişmemesi gereken bilgiler, karşılaştırılabilir biçimde: tarih (ay-gün),
    yıl, saat, sayı, internet ve e-posta adresi."""
    low = turkish_lower(text)
    out: set[str] = set()
    for m in _URL_RE.finditer(low):
        out.add("adres:" + m.group(0).rstrip(".,;:)"))
    low = _URL_RE.sub(" ", low)

    def date(m: re.Match[str], month: int) -> str:
        out.add(f"tarih:{month:02d}-{int(m.group(1)):02d}")
        return " "

    def numeric(m: re.Match[str]) -> str:
        out.add(f"yıl:{m.group(3)}")
        return date(m, int(m.group(2)))

    def worded(m: re.Match[str]) -> str:
        if m.group(3):
            out.add(f"yıl:{m.group(3)}")
        return date(m, MONTHS.index(turkish_lower(m.group(2))) + 1)

    low = _DATE_NUM_RE.sub(numeric, low)
    low = _DATE_WORD_RE.sub(worded, low)
    for m in _TIME_RE.finditer(low):
        out.add(f"saat:{int(m.group(1)):02d}.{m.group(2)}")
    low = _TIME_RE.sub(" ", low)
    for m in _NUMBER_RE.finditer(low):
        digits = m.group(0)
        if re.fullmatch(r"\d{4}", digits) and 1900 <= int(digits) <= 2100:
            out.add(f"yıl:{digits}")
        else:
            out.add("sayı:" + digits.replace(".", "").replace(",", "."))
    return out


def proper_names(text: str) -> set[str]:
    """Metindeki özel adların gövdeleri ("Ankara'da" → "ankara")."""
    doc = build_document(text, load_profile("kolay-dil"), load_lexicon())
    return {
        fold_circumflex(turkish_lower(t.base))
        for s in doc.sentences for t in s.tokens
        if t.kind == "word" and t.is_proper_name and not t.is_abbreviation and len(t.base) > 1
    }


def _describe(fact: str) -> str:
    kind, _, value = fact.partition(":")
    if kind == "tarih":
        month, day = value.split("-")
        return f"{int(day)} {MONTHS[int(month) - 1].capitalize()} tarihi"
    labels = {"yıl": "yılı", "saat": "saati", "sayı": "sayısı", "adres": "adresi", "ad": "adı"}
    return f"'{value}' {labels.get(kind, '')}".strip()


class Side(BaseModel):
    score: int | None
    findings: int
    errors: int


class RewriteResult(BaseModel):
    text: str
    provider: str
    model: str
    before: Side
    after: Side
    missing: list[str] = Field(default_factory=list)  # öneride olmayan bilgiler
    added: list[str] = Field(default_factory=list)  # öneride olup özgünde olmayan bilgiler
    applicable: bool
    note: str = ""


def _side(text: str, profile: str) -> Side:
    r = analyze(text, profile=profile, max_chars=None)
    return Side(
        score=r.scores.compliance.value,
        findings=len(r.findings),
        errors=sum(1 for f in r.findings if f.severity == "hata"),
    )


def check(original: str, suggestion: str, profile: str = "kolay-dil") -> tuple[list[str], list[str], Side, Side]:
    """Önerinin bilgi denetimi ve önce/sonra skorları."""
    fixed = analyze(original, profile=profile, max_chars=None).fixed_text()
    known = facts(original) | facts(fixed)
    got = facts(suggestion)
    # Özgün cümledeki her bilgi öneride (ya da otomatik düzeltilmiş hâlinde) olmalı.
    missing = sorted(f for f in facts(original) if f not in got and not _covered(f, got))
    added = sorted(f for f in got if f not in known and not _covered(f, known))
    sug_low = fold_circumflex(turkish_lower(suggestion))
    missing += sorted(f"ad:{n}" for n in proper_names(original) if n not in sug_low)
    return missing, added, _side(original, profile), _side(suggestion, profile)


def _covered(fact: str, others: set[str]) -> bool:
    """"sayı:2026" ile "yıl:2026" aynı bilgidir."""
    _, _, value = fact.partition(":")
    return any(o.partition(":")[2] == value for o in others)


def rewrite_sentence(
    sentence: str,
    problems: list[str],
    provider: str,
    model: str = "",
    key: str = "",
    before: str = "",
    after: str = "",
    profile: str = "kolay-dil",
) -> RewriteResult:
    sentence = sentence.strip()
    if not sentence:
        raise RewriteError("Yeniden yazılacak cümle boş.", 400)
    if len(sentence) > MAX_SENTENCE_CHARS:
        raise RewriteError("Cümle çok uzun. Önce cümleyi elle bölün.", 413)
    url, model, key = resolve(provider, model, key)
    reply = clean_reply(call_chat(url, model, key, build_messages(sentence, problems, before, after)))
    if not reply:
        raise RewriteError("Model boş bir yanıt verdi. Yeniden deneyin ya da başka bir model seçin.")
    missing, added, side_before, side_after = check(sentence, reply, profile)
    applicable = not missing and not added
    note = ""
    if missing or added:
        parts = []
        if missing:
            parts.append("Öneride şu bilgiler yok: " + ", ".join(_describe(f) for f in missing) + ".")
        if added:
            parts.append("Öneride özgün cümlede olmayan bilgiler var: "
                         + ", ".join(_describe(f) for f in added) + ".")
        note = " ".join(parts) + " Öneriyi uygulamadan önce bilgileri denetleyin."
    elif side_after.findings > side_before.findings or side_after.errors > side_before.errors:
        note = "Öneride özgün cümleden daha çok bulgu var. Uygulamadan önce okuyun."
    return RewriteResult(
        text=reply, provider=provider, model=model, before=side_before, after=side_after,
        missing=[_describe(f) for f in missing], added=[_describe(f) for f in added],
        applicable=applicable, note=note,
    )
