"""Yerel web uygulaması (FastAPI).

Metin hiçbir yerde saklanmaz: yalnızca istek süresince bellekte tutulur ve günlüğe yazılmaz.
Hiçbir dış kaynak yüklenmez; İçerik Güvenliği Politikası (CSP) dış istekleri engeller.
"""

from __future__ import annotations

import html
import re
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from kolaymetin import __version__
from kolaymetin.api import MAX_CHARS, EmptyInput, InputTooLong, analyze
from kolaymetin.io.readers import ReaderError, read_bytes
from kolaymetin.lexicon import LexiconError, load_lexicon
from kolaymetin.profiles import BUILTIN_PROFILES, ProfileError, load_profile
from kolaymetin.rules import all_rules
from kolaymetin.text import morphology

STATIC_DIR = Path(str(resources.files("kolaymetin").joinpath("web", "static")))
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IGNORED_CHARS = 4 * MAX_CHARS
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline'; script-src 'self'; "
    "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)
CATEGORY_TITLES = {"cümle": "Cümle", "kelime": "Kelime", "biçim": "Biçim", "metin": "Metin"}
CATEGORY_COVERS = {"cümle": "cumle", "kelime": "kelime", "biçim": "bicim", "metin": "metin"}
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

    @app.middleware("http")
    async def _headers(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/stil-rehberi", include_in_schema=False)
    def stil_rehberi() -> FileResponse:
        return FileResponse(STATIC_DIR / "stil-rehberi.html", media_type="text/html; charset=utf-8")

    @app.get("/saglik")
    def saglik() -> dict[str, str]:
        return {"durum": "tamam", "surum": __version__, "morfoloji": morphology.backend_name()}

    @app.post("/api/analyze")
    def api_analyze(req: AnalyzeRequest) -> JSONResponse:
        report = _run(req)
        return JSONResponse(report.to_dict())

    @app.post("/api/export")
    def api_export(req: ExportRequest) -> Response:
        report = _run(req)
        if req.format == "json":
            body, media, ext = report.to_json(), "application/json", "json"
        elif req.format == "md":
            body, media, ext = report.to_markdown(), "text/markdown", "md"
        else:
            body, media, ext = report.to_html(), "text/html", "html"
        return Response(
            content=body.encode("utf-8"),
            media_type=f"{media}; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="kolaymetin-rapor.{ext}"'},
        )

    @app.post("/api/upload")
    async def api_upload(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Dosya çok büyük. En fazla 10 MB yükleyebilirsiniz.")
        try:
            text = read_bytes(data, file.filename or "belge.txt")
        except ReaderError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"text": text, "dosya_adi": file.filename, "karakter": len(text)}

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
    def rehber(sayfa: str) -> HTMLResponse:
        page = rehber_page(sayfa.removesuffix(".md"))
        if page is None:
            return HTMLResponse(
                "<!DOCTYPE html><html lang='tr'><meta charset='utf-8'><title>Sayfa yok</title>"
                "<link rel='stylesheet' href='/static/style.css'><body><main class='rapor'>"
                "<h1>Bu sayfa yok</h1><p><a href='/rehber'>Rehberin başına dönün.</a></p></main>",
                status_code=404,
            )
        return HTMLResponse(page)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        own = [str(e.get("msg", "")).removeprefix("Value error, ") for e in errors
               if e.get("type") == "value_error"]
        if own:
            return JSONResponse({"detail": " ".join(own)}, status_code=422)
        fields = ", ".join(".".join(str(p) for p in e.get("loc", ())[1:]) or "gövde" for e in errors)
        return JSONResponse(
            {"detail": f"Geçersiz istek. Şu alanları kontrol edin: {fields}."}, status_code=422
        )

    return app


app = create_app()


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:  # pragma: no cover - ağ
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=True)
