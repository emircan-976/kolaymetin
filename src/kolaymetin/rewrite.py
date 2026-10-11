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

import atexit
import contextlib
import contextvars
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from kolaymetin.api import analyze, build_document
from kolaymetin.lexicon import load_lexicon
from kolaymetin.models import Finding, Report
from kolaymetin.profiles import load_profile
from kolaymetin.text.normalize import fold_circumflex, turkish_lower
from kolaymetin.text.syllables import MONTHS

TIMEOUT = 90.0
REASONING_EFFORT = "low"  # gpt-oss: low / medium / high
MAX_QUOTA_WAIT = 40  # saniye: bir istek için kota dolunca ya da yoğunlukta beklenecek en uzun toplam süre
BUSY_RETRIES = 2  # 503 (sağlayıcı yoğun): kaç kez yinelenir
BUSY_WAIT = 5  # saniye: 503'ten sonra ilk bekleme; her denemede artar (5, 10)
MAX_SENTENCE_CHARS = 2000

# KOLAYMETIN_YZ_GUNLUK=1: her turun öneri, bulgu ve anlam sorunları sunucu konsoluna yazılır
# (yalnızca yerel deneme için; metnin kendisi de yazılır).
_log = logging.getLogger("kolaymetin.yz")
if os.environ.get("KOLAYMETIN_YZ_GUNLUK"):
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[yz] %(message)s"))
    _log.addHandler(_handler)
    _log.setLevel(logging.INFO)
MAX_CONTEXT_CHARS = 1500  # tüm metni çevirmede önceki bölümün çevirisinden gönderilen son kısım
_DEFAULT_TEMPERATURE_RE = re.compile(r"(?:^|/)gemini-(?:[3-9]|\d{2,})", re.I)


@dataclass(frozen=True)
class Provider:
    id: str
    title: str
    url: str
    model: str  # önerilen model; kullanıcı değiştirebilir
    needs_key: bool
    local: bool  # metin bilgisayardan çıkmaz; çevrim içi sunucuda (Vercel) kullanılamaz
    key_url: str = ""
    cli: str = ""  # API yerine bu bilgisayardaki komut satırı aracı (abonelikle kullanım)


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        Provider("ollama", "Ollama (bu bilgisayarda)", "http://localhost:11434/v1", "gemma3:4b",
                 needs_key=False, local=True),
        Provider("lmstudio", "LM Studio (bu bilgisayarda)", "http://localhost:1234/v1", "",
                 needs_key=False, local=True),
        # Önerilen sağlayıcı: Türkçesi en iyi ücretsiz model (canlı deneme, docs/KARARLAR.md).
        Provider("gemini", "Google Gemini (ücretsiz anahtar, önerilen)",
                 "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.5-flash",
                 needs_key=True, local=False, key_url="https://aistudio.google.com/apikey"),
        Provider("groq", "Groq (ücretsiz anahtar)", "https://api.groq.com/openai/v1",
                 "openai/gpt-oss-120b", needs_key=True, local=False,
                 key_url="https://console.groq.com/keys"),
        Provider("openrouter", "OpenRouter (ücretsiz modeller)", "https://openrouter.ai/api/v1", "",
                 needs_key=True, local=False, key_url="https://openrouter.ai/keys"),
        # Abonelikle kullanım: istek, kullanıcının giriş yaptığı komut satırı aracından geçer ve
        # aboneliğin limitinden düşer. Yalnızca kendi bilgisayarında: sağlayıcılar abonelik
        # girişini başkalarına sunan uygulamalara izin vermiyor (bkz. docs/KARARLAR.md).
        Provider("claude-abonelik", "Claude aboneliği (Claude Code, bu bilgisayarda)", "", "sonnet",
                 needs_key=False, local=True, cli="claude"),
        Provider("gemini-abonelik", "Gemini aboneliği (Antigravity CLI, bu bilgisayarda)", "", "",
                 needs_key=False, local=True, cli="agy"),
    )
}
SERVER_PROVIDER = "sunucu"  # KOLAYMETIN_LLM_URL ile sunucuyu kuran kişinin seçtiği model


class RewriteError(Exception):
    """Kullanıcıya gösterilecek Türkçe hata. status: HTTP durum kodu."""

    def __init__(self, message: str, status: int = 502, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after  # 429: sağlayıcının "şu kadar saniye sonra dene" önerisi


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


# Abonelik aracına komut satırı argümanı olarak giden model adı: "haiku", "gemini-3.8-flash-low",
# "claude-opus-4-6-thinking". "-" ile başlayan ad araca bayrak olarak geçebilir; boşluk ve kabuk
# karakterleri (Windows'ta .cmd sarmalayıcısı cmd.exe'den geçer) reddedilir.
_CLI_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}")


def _cli_model(model: str) -> str:
    if model and not _CLI_MODEL_RE.fullmatch(model):
        raise RewriteError("Geçersiz model adı. Listeden bir model seçin.", 400)
    return model


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
    if p.cli:  # model boşsa aracın kendi varsayılanı kullanılır
        return f"cli:{p.cli}", _cli_model(model or p.model), ""
    if p.needs_key and not key:
        raise RewriteError(f"{p.title} için bir API anahtarı girin.", 400)
    model = model or p.model
    if not model:
        raise RewriteError("Model adını yazın.", 400)
    return p.url, model, key


# Kurallar denetleyicinin kurallarıyla birebir eşleşir (KD-…): model bunlara uyarsa yeniden
# denetimde bulgu çıkmaz. Kalan bulgular onarım turunda modele geri gönderilir.
RULES = """CÜMLE
1. Bir cümle en fazla 10 kelime olsun. Her cümle tek bir bilgi versin ve tek bir çekimli fiili olsun. İki fiili tek cümlede "ve", "ama", "ancak", "çünkü" ya da virgülle bağlama; iki cümle yaz. Cümleyi bölünce aradaki bağı kaybetme: ikinci cümleye bağı söyleyen kelimeyle başla ("Çünkü", "Bu yüzden", "Ama", "Sonra", "Bunun için").
   Kötü: "Boru bozulduğu için suyu keseceğiz." Kötü: "Boru bozuldu. Suyu keseceğiz." İyi: "Boru bozuldu. Bu yüzden suyu keseceğiz."
2. Yan cümle kurma. "-an/-en", "-dığı/-diği", "-acak olan", "-arak/-erek", "-ıp/-ip", "-ınca/-ince", "-ken", "-dıktan sonra", "olup" yapılarını kullanma.
   Kötü: "Mahallede bozulan boruyu onaracağız." İyi: "Mahallede bir boru bozuldu. Boruyu onaracağız."
3. Edilgen fiil kullanma ("yapılacak", "kesilecek", "verilir", "alınmaktadır"). İşi yapanı özne yap: "Belediye suyu kesecek." Metni yazan kurum ("belediyemiz", "idaremiz") kendinden "biz" diye söz eder: "Aşı noktası kurduk." Yapan metinde yazmıyorsa "biz" de. İşi metinde yapmayan birine yükleme. Okura yalnızca işi okurun kendisi yapacaksa emir ver: "Aşı olun." doğru, "Yaşlıları aşılayın." yanlış.
4. Fiilleri isme çevirme. "-ma/-me", "-ması/-mesi", "-ış/-iş" ile yapılan adlar yerine fiil kullan.
   Kötü: "Başvuruların yapılması gerekmektedir." İyi: "Başvurunuzu yapın."
5. Olumlu söyleyebiliyorsan olumlu yaz: "Kapıyı açık bırakmayın." yerine "Kapıyı kapatın." Olumsuzluk bilginin kendisiyse kısa bir olumsuz cümle yaz: "Su gelmeyecek." Çifte olumsuzluk kesinlikle kurma.
6. Okura "siz" diye seslen, emir kipini kullan: "Başvurun.", "Belediyeyi arayın." "rica olunur", "duyurulur", "gerekmektedir", "vatandaşlarımız", "ilgililer" yazma. "Sayın Vatandaşlarımız" gibi hitapları at.
7. Art arda en fazla iki ad tamlaması kur. Kötü: "belediyenin su biriminin telefon numarası".
8. Parantez, noktalı virgül, tırnak işareti ve ara söz kullanma. Bir cümlede en fazla bir iki nokta olsun.
9. Yüklemi cümlenin sonuna, özneye yakın yaz.

KELİME
10. Kısa, günlük kelimeler kullan. Bir kelime en fazla 4 heceli ve en fazla 3 ekli olsun. "vatandaşlarımızın", "iletebilirsiniz", "tamamlanmasının" gibi uzun kelimeler yazma: "siz", "gönderin", "bitince" yaz.
11. Resmî ve eski kelimeleri kullanma: müracaat → başvuru, ivedilikle → hemen, temin etmek → almak, hususunda → konusunda, müteakip → sonra, tarafından → (yapanı özne yap), mağduriyet → zarar, tebliğ etmek → bildirmek.
12. Yabancı kelime kullanma: aktivite → etkinlik, doküman → belge, online → internetten.
13. Kısaltma kullanma. Kurumun tam adını yaz: "SGK" yerine "Sosyal Güvenlik Kurumu". Uzun bir kurum adını bir kez tam yaz; sonra kısa adını kullan: "Sosyal Yardım İşleri Müdürlüğü" → "Müdürlük".
14. Deyim ve mecaz kullanma. Belirsiz ifade kullanma ("bir süre", "yakında", "gerekli işlemler", "ilgili birim"). Kesin bilgi metinde varsa onu yaz. Metinde yoksa kesin bilgi uydurma: "bir süre"yi "birkaç saat" yapma.
15. Aynı şey için hep aynı kelimeyi kullan ("neden" ile "sebep"i karıştırma).

SAYI VE BİÇİM
16. 10 ve üstündeki sayıları rakamla yaz: "yirmi beş" değil "25". Roma rakamı kullanma. Ondalık sayıda virgül kullan: "2,5".
17. Tarihi ayın adıyla yaz ve eki tarihe değil "günü" ya da "tarihi" kelimesine getir: "15 Eylül 2026 günü", "15 Eylül 2026 tarihine kadar". Haftanın gününü yazma; araç doğru günü kendisi ekler.
18. Saatin önüne "saat" yaz: "saat 14.30'da". Saat aralığını tireyle değil sözle yaz: "saat 9.00 ile saat 17.00 arasında".
19. Bütün harfleri büyük yazma ("SU KESİNTİSİ" gibi). Türkçe yazım kurallarına uy: başlığa, cümleye ve özel adlara büyük harfle başla ("Su kesintisi", "Cumhuriyet Mahallesi").

BİLGİ
Anlamı korumak bütün kurallardan önemlidir. Kim ne yapıyor, kim ne yapmalı, ne yasak: bunlar özgün metindekiyle aynı olsun.
20. Sayıları, tutarları, tarihleri, saatleri, adresleri, telefon numaralarını, internet adreslerini ve özel adları değiştirmeden koru. Kurum adlarını özgün metindeki gibi yaz; kısaltma ya da ad uydurma.
21. Yeni bilgi ekleme. Hiçbir bilgiyi çıkarma: özgün metindeki her cümlenin bilgisi Kolay Dil metninde de olsun. Yalnızca bilgi taşımayan kalıpları ("Sayın Vatandaşlarımız", "Kamuoyuna saygıyla duyurulur") atabilirsin.
22. Cümleler arasındaki mantığı koru. Neden, sonuç, koşul, sıra ve karşıtlık özgün metindeki gibi kalsın. Koşulu "-rsa" ile yaz: "Sorunuz olursa belediyeyi arayın." Olayları oluş sırasıyla yaz.
23. "Bu", "o", "bunlar" gibi kelimelerin neyi gösterdiği açık olsun. Açık değilse adını yeniden yaz: "Bu" yerine "Bu kesinti".
24. Yazdıktan sonra Kolay Dil metnini baştan sona oku. Her cümle bir öncekinden anlaşılır biçimde devam etsin. Özgün metni bilmeyen biri de aynı şeyi anlasın."""

