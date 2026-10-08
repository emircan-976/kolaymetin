"""Web uygulaması (FastAPI): yerelde `kolaymetin sunucu`, çevrim içi Vercel'de çalışır.

Metin denetim için bu sunucuya gönderilir. Hiçbir yerde saklanmaz: yalnızca istek süresince
bellekte tutulur ve günlüğe yazılmaz. Hiçbir dış kaynak yüklenmez; İçerik Güvenliği Politikası
(CSP) dış istekleri engeller. Tek istisna isteğe bağlı yeniden yazmadır (/api/yeniden-yaz): sunucu,
kullanıcının seçtiği dil modeli sağlayıcısına yalnızca o cümleyi gönderir (bkz. rewrite.py).
"""

from __future__ import annotations

import html
import os
import re
import threading
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from kolaymetin import __version__, rewrite
from kolaymetin.api import MAX_CHARS, EmptyInput, InputTooLong, analyze
from kolaymetin.io.readers import SUPPORTED, ReaderError, read_bytes
from kolaymetin.lexicon import LexiconError, load_lexicon
from kolaymetin.profiles import BUILTIN_PROFILES, ProfileError, load_profile
from kolaymetin.rules import all_rules
from kolaymetin.text import morphology

STATIC_DIR = Path(str(resources.files("kolaymetin").joinpath("web", "static")))
# Vercel isteğin gövdesini 4,5 MB'ta keser ve düz metin bir 413 döndürür; sınır onun altında.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
MAX_IGNORED_CHARS = 4 * MAX_CHARS
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline'; script-src 'self'; "
    "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)
CATEGORY_TITLES = {"cümle": "Cümle", "kelime": "Kelime", "biçim": "Biçim", "metin": "Metin"}
CATEGORY_COVERS = {"cümle": "cumle", "kelime": "kelime", "biçim": "bicim", "metin": "metin"}
# İstemci (IP) başına dakikada en fazla bu kadar API isteği. "Yazarken denetle" en az 600 ms
# bekler; dakikada 60 istek yazan biri için bol. Vercel'de (VERCEL=1) varsayılan olarak açık,
# yerel kurulumda kapalı; KOLAYMETIN_HIZ_SINIRI ile değiştirilir (0 = kapalı).
DEFAULT_RATE_LIMIT = 60
RATE_WINDOW = 60.0
RATE_MESSAGE = "Çok fazla istek gönderildi. Bir dakika bekleyip yeniden deneyin."
STATUS_MESSAGES = {
    404: "Bu adres yok.",
    405: "Bu adrese bu yöntemle istek gönderilemez.",
    413: "İstek çok büyük.",
}
ROBOTS = "User-agent: *\nAllow: /\n"
NOT_FOUND_PAGE = (
    "<!DOCTYPE html><html lang='tr'><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'><title>Sayfa yok</title>"
    "<link rel='icon' href='/static/isaret.svg' type='image/svg+xml'>"
    "<link rel='stylesheet' href='/static/style.css'><body><main class='rapor'>"
    "<h1>Bu sayfa yok</h1><p><a href='{href}'>{label}</a></p></main>"
)
EXTRA_PAGES = [("index", "Kolay Dil nedir?"), ("skorlar", "Skorlar"), ("kaynaklar", "Kaynaklar"),
               ("katki", "Katkıda bulunma")]


class IgnoredItem(BaseModel):
    rule_id: str = Field(max_length=16)
    # Cümle ve paragraf kuralları (KD-C01, KD-M01 …) bütün cümleyi ya da paragrafı işaretler;
    # yoksayılan metin denetlenen metin kadar uzun olabilir.
    text: str = Field(max_length=MAX_CHARS)


class AnalyzeRequest(BaseModel):
    text: str
    profile: str = "kolay-dil"
    custom_lexicon: str | dict[str, Any] | None = None
    ignored: list[IgnoredItem] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def _ignored_size(self) -> AnalyzeRequest:
        if sum(len(i.text) for i in self.ignored) > MAX_IGNORED_CHARS:
            raise ValueError("Yoksayılan bulgular çok uzun. 'Yoksayılanları geri al' düğmesine basın.")
        return self