SENTENCE_PROMPT = f"""Sen Türkçe Kolay Dil editörüsün. Metinleri zihinsel engelli bireyler, yaşlılar ve okumakta zorlanan herkes için yeniden yazarsın.

Sana bir cümle ve denetleyicinin o cümlede bulduğu sorunlar verilecek. Cümleyi şu kurallara göre yeniden yaz:

{RULES}

Bağlam verilirse cümlen önceki cümleden anlaşılır biçimde devam etsin ve sonraki cümleye bağlansın. Bağlamdaki cümlelerin bilgisini tekrar etme.

Yalnızca yeniden yazılmış metni ver. Her cümleyi ayrı bir satıra yaz. Açıklama, başlık, tırnak ya da madde işareti ekleme."""

TEXT_PROMPT = f"""Sen Türkçe Kolay Dil editörüsün. Metinleri zihinsel engelli bireyler, yaşlılar ve okumakta zorlanan herkes için Kolay Dil'e çevirirsin. Çevirdiğin metin Türkçe Kolay Dil Kütüphanesi'ndeki (kolaydil.tr) metinler gibi olmalı.

Kurallar:

{RULES}

METNİN DÜZENİ
25. İlk satıra konuyu söyleyen kısa bir başlık yaz. Başlığın sonuna nokta koyma.
26. En önemli bilgiyi (ne oluyor, ne zaman, nerede) en başa yaz.
27. Her cümleyi ayrı bir satıra yaz ve sonuna nokta koy.
28. Konuları boş satırla ayrı paragraflara böl. Bir paragrafta en fazla 4 cümle olsun.
29. Konular arasına kısa ara başlıklar koy. Ara başlık soru da olabilir: "Ne yapmalısınız?", "Sorunuz var mı?". Ara başlık kendi satırında dursun.
30. 4 ya da daha çok şey sayıyorsan liste yap: her öğeyi "- " ile ayrı satıra yaz.

Örnek çıktı:
Grip aşısı

Grip aşısı 1 Ekim 2026 günü başlıyor.
Aşıyı aile hekiminiz yapar.
Aşı ücretsiz.

Neden aşı olmalısınız?
Grip kışın çok kişiye bulaşır.
Bu yüzden aşınızı erken olun.

Kimler aşı olmalı?
- 65 yaş ve üstündeki kişiler
- Hamile kadınlar
- Şeker ve kalp hastaları
- Sağlık çalışanları

Ne yapmalısınız?
Önce aile hekiminizi arayın.
Sonra aşı için randevu alın.
Ateşiniz varsa aşıyı sonra olun.

Yalnızca Kolay Dil metnini ver. Açıklama ekleme. Markdown işareti (#, **) kullanma."""


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
    return [{"role": "system", "content": SENTENCE_PROMPT}, {"role": "user", "content": "\n".join(lines)}]


def build_text_messages(
    text: str, problems: list[str], first: bool = True, context: str = ""
) -> list[dict[str, str]]:
    lines = ["Bu metni Kolay Dil'e çevir."]
    if not first:
        lines.append("Bu metin daha uzun bir metnin devamı. Başlık yazma; gerekiyorsa ara başlık yaz.")
    if context:
        # Bölümler ayrı çevrilir; önceki bölümün çevirisi olmadan "bu", "o" gibi gönderimler ve
        # "bu yüzden" gibi bağlar kopar.
        lines += ["Önceki bölümün Kolay Dil çevirisi (yalnızca bağlam için; yeniden yazma, tekrar etme, "
                  "aynı kelimeleri kullanarak devam et):", context, ""]
    if problems:
        lines.append("Denetleyicinin bulduğu sorunlar:")
        lines += [f"- {p}" for p in problems]
    lines += ["", "Metin:", text]
    return [{"role": "system", "content": TEXT_PROMPT}, {"role": "user", "content": "\n".join(lines)}]


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