class ExportRequest(AnalyzeRequest):
    format: Literal["json", "md", "html"] = "json"


class RewriteRequest(BaseModel):
    """Bir cümleyi dil modeliyle yeniden yazma isteği. Sağlayıcının adresi istekte yoktur:
    yalnızca bilinen sağlayıcıların kimliği gönderilir (bkz. rewrite.resolve)."""

    sentence: str = Field(max_length=2000)
    problems: list[str] = Field(default_factory=list, max_length=30)
    before: str = Field(default="", max_length=2000)
    after: str = Field(default="", max_length=2000)
    profile: str = "kolay-dil"
    provider: str = Field(max_length=32)
    model: str = Field(default="", max_length=120)
    key: str = Field(default="", max_length=300)


def rehber_dir() -> Path:
    """Rehber Markdown dosyalarının klasörü (kurulu paket ya da kaynak ağacı)."""
    packaged = Path(str(resources.files("kolaymetin").joinpath("_rehber")))
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[3] / "docs" / "rehber"


def _parse_lexicon(value: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value
    try:
        data = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        raise HTTPException(422, f"Sözlük okunamadı (YAML hatası): {exc}") from exc
    if data is None:
        return None
    if not isinstance(data, dict):
        raise HTTPException(422, "Sözlük bir sözlük (anahtar: değer) içermeli.")
    return data


def _run(req: AnalyzeRequest) -> Any:
    if req.profile not in BUILTIN_PROFILES:
        raise HTTPException(422, "Bilinmeyen profil. 'kolay-dil' ya da 'sade-dil' seçin.")
    if len(req.text) > MAX_CHARS:
        raise HTTPException(
            413,
            f"Metin çok uzun: {len(req.text):,} karakter. En fazla {MAX_CHARS:,} karakter "
            "denetlenebilir. Metni bölümlere ayırın.".replace(",", "."),
        )
    try:
        return analyze(
            req.text,
            profile=req.profile,
            custom_lexicon=_parse_lexicon(req.custom_lexicon),
            ignored=[i.model_dump() for i in req.ignored],
        )
    except (LexiconError, ProfileError, EmptyInput) as exc:
        raise HTTPException(422, str(exc)) from exc
    except InputTooLong as exc:  # pragma: no cover - yukarıda yakalanır
        raise HTTPException(413, str(exc)) from exc


class RateLimiter:
    """Bellekte kayan pencereli basit sınır. Sunucusuz ortamda her örneğin kendi belleği vardır;
    tek bir betiğin art arda yüzlerce istek atmasını yine de durdurur."""

    def __init__(self, limit: int, window: float = RATE_WINDOW) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > 10_000:  # bellek sınırı: eski istemcileri at
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self.window}
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def _rate_limit_from_env() -> int:
    value = os.environ.get("KOLAYMETIN_HIZ_SINIRI")
    if value is not None and value.strip().isdigit():
        return int(value)
    return DEFAULT_RATE_LIMIT if os.environ.get("VERCEL") else 0


def client_key(request: Request) -> str:
    """İstemcinin IP adresi. Vercel x-forwarded-for başlığını kendisi yazar (istemci uyduramaz)."""
    forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


def public_base(request: Request) -> str:
    """Sayfanın dışarıdan görünen adresi ("https://….vercel.app"): rapordaki rehber bağlantıları
    için. Vercel'de istek uygulamaya http olarak gelir; özgün şema başlıktan okunur."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host.split(',')[0].strip()}"


_UNSAFE_NAME_RE = re.compile(r"[^\w .()-]+")


def safe_filename(name: str) -> str:
    """Yanıtta geri dönen dosya adı: klasör kısmı ve harf, rakam, boşluk, nokta, tire, parantez
    dışındaki karakterler (<, >, ", / …) atılır. Arayüz textContent kullanır; ileride biri
    innerHTML kullanırsa da açık oluşmasın."""
    base = re.split(r"[\\/]", name)[-1]
    return _UNSAFE_NAME_RE.sub("", base).strip()[:120] or "belge"


def utf16_offsets(data: Any, text: str) -> Any:
    """Python ofsetleri kod noktası (code point) sayar, tarayıcı ise UTF-16 birimi. Emoji gibi
    BMP dışı karakterler JavaScript'te iki birimdir; dönüştürülmezse ardından gelen bütün
    işaretler kayar. Yanıttaki her "start"/"end" değerini UTF-16 ofsetine çevirir."""
    if all(ord(c) < 0x10000 for c in text):
        return data
    table = [0] * (len(text) + 1)
    for i, c in enumerate(text):
        table[i + 1] = table[i] + (2 if ord(c) >= 0x10000 else 1)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("start", "end") and isinstance(value, int) and 0 <= value <= len(text):
                    node[key] = table[value]
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        return node

    return walk(data)


def _warm() -> None:
    morphology.warm_up()
    load_lexicon()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    threading.Thread(target=_warm, daemon=True).start()
    yield


# --------------------------------------------------------------------------- rehber


@lru_cache(maxsize=1)
def _markdown() -> Any:
    from markdown_it import MarkdownIt

    return MarkdownIt("commonmark", {"html": True, "typographer": False}).enable("table")


_LINK_RE = re.compile(r'href="(?:\./)?([A-Za-z0-9-]+)\.md(#[^"]*)?"')


def render_markdown(text: str) -> str:
    out = str(_markdown().render(text))
    return _LINK_RE.sub(lambda m: f'href="/rehber/{m.group(1)}{m.group(2) or ""}"', out)


def _menu(current: str) -> str:
    def link(slug: str, title: str) -> str:
        cur = ' aria-current="page"' if slug == current else ""
        href = "/rehber" if slug == "index" else f"/rehber/{slug}"
        return f'<li><a href="{href}"{cur}>{html.escape(title)}</a></li>'

    parts = ['<nav aria-label="Rehber menüsü"><h2 class="etiket">Genel</h2><ul>']
    parts += [link(slug, title) for slug, title in EXTRA_PAGES]
    parts.append("</ul>")
    for cat, title in CATEGORY_TITLES.items():
        parts.append(f'<h2 class="etiket">{title} kuralları</h2><ul>')
        for rule in all_rules():
            if rule.level == cat:
                parts.append(link(rule.id, f"{rule.id} {rule.name}"))
        parts.append("</ul>")
    parts.append("</nav>")
    return "".join(parts)


def _covers() -> str:
    cards = []
    for cat, title in CATEGORY_TITLES.items():
        items = "".join(
            f'<li><a href="/rehber/{r.id}">{r.id} {html.escape(r.name)}</a></li>'
            for r in all_rules() if r.level == cat
        )
        cards.append(
            f'<section class="kapak"><span class="dither dither--kapak dither--{CATEGORY_COVERS[cat]}" '
            f'aria-hidden="true"></span><h3>{title} kuralları</h3><ul>{items}</ul></section>'
        )
    return '<h2>Kurallar</h2><div class="kapaklar">' + "".join(cards) + "</div>"


def rehber_slug(slug: str) -> str | None:
    """Sayfanın dosya adındaki yazımı: "kd-c01" → "KD-C01". Vercel'in (Linux) dosya sistemi
    büyük-küçük harf ayırır; Windows'ta küçük harfli adres de açılır."""
    if not re.fullmatch(r"[A-Za-z0-9-]+", slug):
        return None
    for path in rehber_dir().glob("*.md"):
        if path.stem.lower() == slug.lower():
            return path.stem
    return None


def rehber_page(slug: str) -> str | None:
    base = rehber_dir()
    path = base / f"{slug}.md"
    if not re.fullmatch(r"[A-Za-z0-9-]+", slug) or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", text, re.M)
    title = title_match.group(1).strip() if title_match else slug
    body = render_markdown(text)
    if slug == "index":
        body += _covers()
    template = (STATIC_DIR / "rehber.html").read_text(encoding="utf-8")
    return (
        template.replace("{{baslik}}", html.escape(title))
        .replace("{{menu}}", _menu(slug))
        .replace("{{icerik}}", body)
        .replace("{{surum}}", __version__)
    )


# --------------------------------------------------------------------------- uygulama


def _profile_summary(name: str) -> dict[str, Any]:
    p = load_profile(name)
    return {
        "name": p.name,
        "title": p.title,
        "description": p.description,
        "compliance_k": p.compliance_k,
        "weights": p.weights,
        "rules": {rid: cfg.model_dump() for rid, cfg in p.rules.items()},
    }


@lru_cache(maxsize=1)
def _samples() -> list[dict[str, str]]:
    folder = resources.files("kolaymetin").joinpath("data", "ornekler")
    index = yaml.safe_load(folder.joinpath("ornekler.yaml").read_text(encoding="utf-8")) or []
    out = []
    for item in index:
        text = folder.joinpath(item["dosya"]).read_text(encoding="utf-8")
        out.append({"id": item["id"], "baslik": item["baslik"], "metin": text})
    return out


def create_app() -> FastAPI:
    app = FastAPI(
        title="kolaymetin",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )

    app.state.hiz_siniri = RateLimiter(_rate_limit_from_env())

    @app.middleware("http")
    async def _headers(request: Request, call_next: Any) -> Response:
        response: Response
        limiter: RateLimiter = app.state.hiz_siniri
        if (
            request.method == "POST"
            and request.url.path.startswith("/api/")
            and not limiter.allow(client_key(request))
        ):
            response = JSONResponse(
                {"detail": RATE_MESSAGE}, status_code=429,
                headers={"Retry-After": str(int(limiter.window))},
            )
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        # Eski tarayıcılar CSP frame-ancestors'u bilmez: sayfa başka sitede çerçeveye alınmasın.
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/robots.txt", include_in_schema=False)
    def robots() -> PlainTextResponse:
        return PlainTextResponse(ROBOTS)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "isaret.svg", media_type="image/svg+xml")

    @app.get("/stil-rehberi", include_in_schema=False)
    def stil_rehberi() -> FileResponse:
        return FileResponse(STATIC_DIR / "stil-rehberi.html", media_type="text/html; charset=utf-8")

    @app.get("/saglik")
    def saglik() -> dict[str, str]:
        # Arayüz sayfa açılınca bunu çağırır: sunucusuz ortamda (Vercel) açılış iş parçacığı
        # yanıttan sonra dondurulabildiği için ısıtma ilk denetime kalmasın diye burada yapılır.
        _warm()
        return {"durum": "tamam", "surum": __version__, "morfoloji": morphology.backend_name()}

    @app.post("/api/analyze")
    def api_analyze(req: AnalyzeRequest) -> JSONResponse:
        report = _run(req)
        return JSONResponse(utf16_offsets(report.to_dict(), req.text))

    @app.post("/api/export")
    def api_export(req: ExportRequest, request: Request) -> Response:
        report = _run(req)
        base = public_base(request)
        if req.format == "json":
            body, media, ext = report.to_json(), "application/json", "json"
        elif req.format == "md":
            body, media, ext = report.to_markdown(base), "text/markdown", "md"
        else:
            body, media, ext = report.to_html(base), "text/html", "html"
        return Response(
            content=body.encode("utf-8"),
            media_type=f"{media}; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="kolaymetin-rapor.{ext}"'},
        )

    @app.post("/api/upload")
    async def api_upload(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        name = file.filename or ""
        if Path(name).suffix.lower() not in SUPPORTED:
            raise HTTPException(
                422, "Bu dosya türü desteklenmiyor. Desteklenen türler: .txt, .md, .docx, .pdf"
            )
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Dosya çok büyük. En fazla 4 MB yükleyebilirsiniz.")
        try:
            text = read_bytes(data, name)
        except ReaderError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not text.strip():
            raise HTTPException(422, "Dosyada metin yok. Dosya boş olabilir.")
        if len(text) > MAX_CHARS:
            raise HTTPException(
                413,
                f"Dosyadaki metin çok uzun: {len(text):,} karakter. En fazla {MAX_CHARS:,} "
                "karakter denetlenebilir. Metni bölümlere ayırın.".replace(",", "."),
            )
        return {"text": text, "dosya_adi": safe_filename(name), "karakter": len(text)}

    @app.get("/api/yz")
    def api_yz() -> dict[str, Any]:
        """Yeniden yazma için kullanılabilen dil modeli sağlayıcıları."""
        return {"saglayicilar": rewrite.available_providers(), "cevrimici": rewrite.is_public_server()}

    @app.post("/api/yeniden-yaz")
    def api_yeniden_yaz(req: RewriteRequest) -> dict[str, Any]:
        if req.profile not in BUILTIN_PROFILES:
            raise HTTPException(422, "Bilinmeyen profil. 'kolay-dil' ya da 'sade-dil' seçin.")
        try:
            result = rewrite.rewrite_sentence(
                req.sentence, [p[:300] for p in req.problems], req.provider, req.model, req.key,
                req.before, req.after, req.profile,
            )
        except rewrite.RewriteError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return result.model_dump()

    @app.get("/api/rules")
    def api_rules() -> list[dict[str, Any]]:
        profiles = {name: load_profile(name) for name in BUILTIN_PROFILES}
        return [
            {
                "id": r.id,
                "name": r.name,
                "level": r.level,
                "default_severity": r.default_severity,
                "summary": r.summary,
                "rehber_url": r.rehber_url,
                "profiles": {n: p.rule(r.id).model_dump() for n, p in profiles.items()},
            }
            for r in all_rules()
        ]

    @app.get("/api/profiles")
    def api_profiles() -> list[dict[str, Any]]:
        return [_profile_summary(n) for n in BUILTIN_PROFILES]

    @app.get("/api/ornekler")
    def api_ornekler() -> list[dict[str, str]]:
        return _samples()

    @app.get("/rehber", response_class=HTMLResponse)
    def rehber_index() -> HTMLResponse:
        page = rehber_page("index")
        if page is None:  # pragma: no cover - paket bozuksa
            raise HTTPException(404, "Rehber bulunamadı.")
        return HTMLResponse(page)

    @app.get("/rehber/{sayfa}", response_class=HTMLResponse)
    def rehber(sayfa: str) -> Response:
        slug = sayfa.removesuffix(".md")
        canonical = rehber_slug(slug)
        if canonical is not None and canonical != slug:
            return RedirectResponse(f"/rehber/{canonical}", status_code=308)
        page = rehber_page(slug)
        if page is None:
            return HTMLResponse(
                NOT_FOUND_PAGE.format(href="/rehber", label="Rehberin başına dönün."),
                status_code=404,
            )
        return HTMLResponse(page)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        # Starlette'in kendi hataları ("Not Found", "Method Not Allowed") İngilizcedir.
        detail = exc.detail if isinstance(exc, HTTPException) else None
        if not isinstance(detail, str) or not detail:
            detail = STATUS_MESSAGES.get(exc.status_code, "İstek yerine getirilemedi.")
        if exc.status_code == 404 and not request.url.path.startswith("/api/"):
            return HTMLResponse(
                NOT_FOUND_PAGE.format(href="/", label="Ana sayfaya dönün."), status_code=404
            )
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        own = [str(e.get("msg", "")).removeprefix("Value error, ") for e in errors
               if e.get("type") == "value_error"]
        if own:
            return JSONResponse({"detail": " ".join(own)}, status_code=422)
        if any(e.get("type") == "json_invalid" for e in errors):
            return JSONResponse(
                {"detail": "Geçersiz istek: gövde geçerli bir JSON değil."}, status_code=422
            )
        if any(tuple(e.get("loc", ())) == ("body",) for e in errors):
            return JSONResponse(
                {"detail": "Geçersiz istek: gövde bir JSON nesnesi olmalı."}, status_code=422
            )
        fields = ", ".join(".".join(str(p) for p in e.get("loc", ())[1:]) or "gövde" for e in errors)
        return JSONResponse(
            {"detail": f"Geçersiz istek. Şu alanları kontrol edin: {fields}."}, status_code=422
        )

    return app


app = create_app()


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:  # pragma: no cover - ağ
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=True)