def _request(url: str, key: str, body: dict[str, Any] | None = None, model: str = "") -> Any:
    """OpenAI uyumlu API isteği (yalnızca standart kütüphane). body yoksa GET.

    User-Agent verilir: Groq'un önündeki Cloudflare Python'un varsayılan kimliğini
    ("Python-urllib") 403 "error code: 1010" ile engelliyor."""
    from kolaymetin import __version__

    headers = {"Content-Type": "application/json", "User-Agent": f"kolaymetin/{__version__}"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body else "GET")
    try:
        # Adres sabit sağlayıcı listesinden ya da sunucunun ortam değişkeninden gelir.
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _error_detail(exc)
        if exc.code == 401 or (exc.code == 400 and "api key" in detail.lower()):
            raise RewriteError("Sağlayıcı anahtarı kabul etmedi. API anahtarını denetleyin.") from exc
        if exc.code == 403:
            raise RewriteError(
                "Sağlayıcı isteği reddetti (HTTP 403). Anahtarın bu modele izni olmayabilir. "
                + (f"Sağlayıcının iletisi: {detail}" if detail else "")
            ) from exc
        if exc.code == 429:
            wait = _retry_after(exc)
            low = detail.lower()
            if "free-models-per-day" in low:  # OpenRouter: hesap başına, bütün :free modeller
                raise RewriteError(
                    "OpenRouter'ın günlük ücretsiz istek sınırı doldu (bütün ücretsiz modeller "
                    "için ortak; hesaba 10 dolar yüklenmemişse günde 50 istek). Yarın yeniden "
                    "deneyin ya da başka bir sağlayıcı seçin.", 429, wait
                ) from exc
            if "per day" in low:  # Groq: "tokens per day (TPD): Limit 200000 …"
                minutes = f"Yaklaşık {max(1, round(wait / 60))} dakika sonra" if wait else "Daha sonra"
                raise RewriteError(
                    f"Bu modelin günlük ücretsiz kotası doldu. {minutes} yeniden deneyin ya da "
                    "başka bir model seçin.", 429, wait
                ) from exc
            if "upstream" in low:  # OpenRouter: ücretsiz modeli sunan sağlayıcı meşgul
                raise RewriteError(
                    "Bu ücretsiz model şu an çok yoğun: modeli sunan sağlayıcı istekleri "
                    "sınırlıyor. Biraz sonra yeniden deneyin ya da listeden başka bir model seçin.",
                    429, wait
                ) from exc
            raise RewriteError(
                "Sağlayıcının ücretsiz kotası doldu ya da çok sık istek gönderildi. Biraz sonra "
                "yeniden deneyin." + (f" Sağlayıcının iletisi: {detail}" if detail else ""), 429, wait
            ) from exc
        if exc.code == 400 and "reasoning" in detail.lower():  # call_chat alansız yineler
            raise RewriteError(f"Sağlayıcı bir hata döndürdü (HTTP 400). {detail}") from exc
        if exc.code == 404 or (exc.code == 400 and "model" in detail.lower()):
            # Gemini kapattığı modeli listede göstermeyi sürdürür; iletisi yerine geçeni söyler.
            raise RewriteError(
                f"Model bulunamadı ya da kapatılmış: '{model}'. Listeden başka bir model seçin."
                + (f" Sağlayıcının iletisi: {detail}" if detail else "")
            ) from exc
        if exc.code == 503:
            raise RewriteError(
                "Sağlayıcı şu an çok yoğun (HTTP 503). Biraz sonra yeniden deneyin ya da listeden "
                "daha hafif bir model seçin (Gemini'de: gemini-3.5-flash-lite).", 503
            ) from exc
        raise RewriteError(
            f"Sağlayıcı bir hata döndürdü (HTTP {exc.code})." + (f" {detail}" if detail else "")
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if "localhost" in url:
            raise RewriteError(
                "Yerel modele ulaşılamadı. Ollama ya da LM Studio açık mı? Ollama için: "
                "'ollama serve', LM Studio'da: Developer → Start Server."
            ) from exc
        raise RewriteError("Sağlayıcıya ulaşılamadı. İnternet bağlantınızı denetleyin.") from exc
    except ValueError as exc:
        raise RewriteError("Sağlayıcının yanıtı okunamadı.") from exc


def _retry_after(exc: urllib.error.HTTPError) -> int | None:
    try:
        return max(1, round(float(exc.headers.get("retry-after", ""))))
    except (TypeError, ValueError):
        return None


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """Sağlayıcının hata iletisi (kısa): {"error": {"message": "..."}}."""
    try:
        raw = exc.read().decode("utf-8", "replace")
    except OSError:
        return ""
    try:
        data = json.loads(raw)
        err = data[0]["error"] if isinstance(data, list) else data.get("error", data)
        msg = err.get("message", "") if isinstance(err, dict) else str(err)
        # OpenRouter asıl nedeni metadata.raw'da verir: "Provider returned error" + "… rate-limited upstream".
        raw_meta = err.get("metadata", {}).get("raw") if isinstance(err, dict) else None
        if isinstance(raw_meta, str) and raw_meta not in msg:
            msg = f"{msg} {raw_meta}"
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        msg = raw
    return " ".join(str(msg).split())[:200]


def call_chat(url: str, model: str, key: str, messages: list[dict[str, str]]) -> str:
    """OpenAI uyumlu /chat/completions çağrısı.

    gpt-oss akıl yürüten bir modeldir; akıl yürütme belirteçleri çıktı olarak ücretlendirilir ve
    ücretsiz katmanın dakikalık kotasından düşer. Yeniden yazmada "low" yeter: istek 3-4 kat
    ucuzlar ve hızlanır. Bu alanı tanımayan bir sağlayıcı reddederse alan olmadan yinelenir.

    Dakikalık kota dolunca (429) sağlayıcının önerdiği süre kadar beklenip yinelenir: Groq'un
    ücretsiz katmanı dakikada 8.000 belirteç verir; ilk yazım ile onarım turu bunu aşabilir.
    Gemini yoğunken 503 döndürür; kısa bir süre bekleyip yinelemek çoğu kez yeter.
    Boş yanıtta (akıl yürütme bütün bütçeyi yediğinde olur) bir kez yinelenir.

    Gemini 3 ve sonrasına sıcaklık gönderilmez: Google bu modellerde varsayılan 1.0'ı öneriyor;
    düşük sıcaklık döngüye ve kalite düşüşüne yol açabiliyor (Gemini 3 geliştirici rehberi)."""
    if url.startswith("cli:"):
        return call_cli(url[4:], model, messages)
    body: dict[str, Any] = {"model": model, "messages": messages}
    if not _DEFAULT_TEMPERATURE_RE.search(model):
        body["temperature"] = 0.2
    if "gpt-oss" in model:
        body["reasoning_effort"] = REASONING_EFFORT
    waited = 0
    empty = 0
    busy = 0
    while True:
        try:
            data = _request(f"{url}/chat/completions", key, body, model)
        except RewriteError as exc:
            if "reasoning" in str(exc) and "reasoning_effort" in body:
                del body["reasoning_effort"]
                continue
            wait = exc.retry_after or 0
            if exc.status == 503 and busy < BUSY_RETRIES:
                busy += 1
                wait = wait or BUSY_WAIT * busy
            if exc.status in (429, 503) and wait > 0 and waited + wait <= MAX_QUOTA_WAIT:
                time.sleep(wait)
                waited += wait
                continue
            raise
        try:
            content = str(data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RewriteError("Sağlayıcının yanıtı beklenen biçimde değil.") from exc
        if content or empty:
            return content
        empty += 1


# --------------------------------------------------------------------------- abonelik (CLI)
#
# Claude Pro/Max ve Google AI Pro aboneliklerinin API anahtarı yok; abonelik limitine yalnızca
# sağlayıcının kendi komut satırı aracıyla ulaşılır. Araçlar kodlama ajanıdır: dosya araçları
# kapatılır (Claude: --tools ""), boş bir geçici klasörde çalışır, proje dosyalarını görmez.
#
# Aracı her istekte açmak pahalı: Antigravity'de modelin yanıtı ~2 sn sürerken ilk tur ~12 sn
# (MCP sunucuları, çalışma alanı); Claude Code'da ~4 sn yerine ~1 sn. Bu yüzden araç akış
# kipinde (stream-json) açık tutulur ve mesajlar aynı süreçten geçer. Bir yeniden yazma işi (bir
# cümle ya da bölüm: ilk yazım, anlam denetimi, onarım) tek konuşmada yürür; iş bitince süreç
# kapatılır, metinler birbirine karışmaz. Sonraki iş, arka planda önceden ısıtılmış yedek bir
# süreçle başlar (_CliPool).

CLI_TIMEOUT = 300  # saniye
CLAUDE_MODELS = ["haiku", "sonnet", "opus"]  # takma adlar: her zaman en son sürüm
# Antigravity'nin sistem istemi bayrağı yok; kurallar istemin başına eklenir.
_AGY_PREFIX = ("Bu bir metin düzenleme görevi. Hiçbir araç kullanma, dosya okuma ya da yazma, "
               "komut çalıştırma. Yalnızca istenen metni yanıt olarak ver.\n\n")
_CLI_HELP = {
    "claude": ("Claude Code bulunamadı. Kurun (https://claude.com/claude-code), terminalde bir kez "
               "'claude' yazıp Claude hesabınızla giriş yapın, sonra bu sunucuyu yeniden başlatın."),
    "agy": ("Antigravity CLI (agy) bulunamadı. Kurun (https://antigravity.google/docs/cli), "
            "terminalde bir kez 'agy' yazıp Google hesabınızla giriş yapın, sonra bu sunucuyu "
            "yeniden başlatın."),
}
_CLI_NAMES = {"claude": "Claude Code", "agy": "Antigravity CLI"}
CLI_SPARES = 2  # sağlayıcı ve model başına ısıtılıp hazır bekleyen süreç
CLI_IDLE = 600  # saniye: bu kadar kullanılmayan yedek süreçler kapatılır
MAX_POOLS = 3  # aynı anda yedek süreç tutulan (araç, model) sayısı; en eski kullanılan kapatılır
_WARMUP = "Yalnızca TAMAM yaz."
_CLAUDE_SYSTEM = ("Sen bir metin düzenleme yardımcısısın. Her mesajdaki talimatlara uy ve yalnızca "
                  "istenen metni ver.")
# Aynı konuşmadaki sonraki adımlar (anlam denetimi, onarım) önceki yanıtı değil, mesajı esas alsın.
_STEP_PREFIX = "Yeni adım. Yalnızca bu mesajdaki talimatlara ve metinlere göre yanıt ver.\n\n"


def _cli_env() -> dict[str, str]:
    """Alt sürecin ortamı. ANTHROPIC_API_KEY varsa Claude Code abonelik yerine API'yi kullanır
    (ücretli); Claude Code oturumundan başlatılan sunucunun CLAUDE_CODE_* değişkenleri de iç
    içe oturum sanılmasın diye atılır."""
    return {k: v for k, v in os.environ.items()
            if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY") and not k.startswith("CLAUDE_CODE_")}


def _last_json(text: str) -> dict[str, Any] | None:
    """Çıktıdaki son JSON nesnesi (öncesinde uyarı satırları olabilir)."""
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict):
                return data
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _cli_error(cli: str, message: str) -> RewriteError:
    name = _CLI_NAMES.get(cli, cli)
    low = message.lower()
    if any(w in low for w in ("login", "log in", "authentication", "not authenticated", "oauth",
                              "invalid api key", "unauthorized")):
        return RewriteError(f"{name} hesabınıza giriş yapmamış. Terminalde bir kez '{cli}' yazıp "
                            "giriş yapın.", 400)
    if any(w in low for w in ("usage limit", "rate limit", "quota", "exhausted", "limit reached",
                              "resource_exhausted")):
        return RewriteError(f"Aboneliğinizin kullanım sınırı doldu ({name}). Sınır açılınca yeniden "
                            "deneyin ya da API ile çalışan bir sağlayıcı seçin.", 429)
    if "model" in low and any(w in low for w in ("unknown", "not found", "invalid", "not available")):
        return RewriteError(f"{name} bu modeli tanımadı. Listeden başka bir model seçin. "
                            f"Aracın iletisi: {message[:200]}")
    return RewriteError(f"{name} bir hata döndürdü: {message[:300]}")


def _job_for(proc: subprocess.Popen[bytes]) -> Any:
    """Windows: süreci bir iş nesnesine (Job Object) koyar; iş kapatılınca süreç ve başlattığı
    bütün alt süreçler kapanır. Olmazsa None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # 9: genişletilmiş sınırlar
    if not ok or not k32.AssignProcessToJobObject(job, int(proc._handle)):  # type: ignore[attr-defined]
        k32.CloseHandle(wintypes.HANDLE(job))
        return None
    return job


def _kill_tree(proc: subprocess.Popen[bytes], job: Any) -> None:
    """Aracı ve başlattığı alt süreçleri (ör. MCP sunucuları) kapatır."""
    if sys.platform == "win32":
        if job:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.TerminateJobObject(wintypes.HANDLE(job), 1)
            k32.CloseHandle(wintypes.HANDLE(job))
        elif proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, check=False)
    else:
        import signal

        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    if proc.poll() is None:
        proc.kill()


def _finished(stdout: str) -> bool:
    """Araç son JSON sonucunu yazdı mı? (Claude: type=result, Antigravity: status)"""
    data = _last_json(stdout)
    if not data:
        return False
    return data.get("type") == "result" or data.get("status") not in (None, "RUNNING", "WAITING")


def _run_cli(args: list[str], stdin: str | None, cwd: str, env: dict[str, str],
             timeout: float = CLI_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Aracı çalıştırır; yanıt yazılınca araç ve alt süreçleri kapatılır.

    Antigravity kullanıcının MCP sunucularını da başlatıyor (ör. bir node süreci). Bu alt süreç
    araç bitince de açık kalıyor ve çıktı borusunu tutuyordu: subprocess.run borunun kapanmasını
    sonsuza dek bekliyor, arayüz "Yeniden yazılıyor…"da kalıyordu. Bu yüzden çıktı boruya değil
    dosyaya yazılır, yanıt gelince bütün süreç ağacı kapatılır."""
    out_path, err_path = os.path.join(cwd, "cikti.txt"), os.path.join(cwd, "hata.txt")

    def read(path: str) -> str:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()

    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        proc = subprocess.Popen(
            args, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL, stdout=out,
            stderr=err, cwd=cwd, env=env, start_new_session=sys.platform != "win32",
        )
        job = _job_for(proc)
        try:
            if stdin is not None and proc.stdin:
                proc.stdin.write(stdin.encode("utf-8"))
                proc.stdin.close()
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                if _finished(read(out_path)):
                    break
                if time.monotonic() > deadline:
                    raise subprocess.TimeoutExpired(args, timeout)
                time.sleep(0.3)
        finally:
            _kill_tree(proc, job)
    return subprocess.CompletedProcess(args, proc.returncode or 0, read(out_path), read(err_path))


def _session_args(cli: str, exe: str, model: str) -> list[str]:
    if cli == "claude":
        # --setting-sources project: boş klasörde proje ayarı yok; kullanıcının kancaları
        # (SessionStart …) her oturumda çalışmasın. Giriş bilgisi ayarlardan gelmez.
        args = [exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                "--verbose", "--system-prompt", _CLAUDE_SYSTEM, "--tools", "", "--strict-mcp-config",
                "--setting-sources", "project", "--no-session-persistence", "--disable-slash-commands"]
    else:
        # "--print=": değersiz -p sonraki bayrağı istem sanıyor.
        args = [exe, "--print=", "--input-format", "stream-json", "--output-format", "stream-json",
                "--disable-slash-commands"]
    return args + (["--model", model] if model else [])


def _message_line(cli: str, text: str) -> bytes:
    msg = ({"type": "user", "message": {"role": "user", "content": text}} if cli == "claude"
           else {"event": "user", "message": {"content": text}})
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")


def _parse_result(cli: str, event: dict[str, Any]) -> str | None:
    """Sonuç olayıysa yanıt metni, hata sonucuysa RewriteError; başka olaysa None."""
    if cli == "claude":
        if event.get("type") != "result":
            return None
        if event.get("is_error") or event.get("subtype", "success") != "success":
            raise _cli_error(cli, str(event.get("result") or event.get("subtype")))
        return str(event.get("result") or "").strip()
    if event.get("event") != "result":
        return None
    res = event.get("result") or {}
    if res.get("status") != "SUCCESS":
        raise _cli_error(cli, str(res.get("error") or res.get("status")))
    return str(res.get("response") or "").strip()


class _CliSession:
    """Akış kipinde açık tutulan araç süreci: bir konuşma."""

    def __init__(self, cli: str, args: list[str], env: dict[str, str]) -> None:
        self.cli = cli
        self.cwd = tempfile.mkdtemp(prefix="kolaymetin-")
        self.proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.cwd,
            env=env, start_new_session=sys.platform != "win32",
        )
        self.job = _job_for(self.proc)  # kapatılınca MCP gibi alt süreçler de kapanır
        self.events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.stderr: deque[str] = deque(maxlen=20)
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.error: RewriteError | None = None
        self.created = time.monotonic()
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read_out(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if isinstance(data, dict):
                self.events.put(data)
        self.events.put(None)  # süreç kapandı

    def _read_err(self) -> None:
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            line = raw.decode("utf-8", "replace").strip()
            if line:
                self.stderr.append(line)

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None and self.error is None

    def _died(self) -> RewriteError:
        return _cli_error(self.cli, " ".join(self.stderr) or "araç beklenmedik biçimde kapandı")

    def ask(self, text: str, timeout: float = CLI_TIMEOUT) -> str:
        with self.lock:
            if self.proc.poll() is not None:
                raise self._died()
            assert self.proc.stdin is not None
            try:
                self.proc.stdin.write(_message_line(self.cli, text))
                self.proc.stdin.flush()
            except OSError as exc:
                raise self._died() from exc
            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    self.close()
                    raise RewriteError(f"{_CLI_NAMES.get(self.cli, self.cli)} {round(timeout)} saniyede "
                                       "yanıt vermedi.", 504)
                try:
                    event = self.events.get(timeout=left)
                except queue.Empty:
                    continue
                if event is None:
                    raise self._died()
                reply = _parse_result(self.cli, event)
                if reply is not None:
                    return reply

    def warm(self) -> None:
        """İlk tur pahalı (Antigravity ~12 sn): kısa bir mesajla önceden ödenir."""
        try:
            self.ask(_WARMUP)
        except RewriteError as exc:
            self.error = exc
        finally:
            self.ready.set()

    def close(self) -> None:
        _kill_tree(self.proc, self.job)
        shutil.rmtree(self.cwd, ignore_errors=True)


class _CliPool:
    """Bir sağlayıcı ve model için ısıtılmış yedek süreçler."""

    def __init__(self, cli: str, args: list[str]) -> None:
        self.cli, self.args = cli, args
        self.spares: list[_CliSession] = []
        self.lock = threading.Lock()
        self.used = time.monotonic()
        self.closed = False  # havuz listeden çıkarıldı: arka plandaki fill yeni süreç açmasın

    def _spawn(self) -> _CliSession:
        session = _CliSession(self.cli, self.args, _cli_env())
        threading.Thread(target=session.warm, daemon=True).start()
        return session

    def _prune(self) -> None:
        for dead in [x for x in self.spares if not x.alive]:
            dead.close()
        self.spares = [x for x in self.spares if x.alive]

    def fill(self) -> None:
        with self.lock:
            self._prune()
            while not self.closed and len(self.spares) < CLI_SPARES:
                self.spares.append(self._spawn())

    def acquire(self) -> _CliSession:
        """Hazır yedek; yoksa en önce ısınmaya başlayan; o da yoksa yeni süreç."""
        with self.lock:
            self.used = time.monotonic()
            self._prune()
            self.spares.sort(key=lambda x: (not x.ready.is_set(), x.created))
            session = self.spares.pop(0) if self.spares else self._spawn()
        threading.Thread(target=self.fill, daemon=True).start()
        session.ready.wait(CLI_TIMEOUT)
        if session.error is not None:
            session.close()
            raise session.error
        return session

    def close(self, idle_only: bool = False) -> None:
        with self.lock:
            if idle_only and time.monotonic() - self.used < CLI_IDLE:
                return
            self.closed = self.closed or not idle_only
            for spare in self.spares:
                spare.close()
            self.spares = []


_POOLS: dict[tuple[str, str], _CliPool] = {}
_POOLS_LOCK = threading.Lock()
_REAPER: list[threading.Thread] = []


def _reap() -> None:
    while True:
        time.sleep(30)
        with _POOLS_LOCK:
            pools = list(_POOLS.values())
        for pool in pools:
            pool.close(idle_only=True)


def close_pools() -> None:
    with _POOLS_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        pool.close()


atexit.register(close_pools)


def _pool(cli: str, model: str) -> _CliPool:
    exe = shutil.which(cli)
    if not exe:
        raise RewriteError(_CLI_HELP.get(cli, f"'{cli}' bulunamadı."), 400)
    with _POOLS_LOCK:
        if (cli, model) not in _POOLS:
            # Her model kendi yedek süreçlerini açar: model değiştirildikçe süreç birikmesin.
            while len(_POOLS) >= MAX_POOLS:
                old = min(_POOLS, key=lambda k: _POOLS[k].used)
                _POOLS.pop(old).close()
            _POOLS[(cli, model)] = _CliPool(cli, _session_args(cli, exe, model))
        if not _REAPER:
            _REAPER.append(threading.Thread(target=_reap, daemon=True))
            _REAPER[0].start()
        return _POOLS[(cli, model)]


def warm_cli(provider: str, model: str = "") -> None:
    """Abonelik sağlayıcısı seçilince yedek süreçleri ısıtmaya başlar (arka planda)."""
    p = PROVIDERS.get(provider)
    if p and p.cli and not is_public_server():
        with contextlib.suppress(RewriteError):
            threading.Thread(target=_pool(p.cli, _cli_model(model or p.model)).fill, daemon=True).start()


# Bir yeniden yazma işinin oturumları: işteki bütün istekler aynı konuşmadan geçer.
_JOB: contextvars.ContextVar[dict[tuple[str, str], _CliSession] | None] = contextvars.ContextVar(
    "kolaymetin_cli_job", default=None)


@contextlib.contextmanager
def _cli_job() -> Iterator[None]:
    token = _JOB.set({})
    try:
        yield
    finally:
        sessions = _JOB.get() or {}
        _JOB.reset(token)
        for session in sessions.values():
            session.close()


def call_cli(cli: str, model: str, messages: list[dict[str, str]]) -> str:
    """İsteği abonelik aracının açık oturumundan geçirir, yanıt metnini döndürür."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    user = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
    text = (_AGY_PREFIX if cli == "agy" else "") + _STEP_PREFIX + system + "\n\n" + user
    job = _JOB.get()
    key = (cli, model)
    session = job.get(key) if job is not None else None
    if session is None or not session.alive:
        session = _pool(cli, model).acquire()
        if job is not None:
            job[key] = session
    try:
        return session.ask(text)
    except RewriteError:
        if job is not None:  # bozuk oturum: işin sonraki isteği yeni süreçle başlasın
            job.pop(key, None)
        session.close()
        raise
    finally:
        if job is None:
            session.close()


def _cli_models(cli: str) -> list[str]:
    if cli == "claude":
        return list(CLAUDE_MODELS)
    exe = shutil.which(cli)
    if not exe:
        raise RewriteError(_CLI_HELP.get(cli, f"'{cli}' bulunamadı."), 400)
    try:
        with tempfile.TemporaryDirectory(prefix="kolaymetin-", ignore_cleanup_errors=True) as cwd:
            proc = _run_cli([exe, "models"], None, cwd, _cli_env(), timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return []
    # Her satırın ilk sözcüğü model adıdır ("gemini-3.8-flash-medium  …"); başlık satırları elenir.
    ids = []
    for line in proc.stdout.splitlines():
        m = re.match(r"\s*(?:[-*]\s*)?([a-z][a-z0-9.\-]*\d[a-z0-9.\-]*)\b", line)
        if m:
            ids.append(m.group(1))
    return sorted(set(ids))


# Sohbet modeli olmayanlar: ses, görüntü, gömme, denetim modelleri.
_NOT_CHAT = re.compile(
    r"whisper|tts|guard|embed|image|imagen|veo|audio|transcri|moderation|orpheus|playai|"
    r"compound|aqa|learnlm|gemma-3n|robotics|computer-use|live|native-audio|-exp-|search", re.I
)
# Sağlayıcıya göre önerilen model sırası (listede ilk eşleşen seçilir).
_PREFERRED: dict[str, tuple[str, ...]] = {
    "groq": (r"gpt-oss-120b", r"qwen", r"llama-4", r"llama", r"gpt-oss"),
    "gemini": (r"^gemini-[\d.]+-flash$", r"^gemini-.*flash$", r"^gemini-[\d.]+-pro$", r"^gemini"),
    # Antigravity: en yeni flash, düşük düşünme düzeyi. Her istek araç açılışıyla 15-25 sn sürüyor;
    # "medium" bir cümlede 2 dakikayı buluyordu. Pro haftalık kotayı çabuk bitirir.
    "gemini-abonelik": (r"^gemini-[\d.]+-flash-low$", r"^gemini-[\d.]+-flash", r"^gemini"),
    "openrouter": (r"gemma.*:free", r"llama.*:free", r"qwen.*:free", r":free"),
}


def list_models(provider: str, key: str = "", model: str = "") -> dict[str, Any]:
    """Sağlayıcının sohbet modelleri ve önerilen model. Anahtarı da doğrular. Abonelik araçlarında
    seçili model (yoksa önerilen) için yedek süreçler ısıtılmaya başlar."""
    p = PROVIDERS.get(provider)
    # Model listelemede gerekmez; "-" yalnızca "Model adını yazın" denetimini geçmek için.
    url, _model, key = resolve(provider, "" if p and p.cli else "-", key)
    if p and p.cli:
        ids = _cli_models(p.cli)
        suggested = p.model if p.model in ids else next(
            (m for pat in _PREFERRED.get(provider, ()) for m in sorted(ids, reverse=True) if re.search(pat, m)), "")
        warm_cli(provider, model if model in ids else suggested)
        return {"models": ids, "suggested": suggested}
    data = _request(f"{url}/models", key)
    items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
    ids = []
    for item in items or []:
        mid = str(item.get("id") or item.get("name") or "") if isinstance(item, dict) else str(item)
        mid = mid.removeprefix("models/")
        if mid and not _NOT_CHAT.search(mid):
            ids.append(mid)
    if provider == "openrouter":
        ids = [m for m in ids if m.endswith(":free")]
    ids = sorted(set(ids))
    p = PROVIDERS.get(provider)
    suggested = p.model if p and p.model in ids else ""
    for pattern in _PREFERRED.get(provider, ()):
        if suggested:
            break
        suggested = next((m for m in sorted(ids, reverse=True) if re.search(pattern, m)), "")
    if not suggested and ids:
        suggested = ids[0]
    return {"models": ids, "suggested": suggested}


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
    """Metindeki özel adların gövdeleri ("Ankara'da" → "ankara"). Hitaptaki büyük harfli
    kelimeler ("Sayın Vatandaşlarımız") ad değildir; Kolay Dil çevirisi hitabı atar. Hitaptaki
    gerçek ad ("Sayın Ahmet Yılmaz") sıradan bir kelime olmadığı için denetlenir."""
    lexicon = load_lexicon()
    doc = build_document(text, load_profile("kolay-dil"), lexicon)
    out = set()
    for s in doc.sentences:
        salutation = False
        for t in s.tokens:
            if t.kind != "word":
                salutation = False
                continue
            low = fold_circumflex(turkish_lower(t.base))
            if low in ("sayın", "değerli", "sevgili"):
                salutation = True
                continue
            if salutation and lexicon.is_common(t):
                continue
            if t.is_proper_name and not t.is_abbreviation and len(low) > 1:
                out.add(_lemma(t) or low)
            salutation = salutation and t.is_proper_name
    return out


def _lemma(t: Any) -> str:
    """Kesme işaretsiz ekli adın gövdesi: "Müdürlüğünden" → "müdürlük"."""
    return fold_circumflex(turkish_lower(t.analysis.lemma)) if t.analysis and t.analysis.lemma else ""


def _word_forms(text: str) -> set[str]:
    """Metindeki kelimelerin küçük harfli biçimleri ve gövdeleri."""
    doc = build_document(text, load_profile("kolay-dil"), load_lexicon())
    out = set()
    for s in doc.sentences:
        for t in s.tokens:
            if t.kind == "word":
                out.add(fold_circumflex(turkish_lower(t.base)))
                out.add(_lemma(t))
    return out


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
    calls: int = 1  # modele kaç istek gitti (ilk yazım + onarım turları)
    remaining: list[str] = Field(default_factory=list)  # öneride kalan bulgular
    meaning: list[str] = Field(default_factory=list)  # anlam denetiminin öneride bulduğu sorunlar


def _side(report: Report) -> Side:
    return Side(
        score=report.scores.compliance.value,
        findings=len(report.findings),
        errors=sum(1 for f in report.findings if f.severity == "hata"),
    )


def check(original: str, suggestion: str, profile: str = "kolay-dil") -> tuple[list[str], list[str], Side, Side]:
    """Önerinin bilgi denetimi ve önce/sonra skorları."""
    missing, added = fact_diff(original, suggestion, profile)
    return (missing, added, _side(analyze(original, profile=profile, max_chars=None)),
            _side(analyze(suggestion, profile=profile, max_chars=None)))


def fact_diff(original: str, suggestion: str, profile: str = "kolay-dil") -> tuple[list[str], list[str]]:
    """Öneride olmayan ve özgünde olmayan bilgiler."""
    fixed = analyze(original, profile=profile, max_chars=None).fixed_text()
    known = facts(original) | facts(fixed)
    got = facts(suggestion)
    # Özgün cümledeki her bilgi öneride (ya da otomatik düzeltilmiş hâlinde) olmalı.
    missing = sorted(f for f in facts(original) if f not in got and not _covered(f, got))
    added = sorted(f for f in got if f not in known and not _covered(f, known))
    # Ad öneride başka bir ekle geçebilir ("Müdürlüğünden" → "Müdürlük"): gövdeler de karşılaştırılır.
    sug_low = fold_circumflex(turkish_lower(suggestion))
    names = [n for n in proper_names(original) if n not in sug_low]
    if names:
        forms = _word_forms(suggestion)
        missing += sorted(f"ad:{n}" for n in names if n not in forms)
    return missing, added


def _covered(fact: str, others: set[str]) -> bool:
    """"sayı:2026" ile "yıl:2026" aynı bilgidir."""
    _, _, value = fact.partition(":")
    return any(o.partition(":")[2] == value for o in others)


# --------------------------------------------------------------------------- denetle ve onar
#
# Model kurallara her zaman uymaz. Önerisine önce aracın kesin düzeltmeleri uygulanır (tarihe
# haftanın günü, saate "saat" …), sonra öneri yeniden denetlenir. Kalan bulgular satır satır
# modele geri gönderilir; model yalnızca sorunlu satırları yeniden yazar (az belirteç). En çok
# REPAIR_ROUNDS tur; bulgusu en az olan, bilgisi eksiksiz öneri seçilir.
#
# Kural bulgusu anlamı ölçmez: küçük model (ör. gemini-3.5-flash-lite) bulguyu azaltmak için
# cümleyi bağlamından koparıp anlamı bozabiliyor ve skor yine yükseliyor. Bu yüzden her öneri
# ayrı bir istekle anlam bakımından da denetlenir (MEANING_PROMPT): eksik ya da yanlış bilgi,
# kopan neden-sonuç bağı, anlaşılmayan gönderim. Anlam sorunları onarıma önce gider ve öneriler
# arasında seçimde kural bulgularından önce gelir.

REPAIR_ROUNDS = 3  # temiz öneride döngü erken biter; çoğu metin 1 turda biter
MEANING_CHECK = True  # her öneri ayrıca anlam bakımından denetlenir (öneri başına bir istek daha)
# Anlam sorunu sayısı eşitken onarılmış öneri, kural cezası en çok bu kadar (bir "hata") artsa
# da seçilir: bkz. _better.
MEANING_TOLERANCE = 3.0
MAX_MEANING_ISSUES = 12
MAX_TEXT_CHARS = 4000  # tüm metni çevirme: bir istek (Groq ücretsiz katmanı dakikada 8.000 belirteç)
_MODEL_FIXES = ("hata", "uyarı")  # "bilgi" bulguları onarıma gönderilmez
# KD-M01: paragraf bölmeyi araç kendisi yapar (_split_paragraphs). KD-C04: olumsuz cümleyi
# zorla olumluya çevirmek anlamı bozuyor ("Gecikme olursa? Su akmaya devam edecek.");
# kolaydil.tr metinleri de gerektiğinde olumsuz cümle kurar ("Suyunuz 1 gün gelmeyecek").
_NOT_FOR_MODEL = {"KD-M01", "KD-C04"}
_PARAGRAPH_SENTENCES = 4

# Onarım isteği kısa tutulur: bütün kurallar yerine özet gider, her bulgunun kendi önerisi zaten
# istekte. Böylece ilk yazım ile onarım dakikalık belirteç kotasına sığar.
REPAIR_PROMPT = """Sen Türkçe Kolay Dil editörüsün. Kolay Dil'e çevrilmiş bir metni denetliyorsun.

Kolay Dil kuralları özetle: en fazla 10 kelimelik cümle, her cümlede tek bilgi ve tek fiil; yan cümle yok ("-an", "-dığı", "-arak", "-ıp", "olup"); edilgen yok, işi yapan özne olsun; fiili isme çevirme ("-ması gerekir" yerine "yapın"); olumlu anlatım; okura "siz" diye emirle seslen; en fazla 4 heceli, en fazla 3 ekli günlük kelimeler; resmî, eski, yabancı kelime, kısaltma, deyim yok; tarih "15 Eylül 2026 günü", saat "saat 9.00"; büyük harfle bütün kelimeyi yazma.

Sana özgün metin, onun numaralı satırlarla yazılmış Kolay Dil hâli ve bazı satırlarda bulunan sorunlar verilecek. Yalnızca sorunlu satırları yeniden yaz. Bir satırı birden çok cümleye bölebilirsin; her cümleyi ayrı satıra yaz. Eksik bilgi varsa özgün metinden alıp uygun satıra ekle.
Anlamı korumak kurallardan önemlidir: kim ne yapıyor, kim ne yapmalı, özgün metindekiyle aynı kalsın. "Anlam:" ile başlayan sorunları önce ve mutlaka gider; sorunda "Doğrusu:" yazıyorsa satırı ona göre yaz ve özgün metindeki kelimeyi kullan. Okura yalnızca işi okurun kendisi yapacaksa emir ver. Bir sorunu gidermek için bilgi uydurman ya da anlamı değiştirmen gerekiyorsa o satırı olduğu gibi bırak.
Yeni satır önceki ve sonraki satırla bağlantılı olsun. Cümleyi bölünce bağı kaybetme: "Çünkü", "Bu yüzden", "Ama", "Sonra" ile başla. "Bu", "o" neyi gösteriyorsa açık olsun.

Cevabı yalnızca şu biçimde ver, başka hiçbir şey yazma:
[3]
yeniden yazılmış satır
[7]
yeniden yazılmış satır
ikinci cümle"""

MEANING_PROMPT = """Sen Türkçe bir metin denetçisisin. Sana özgün bir metin ve onun numaralı satırlarla yazılmış Kolay Dil çevirisi verilecek. Çeviriyi özgün metinle karşılaştır.

Kolay Dil çok kısa cümleler, günlük kelimeler ve "siz" dili kullanır; hitaplar ve kalıp sözler atılır. Bunlar hata değildir. Kelime seçimine, üsluba ve cümle uzunluğuna bakma. Yalnızca anlam hatalarını bul:
- Eksik bilgi: özgün metindeki bir bilgi, koşul, istisna ya da uyarı çeviride yok.
- Yanlış bilgi: kim ne yapıyor, kim ne yapmalı, ne zaman, nerede, ne yasak değişmiş.
- Kopuk bağ: neden, sonuç, koşul, sıra ya da karşıtlık kaybolmuş ya da ters dönmüş.
- Anlaşılmayan cümle: önceki satırlar okunsa bile ne demek istediği anlaşılmıyor ya da önceki satırla çelişiyor.
- Belirsiz gönderim: "bu", "o", "bunlar" neyi gösteriyor anlaşılmıyor.
- Uydurma: özgün metinde olmayan bir bilgi eklenmiş.
Özgün metne aracın kesin düzeltmeleri uygulanmıştır (ör. tarihe haftanın günü eklenir, resmî kelime sadeleşir); çeviride bunları görmek doğrudur, uydurma sayma.
Emin olmadığın şeyi yazma. Her sorunu bir kez yaz.

Cevabı yalnızca şu biçimde ver, başka bir şey yazma:
[4] sorunun kısa açıklaması. Doğrusu: özgün metne göre ne olmalı.
Bir satıra bağlı olmayan eksik bilgi için numara olarak [0] yaz. Sorun yoksa yalnızca TAMAM yaz."""

_ITEM_RE = re.compile(r"^\[(\d+)\]\s*(.*)$")
_ISSUE_RE = re.compile(r"^[-*•\s]*\[(\d+)\]\s*[:.-]?\s*(.+)$")
_MONTH_LOWER_RE = re.compile(rf"\b(\d{{1,2}}\s+)({_MONTH_RE})\b")  # "1 ekim" → "1 Ekim"


@dataclass
class _Candidate:
    text: str
    report: Report
    missing: list[str]
    added: list[str]
    penalty: float
    meaning: list[tuple[int, str]] = field(default_factory=list)  # (satır numarası, anlam sorunu)

    @property
    def facts_ok(self) -> bool:
        return not self.missing and not self.added



def _better(cand: _Candidate, best: _Candidate) -> bool:
    """Onarılmış öneri öncekinin yerini alır mı? Sıra: bilgi, anlam, kural bulguları.

    Anlam sorunu sayısı eşitse onarım seçilir (kural cezası en çok MEANING_TOLERANCE artabilir):
    onarım önceki sorunları gidermek için yazıldı; denetçinin yeni öneride bulduğu sorun çoğu
    kez başka ve daha küçük bir sorundur, sonraki tur onu onarır. Eşitlikte eski öneri kalınca
    düzeltilmiş sorun ("kum" → "bulanıklık") her turda çöpe gidiyor, kullanıcıya uyarı kalıyordu."""
    if cand.facts_ok != best.facts_ok:
        return cand.facts_ok
    if len(cand.meaning) != len(best.meaning):
        return len(cand.meaning) < len(best.meaning)
    if best.meaning:
        return cand.penalty <= best.penalty + MEANING_TOLERANCE
    return cand.penalty < best.penalty


def _clean_text(text: str) -> str:
    """Tüm metin yanıtı: Markdown işaretlerini atar ("## Başlık" → "Başlık", "* öğe" → "- öğe")."""
    text = clean_reply(text)
    text = re.sub(r"^[ \t]*[*•][ \t]+", "- ", text, flags=re.M)
    text = re.sub(r"^[ \t]*#{1,6}[ \t]+", "", text, flags=re.M)
    text = text.replace("**", "").replace("__", "").replace("‐", "-").replace("‑", "-")
    text = re.sub(r"[ \t]+$", "", text, flags=re.M)
    text = _MONTH_LOWER_RE.sub(lambda m: m.group(1) + m.group(2)[0].upper() + m.group(2)[1:], text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _autofix(text: str, profile: str) -> str:
    """Aracın kesin düzeltmeleri; çakışan düzeltmeler sonraki turda uygulanır."""
    for _ in range(3):
        fixed = analyze(text, profile=profile, max_chars=None).fixed_text()
        if fixed == text:
            break
        text = fixed
    return text


def _split_paragraphs(text: str) -> str:
    """Her cümlesi ayrı satırda olan metinde uzun paragrafı (KD-M01) boş satırla böler.
    Başlık ve liste öğesi cümle sayılmaz; başlık yeni paragraf başlatır."""
    out: list[str] = []
    count = 0
    for line in text.split("\n"):
        s = line.strip()
        if not s or s.endswith(("?", ":")) or not s.endswith((".", "!")):
            count = 0 if not s.startswith("-") else count
        else:
            if count >= _PARAGRAPH_SENTENCES:
                out.append("")
                count = 0
            count += 1
        out.append(line)
    return "\n".join(out)


def _punctuate(text: str) -> str:
    """Noktasız cümle satırına nokta koyar. Denetleyici noktasız kısa satırı başlık sayar ve
    cümle kurallarına bakmaz: model noktayı unutunca skor haksız yere yükselir. Başlık yalnızca
    paragrafın ilk satırında ve en çok 6 kelimeyle durabilir."""
    out: list[str] = []
    first = True
    for line in text.split("\n"):
        s = line.rstrip()
        if not s.strip():
            first = True
        else:
            heading = first and len(s.split()) <= 6
            if not heading and not s.lstrip().startswith("-") and s[-1] not in ".!?:…":
                s += "."
            first = False
        out.append(s)
    return "\n".join(out)


def _penalty(report: Report, profile: str) -> float:
    weights = load_profile(profile).weights
    return sum(weights.get(f.severity, 1.0) for f in report.findings)


def _evaluate(original: str, text: str, profile: str) -> _Candidate:
    text = _autofix(text, profile)
    report = analyze(text, profile=profile, max_chars=None)
    missing, added = fact_diff(original, text, profile)
    return _Candidate(text, report, missing, added, _penalty(report, profile))


def _open_findings(report: Report) -> list[Finding]:
    return [f for f in report.findings
            if f.severity in _MODEL_FIXES and f.fix is None and f.rule_id not in _NOT_FOR_MODEL]


def _problem(f: Finding) -> str:
    out = f"'{f.text}': {f.message}" if f.text and len(f.text) <= 60 else f.message
    if f.suggestion and f.suggestion not in out:
        out += f" Öneri: {f.suggestion}"
    return out


def _numbered(text: str) -> tuple[list[str], list[tuple[int, int, int]]]:
    """Satırlar ve dolu satırların (numara, başlangıç, bitiş) ofsetleri."""
    lines = text.split("\n")
    spans = []
    pos = 0
    for i, line in enumerate(lines):
        if line.strip():
            spans.append((i, pos, pos + len(line)))
        pos += len(line) + 1
    return lines, spans


def build_repair_messages(original: str, cand: _Candidate) -> list[dict[str, str]]:
    """Onarım isteği: özgün metin (eksik bilgi için), numaralı Kolay Dil metni, satır satır
    sorunlar."""
    lines, spans = _numbered(cand.text)
    numbers = {i: n for n, (i, _, _) in enumerate(spans, 1)}
    by_line: dict[int, list[str]] = {}
    general = []  # satıra bağlı olmayan anlam sorunları
    for n, issue in cand.meaning:  # anlam sorunları önce: model onları önce gidersin
        if 1 <= n <= len(spans):
            by_line.setdefault(spans[n - 1][0], []).append(f"Anlam: {issue}")
        else:
            general.append(issue)
    for f in _open_findings(cand.report):
        for i, a, b in spans:
            if a <= f.start < b + 1:
                by_line.setdefault(i, []).append(_problem(f))
                break
    added = set(cand.added)
    for i, _, _ in spans:
        for fact in sorted(facts(lines[i]) & added):
            by_line.setdefault(i, []).append(
                f"{_describe(fact)} özgün metinde yok, uydurulmuş. Bu bilgiyi satırdan çıkar.")
    body = ["Özgün metin:", original, "", "Kolay Dil metni:"] + [f"[{numbers[i]}] {lines[i].strip()}" for i, _, _ in spans]
    if by_line:
        body += ["", "Sorunlu satırlar:"]
        for i in sorted(by_line):
            body.append(f"[{numbers[i]}] {lines[i].strip()}")
            body += [f"- {p}" for p in dict.fromkeys(by_line[i])]
    if general:
        body += ["", "Çeviride anlam sorunları var; ilgili satırı yeniden yazarak gider:"]
        body += [f"- Anlam: {g}" for g in general]
    if cand.missing:
        body += ["", "Çeviride şu bilgiler eksik; uygun satıra ekle: "
                 + ", ".join(_describe(f) for f in cand.missing) + "."]
    if cand.added:
        body += ["", "Çeviride özgün metinde olmayan bilgiler var; bu bilgileri çıkar: "
                 + ", ".join(_describe(f) for f in cand.added) + "."]
    return [{"role": "system", "content": REPAIR_PROMPT}, {"role": "user", "content": "\n".join(body)}]


def build_meaning_messages(original: str, text: str, profile: str = "kolay-dil") -> list[dict[str, str]]:
    """Anlam denetimi isteği: özgün metin ve numaralı Kolay Dil metni (onarımla aynı numaralar).

    Özgün metin aracın kesin düzeltmeleriyle gider: araç tarihe haftanın gününü kendisi ekliyor;
    denetçi "Salı" özgün metinde yok, uydurma deyince model onu siliyor, araç geri ekliyordu."""
    lines, spans = _numbered(text)
    body = ["Özgün metin:", _autofix(original, profile), "", "Kolay Dil çevirisi:"]
    body += [f"[{n}] {lines[i].strip()}" for n, (i, _, _) in enumerate(spans, 1)]
    return [{"role": "system", "content": MEANING_PROMPT}, {"role": "user", "content": "\n".join(body)}]


def parse_meaning(reply: str, line_count: int) -> list[tuple[int, str]]:
    """"[n] sorun" satırları. Numara metinde yoksa sorun satıra bağlanmaz (0). Biçime uymayan
    yanıt sorun sayılmaz: denetçi yanılırsa öneri haksız yere elenmesin."""
    out: dict[tuple[int, str], None] = {}
    for raw in clean_reply(reply).split("\n"):
        m = _ISSUE_RE.match(raw.strip())
        if not m:
            continue
        issue = m.group(2).strip()
        if not issue or turkish_lower(issue).rstrip(".") == "tamam":
            continue
        n = int(m.group(1))
        out[(n if 1 <= n <= line_count else 0, issue[:300])] = None
    return list(out)[:MAX_MEANING_ISSUES]


def check_meaning(original: str, text: str, url: str, model: str, key: str,
                  profile: str = "kolay-dil") -> list[tuple[int, str]]:
    reply = call_chat(url, model, key, build_meaning_messages(original, text, profile))
    return parse_meaning(reply, len(_numbered(text)[1]))


def _meaning_line(text: str, n: int, issue: str) -> str:
    """Kullanıcıya gösterilecek anlam sorunu: hangi satır, ne sorun."""
    lines, spans = _numbered(text)
    if 1 <= n <= len(spans):
        return f"'{lines[spans[n - 1][0]].strip()[:80]}': {issue}"
    return issue


def apply_repair(text: str, reply: str) -> str:
    """"[n]" bloklarını metnin n. dolu satırının yerine koyar. Numarasız yanıt yoksayılır."""
    lines, spans = _numbered(text)
    blocks: dict[int, list[str]] = {}
    current: list[str] | None = None
    for raw in clean_reply(reply).split("\n"):
        m = _ITEM_RE.match(raw.strip())
        if m:
            current = blocks.setdefault(int(m.group(1)), [])
            if m.group(2).strip():
                current.append(m.group(2).strip())
        elif current is not None and raw.strip():
            current.append(raw.strip())
    for n, new in blocks.items():
        if 1 <= n <= len(spans) and new:
            lines[spans[n - 1][0]] = "\n".join(_clean_text(x) for x in new)
    return "\n".join(lines)


def _rewrite(*args: Any, **kwargs: Any) -> RewriteResult:
    """Bir yeniden yazma işi: abonelik aracında bütün istekler tek konuşmadan geçer (_cli_job)."""
    with _cli_job():
        return _rewrite_steps(*args, **kwargs)


def _rewrite_steps(
    original: str,
    messages: list[dict[str, str]],
    provider: str,
    url: str,
    model: str,
    key: str,
    profile: str,
    whole: bool,
) -> RewriteResult:
    reply = call_chat(url, model, key, messages)
    reply = _punctuate(_clean_text(reply)) if whole else clean_reply(reply)
    if not reply:
        raise RewriteError("Model boş bir yanıt verdi. Yeniden deneyin ya da başka bir model seçin.")
    best = _evaluate(original, reply, profile)
    calls = 1
    stopped = ""
    if MEANING_CHECK:
        try:
            best.meaning = check_meaning(original, best.text, url, model, key, profile)
            calls += 1
        except RewriteError as exc:
            stopped = f"Öneri anlam bakımından denetlenemedi: {exc}"
    _log.info("ilk öneri:\n%s\nbulgu %.2f, anlam %s", best.text, best.penalty, best.meaning)
    for _ in range(REPAIR_ROUNDS):  # her tur o ana kadarki en iyi öneriyi onarır
        if stopped or (best.facts_ok and not best.meaning and not _open_findings(best.report)):
            break
        try:
            reply = call_chat(url, model, key, build_repair_messages(original, best))
        except RewriteError as exc:  # kota ya da bağlantı: elimizdeki en iyi öneriyle dönülür
            stopped = f"Öneri yeniden denetlendi ama onarılamadı: {exc}"
            break
        fixed = apply_repair(best.text, reply)
        calls += 1
        if whole:
            fixed = _punctuate(fixed)
        if fixed == best.text:
            # Yanıtta "[n]" bloğu varsa model satırı bilerek bıraktı (istem buna izin veriyor):
            # yinelemek boşa istek. Blok yoksa yanıt biçime uymadı: yeniden denenir.
            formatted = any(_ITEM_RE.match(x.strip()) for x in clean_reply(reply).split("\n"))
            _log.info("onarım %d: değişiklik yok (%s)", calls, "bitti" if formatted else "biçimsiz yanıt")
            if formatted:
                break
            continue
        cand = _evaluate(original, fixed, profile)
        if MEANING_CHECK:
            try:
                cand.meaning = check_meaning(original, cand.text, url, model, key, profile)
                calls += 1
            except RewriteError as exc:  # denetlenmemiş onarım seçilmez: anlamı bozmuş olabilir
                stopped = f"Onarım anlam bakımından denetlenemedi: {exc}"
                break
        chosen = _better(cand, best)
        _log.info("onarım %d (%s):\n%s\nbulgu %.2f, anlam %s", calls, "seçildi" if chosen else "elendi",
                  cand.text, cand.penalty, cand.meaning)
        if chosen:
            best = cand
    if whole:  # uzun paragrafları en sonda bir kez böl (her turda bölünce boş satır birikir)
        split = _evaluate(original, _split_paragraphs(best.text), profile)
        split.meaning = best.meaning  # boş satır numaraları kaydırmaz: yalnızca dolu satırlar sayılır
        best = split
    result = _result(original, best, provider, model, profile, calls)
    if stopped:
        result.note = f"{result.note} {stopped}".strip()
    return result


def _result(original: str, best: _Candidate, provider: str, model: str, profile: str, calls: int) -> RewriteResult:
    side_before = _side(analyze(original, profile=profile, max_chars=None))
    side_after = _side(best.report)
    note = ""
    if not best.facts_ok:
        parts = []
        if best.missing:
            parts.append("Öneride şu bilgiler yok: " + ", ".join(_describe(f) for f in best.missing) + ".")
        if best.added:
            parts.append("Öneride özgün metinde olmayan bilgiler var: "
                         + ", ".join(_describe(f) for f in best.added) + ".")
        note = " ".join(parts) + " Öneriyi uygulamadan önce bilgileri denetleyin."
    elif side_after.findings > side_before.findings or side_after.errors > side_before.errors:
        note = "Öneride özgün metinden daha çok bulgu var. Uygulamadan önce okuyun."
    meaning = [_meaning_line(best.text, n, issue) for n, issue in best.meaning]
    if meaning:
        note = (f"{note} Anlam denetimi şu sorunları buldu: " + " · ".join(meaning)
                + " Uygulamadan önce özgün metinle karşılaştırın.").strip()
    return RewriteResult(
        text=best.text, provider=provider, model=model, before=side_before, after=side_after,
        missing=[_describe(f) for f in best.missing], added=[_describe(f) for f in best.added],
        applicable=best.facts_ok, note=note, calls=calls,
        remaining=[_problem(f) for f in _open_findings(best.report)], meaning=meaning,
    )


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
    return _rewrite(sentence, build_messages(sentence, problems, before, after), provider, url,
                    model, key, profile, whole=False)


def rewrite_text(
    text: str,
    provider: str,
    model: str = "",
    key: str = "",
    first: bool = True,
    profile: str = "kolay-dil",
    context: str = "",
) -> RewriteResult:
    """Metni (ya da uzun metnin bir bölümünü) kolaydil.tr biçiminde Kolay Dil'e çevirir: başlık,
    her cümle ayrı satırda, kısa paragraflar, ara başlıklar, listeler. context: önceki bölümün
    Kolay Dil çevirisi; son MAX_CONTEXT_CHARS karakteri bağlam olarak gider."""
    text = text.strip()
    if not text:
        raise RewriteError("Çevrilecek metin boş.", 400)
    if len(text) > MAX_TEXT_CHARS:
        raise RewriteError(f"Bölüm çok uzun (en çok {MAX_TEXT_CHARS} karakter).", 413)
    url, model, key = resolve(provider, model, key)
    report = analyze(text, profile=profile, max_chars=None)
    # Kelime bulguları modele karşılığı söyler ("müracaat" → "başvuru"); cümle bulguları
    # kuralların içinde zaten var.
    problems = list(dict.fromkeys(
        _problem(f) for f in _open_findings(report) if f.rule_id.startswith("KD-K")))[:40]
    context = context.strip()
    if len(context) > MAX_CONTEXT_CHARS:  # satır başından kes: yarım cümle modeli yanıltmasın
        tail = context[-MAX_CONTEXT_CHARS:]
        context = tail[tail.find("\n") + 1:] if "\n" in tail else tail
    return _rewrite(text, build_text_messages(text, problems, first, context), provider, url, model,
                    key, profile, whole=True)
