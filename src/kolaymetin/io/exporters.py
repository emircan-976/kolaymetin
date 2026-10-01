"""Rapor dışa aktarma: JSON, Markdown ve bağımsız tek dosya HTML."""

from __future__ import annotations

import base64
import datetime as dt
import html
import itertools
import os
import re
from collections import defaultdict
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING

from kolaymetin.models import SEVERITY_ORDER, Finding

if TYPE_CHECKING:
    from kolaymetin.models import ReadabilityScore, Report

SEV_CLASS = {"hata": "hata", "uyarı": "uyari", "bilgi": "bilgi"}
SEV_LABEL = {"hata": "Hata", "uyarı": "Uyarı", "bilgi": "Bilgi"}
SEV_ICON = {"hata": "isaret-hata", "uyarı": "isaret-uyari", "bilgi": "isaret-bilgi"}
SEV_MD = {"hata": "■ Hata", "uyarı": "□ Uyarı", "bilgi": "○ Bilgi"}
CAT_LABEL = {"cümle": "Cümle", "kelime": "Kelime", "biçim": "Biçim", "metin": "Metin"}
_MIME = {".woff2": "font/woff2", ".png": "image/png", ".svg": "image/svg+xml"}
_MONTHS = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül",
           "Ekim", "Kasım", "Aralık")
_WEEKDAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
_TURKEY = dt.timezone(dt.timedelta(hours=3))


def readable_date(iso: str) -> str:
    """"2026-10-01T21:44:24+00:00" → "2 Ekim 2026 Cuma, 00.44" (Türkiye saati). Araç sayısal
    tarihleri KD-B04 ile işaretlediği için rapor da tarihi ayın adıyla yazar."""
    try:
        when = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if when.tzinfo is not None:
        when = when.astimezone(_TURKEY)
    return (
        f"{when.day} {_MONTHS[when.month - 1]} {when.year} {_WEEKDAYS[when.weekday()]}, "
        f"{when.hour:02d}.{when.minute:02d}"
    )


def rehber_link(f: Finding, base_url: str = "") -> str:
    """Rehber sayfasının tam adresi. İndirilen raporda "/rehber/KD-C01" gibi göreli bir yol
    işe yaramaz. base_url verilmezse KOLAYMETIN_ADRES ortam değişkenine bakılır."""
    base = (base_url or os.environ.get("KOLAYMETIN_ADRES", "")).rstrip("/")
    return base + f.rehber_url if base and f.rehber_url.startswith("/") else f.rehber_url


def _ignored_summary(report: Report) -> str | None:
    c = report.scores.compliance
    if not c.ignored_count:
        return None
    return (
        f"{c.ignored_count} bulgu yoksayıldı ve skora katılmadı. "
        f"Yoksaymadan skor: {score_value(c.raw_value)} / 100."
    )


def dither_level(score: float) -> int:
    """0–100 skoru 17 Bayer desen seviyesinden birine çevirir (her %6,25 bir seviye)."""
    return max(0, min(16, round(score / 6.25)))


# --------------------------------------------------------------------------- JSON


def to_json(report: Report, indent: int | None = 2) -> str:
    return report.model_dump_json(indent=indent)


# --------------------------------------------------------------------------- Markdown


def _md_escape(text: str) -> str:
    return re.sub(r"([\\`*_\[\]<>|])", r"\\\1", text)


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}".replace(".", ",")


def _readability_line(s: ReadabilityScore) -> str:
    grade = f" ({s.grade})" if s.grade else ""
    return f"| {s.name} | {_fmt(s.value)} | {s.level}{grade} |"


def _md_finding(f: Finding, base_url: str) -> list[str]:
    lines = [f"- **{SEV_MD[f.severity]} · {f.rule_id} {f.rule_name}** — {f.message}"]
    if f.text:
        lines.append(f"  - Yer: “{_md_escape(f.text[:120])}”")
    lines.append(f"  - Neden: {f.explanation}")
    if f.suggestion:
        lines.append(f"  - → Öneri: {f.suggestion}")
    if f.confidence < 1:
        lines.append(f"  - Güven: {f.confidence:.2f}")
    link = rehber_link(f, base_url)
    lines.append(f"  - Rehber: [{f.rule_id}]({link})" if link.startswith("http") else f"  - Rehber: {link}")
    return lines


def to_markdown(report: Report, base_url: str = "") -> str:
    sc = report.scores
    c = sc.compliance
    st = report.stats
    lines = [
        "# kolaymetin denetim raporu",
        "",
        f"- **Profil:** {report.profile_title} (`{report.profile}`)",
        f"- **Tarih:** {readable_date(report.created_at)}",
        f"- **Sürüm:** kolaymetin {report.version} · morfoloji: {report.morphology}",
        "",
    ]
    for note in report.notes:
        lines.append(f"> {note}")
    lines += [
        "",
        "## Skorlar",
        "",
        f"**{score_title(report)}: {score_value(c.value)} / 100**"
        + (f" — _{c.note}_" if c.note else ""),
        "",
    ]
    ignored = _ignored_summary(report)
    if ignored:
        lines += [f"**{ignored}**", ""]
    lines += [
        "| Kategori | Skor | Bulgu |",
        "|---|---:|---:|",
    ]
    for cat in c.by_category:
        lines.append(
            f"| {CAT_LABEL[cat.category]} | {score_value(cat.score)} | {cat.finding_count} |"
        )
    lines += [
        "",
        "| Formül | Değer | Düzey |",
        "|---|---:|---|",
        _readability_line(sc.atesman),
        _readability_line(sc.cetinkaya_uzun),
        _readability_line(sc.bezirci_yilmaz),
        "",
        "_Bu üç formülün amacı Kolay Dil değildir. Formüller yalnızca hece ve cümle uzunluğunu ölçer._",
        "",
        "### Bu skor nasıl hesaplandı?",
        "",
        f"`{c.formula}`",
        "",
        f"Ağırlıklar: hata = {c.weights.get('hata', 3):g}, uyarı = {c.weights.get('uyarı', 1):g}, "
        f"bilgi = {c.weights.get('bilgi', 0.25):g}. k = {c.k:g}. Cümle sayısı: {c.sentence_count}. "
        f"Toplam ceza: {c.penalty:g}. Cümle başına ceza: {c.normalized:g}.",
        "",
    ]
    if c.contributions:
        lines += ["| Kural | Bulgu | Ceza |", "|---|---:|---:|"]
        for rc in c.contributions:
            lines.append(f"| {rc.rule_id} {rc.rule_name} | {rc.count} | {rc.penalty:g} |")
        lines.append("")
    lines += [
        "## Temel sayılar",
        "",
        f"- Kelime: {st.word_count}",
        f"- Cümle: {st.sentence_count}",
        f"- Paragraf: {st.paragraph_count}",
        f"- Ortalama cümle uzunluğu: {_fmt(st.avg_sentence_length)} kelime",
        f"- En uzun cümle: {st.longest_sentence_words} kelime",
        "",
        f"## Bulgular ({len(report.findings)})",
        "",
    ]
    if not report.findings:
        lines.append("Bu profilde bulgu yok.")
    by_sentence: dict[int | None, list[Finding]] = defaultdict(list)
    for f in report.findings:
        by_sentence[f.sentence_index].append(f)
    for idx in sorted(by_sentence, key=lambda i: (i is None, i if i is not None else 0)):
        if idx is not None and idx < len(report.sentences):
            lines.append(f"> {_md_escape(report.sentences[idx].text)}")
            lines.append("")
        for f in by_sentence[idx]:
            lines += _md_finding(f, base_url)
        lines.append("")
    if report.ignored_findings:
        lines += [
            f"## Yoksayılan bulgular ({len(report.ignored_findings)})",
            "",
            "Bu bulgular denetimde \"Yoksay\" ile kapatıldı. Skora katılmadılar.",
            "",
        ]
        for f in report.ignored_findings:
            lines += _md_finding(f, base_url)
        lines.append("")
    lines.append("---")
    lines.append("Bu rapor kolaymetin ile üretildi. Araç bir yardımcıdır; metni hedef okurlarla test edin.")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- HTML


def _static(name: str) -> bytes:
    return resources.files("kolaymetin").joinpath("web", "static", *name.split("/")).read_bytes()


@lru_cache(maxsize=1)
def _inline_css() -> str:
    """style.css + rapor.css; url(...) başvuruları data URI'ye çevrilir (dış istek yok)."""
    css = _static("style.css").decode("utf-8") + "\n" + _static("rapor.css").decode("utf-8")

    def repl(m: re.Match[str]) -> str:
        path = m.group(1).strip("\"'")
        if path.startswith("data:"):
            return m.group(0)
        suffix = "." + path.rsplit(".", 1)[-1]
        try:
            data = _static(path)
        except (FileNotFoundError, OSError):
            return m.group(0)
        b64 = base64.b64encode(data).decode("ascii")
        return f"url(data:{_MIME.get(suffix, 'application/octet-stream')};base64,{b64})"

    return re.sub(r"url\(([^)]+)\)", repl, css)


@lru_cache(maxsize=32)
def _icon(name: str) -> str:
    svg = _static(f"ikon/{name}.svg").decode("utf-8").strip()
    return svg.replace("<svg ", '<svg class="ikon" ', 1)


@lru_cache(maxsize=1)
def _dortlu() -> str:
    """Künyedeki işaret: isaret.svg'nin kendi renkleri atılır, renk style.css'ten gelir."""
    svg = _static("isaret.svg").decode("utf-8").strip()
    svg = re.sub(r"<title>.*?</title>|<style>.*?</style>", "", svg)
    svg = re.sub(r' width="16" height="16"', "", svg, count=1)
    return svg.replace("<svg ", '<svg class="dortlu" aria-hidden="true" ', 1)


@lru_cache(maxsize=1)
def _favicon() -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(_static("isaret.svg")).decode("ascii")


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def render_marked(text: str, findings: list[Finding], base: int = 0, numbers: dict[int, int] | None = None) -> str:
    """Metni düzeltmen işaretleriyle HTML'e çevirir. base: text'in orijinal metindeki başlangıcı."""
    bounds = {0, len(text)}
    spans = []
    for i, f in enumerate(findings):
        a, b = max(0, f.start - base), min(len(text), f.end - base)
        if a >= b:
            continue
        bounds.update((a, b))
        spans.append((a, b, i, f))
    points = sorted(bounds)
    out = []
    for a, b in itertools.pairwise(points):
        seg = _esc(text[a:b])
        covering = [(i, f) for (x, y, i, f) in spans if x <= a and b <= y]
        if covering:
            top = min(covering, key=lambda c: SEVERITY_ORDER[c[1].severity])[1]
            cls = SEV_CLASS[top.severity]
            if top.severity != "uyarı" and any(f.severity == "uyarı" for _, f in covering):
                cls += " imi--kalem"
            title = _esc("; ".join(f"{f.rule_id}: {f.message}" for _, f in covering))
            out.append(f'<span class="imi imi--{cls} imi--gorunur" title="{title}">{seg}</span>')
        else:
            out.append(seg)
        if numbers:
            for _x, y, i, f in spans:
                if y == b and i in numbers:
                    cls = SEV_CLASS[f.severity]
                    out.append(f'<span class="imi-no imi-no--{cls}">{numbers[i]}</span>')
    return "".join(out)


def _bar(score: float | None) -> str:
    shown = "—" if score is None else f"{score:.0f}"
    score = score or 0
    level = dither_level(score)
    return (
        f'<div class="cubuk-satir"><div class="cubuk" aria-hidden="true">'
        f'<div class="cubuk__dolgu d-{level:02d}" style="width:{max(0, min(100, score)):.0f}%"></div>'
        f'</div><span class="cubuk__deger">{shown}</span></div>'
    )


def score_value(value: int | None) -> str:
    return "—" if value is None else str(value)


def score_title(report: Report) -> str:
    """"Kolay Dil Uyum Skoru", "Sade Dil Uyum Skoru": başlık seçilen profile göre."""
    return f"{report.profile_title} Uyum Skoru"


def _readability_card(s: ReadabilityScore) -> str:
    grade = f"<p class='skor__duzey'>{_esc(s.grade)}</p>" if s.grade else ""
    return (
        f'<div class="skor"><h3 class="skor__baslik">{_esc(s.name)}</h3>'
        f'<div class="skor__deger">{_fmt(s.value)}</div>'
        f'<p class="skor__duzey">{_esc(s.level)}</p>{grade}</div>'
    )


def _rehber_html(f: Finding, base_url: str) -> str:
    link = rehber_link(f, base_url)
    if link.startswith("http"):
        return f'<p class="etiket">Rehber: <a href="{_esc(link)}">{_esc(link)}</a></p>'
    return f'<p class="etiket">Rehber: {_esc(link)}</p>'


def _card(f: Finding, number: int | None, base_url: str = "") -> str:
    cls = SEV_CLASS[f.severity]
    sugg = (
        f'<p class="not-kagidi__oneri"><span>{_esc(f.suggestion)}</span></p>' if f.suggestion else ""
    )
    conf = f" · güven {f.confidence:.2f}".replace(".", ",") if f.confidence < 1 else ""
    return (
        f'<article class="not-kagidi not-kagidi--{cls}">'
        f'<div class="not-kagidi__ust"><span class="onem onem--{cls}">{_icon(SEV_ICON[f.severity])}'
        f"{SEV_LABEL[f.severity]}</span>"
        f'<span class="kimlik kimlik--{cls}">{f"{number}. " if number else ""}{f.rule_id}</span>'
        f'<span class="not-kagidi__ad">{_esc(f.rule_name)}{conf}</span></div>'
        f'<p style="margin:0 0 6px;font-weight:700">{_esc(f.message)}</p>'
        f'<div class="not-kagidi__govde"><p>{_esc(f.explanation)}</p>{sugg}'
        f"{_rehber_html(f, base_url)}</div></article>"
    )


def to_html(report: Report, base_url: str = "") -> str:
    sc = report.scores
    c = sc.compliance
    st = report.stats
    numbers = {i: i + 1 for i in range(len(report.findings))}
    marked = render_marked(report.text, report.findings, 0, numbers)

    cats = "".join(
        f'<li><span class="etiket">{CAT_LABEL[cs.category]}</span>{_bar(cs.score)}</li>'
        for cs in c.by_category
    )
    contrib = "".join(
        f"<tr><td>{rc.rule_id} {_esc(rc.rule_name)}</td><td>{rc.count}</td><td>{rc.penalty:g}</td></tr>"
        for rc in c.contributions
    ) or '<tr><td colspan="3">Bulgu yok.</td></tr>'

    groups: dict[int | None, list[tuple[int, Finding]]] = defaultdict(list)
    for i, f in enumerate(report.findings):
        groups[f.sentence_index].append((i, f))
    group_html = []
    for idx in sorted(groups, key=lambda i: (i is None, i if i is not None else 0)):
        items = groups[idx]
        quote_html = ""
        if idx is not None and idx < len(report.sentences):
            s = report.sentences[idx]
            fs = [f for _, f in items]
            quote_html = f"<blockquote>{render_marked(s.text, fs, s.start)}</blockquote>"
        cards = "".join(_card(f, i + 1, base_url) for i, f in items)
        group_html.append(f'<div class="cumle-grubu">{quote_html}{cards}</div>')
    findings_html = "".join(group_html) or "<p class='bos-not'>Bu profilde bulgu yok.</p>"
    notes = "".join(f"<span>{_esc(n)}</span>" for n in report.notes)
    reliable = f"<p class='skor__not'>{_esc(c.note)}</p>" if c.note else ""
    ignored = _ignored_summary(report)
    if ignored:
        reliable += f"<p class='skor__not'><strong>{_esc(ignored)}</strong></p>"
    ignored_html = ""
    if report.ignored_findings:
        ignored_cards = "".join(_card(f, None, base_url) for f in report.ignored_findings)
        ignored_html = (
            f'<section aria-labelledby="yoksayilan"><h2 id="yoksayilan">Yoksayılan bulgular '
            f"({len(report.ignored_findings)})</h2><p>Bu bulgular denetimde \"Yoksay\" ile "
            f"kapatıldı. Skora katılmadılar.</p>{ignored_cards}</section>"
        )

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kolaymetin raporu — {_esc(report.profile_title)}</title>
<link rel="icon" href="{_favicon()}" type="image/svg+xml">
<style>{_inline_css()}</style>
</head>
<body>
<div class="rapor">
<header class="kunye">
  <div><p class="kunye__ad"><span class="kunye__imza">{_dortlu()}kolaymetin</span></p><p class="kunye__alt">Kolay Dil denetim raporu</p></div>
  <div class="kunye__sag"><p class="kunye__bilgi">{_esc(readable_date(report.created_at))}<br>Profil: {_esc(report.profile_title)}<br>Sürüm {_esc(report.version)}</p></div>
</header>
<p class="not-seridi">{notes}</p>
<main>
<section aria-labelledby="skorlar">
  <h2 id="skorlar">Skorlar</h2>
  <div class="rapor-skorlar">
    <div class="skor skor--buyuk">
      <h3 class="skor__baslik">{_esc(score_title(report))}</h3>
      <div class="skor__deger">{score_value(c.value)}<span class="etiket"> / 100</span></div>
      {_bar(c.value)}
      {reliable}
      <ul class="kategori-listesi">{cats}</ul>
    </div>
    <dl class="sayilar" style="grid-template-columns:1fr">
      <div><dt>Kelime</dt><dd>{st.word_count}</dd></div>
      <div><dt>Cümle</dt><dd>{st.sentence_count}</dd></div>
      <div><dt>Paragraf</dt><dd>{st.paragraph_count}</dd></div>
      <div><dt>Ortalama cümle</dt><dd>{_fmt(st.avg_sentence_length)}</dd></div>
      <div><dt>En uzun cümle</dt><dd>{st.longest_sentence_words}</dd></div>
      <div><dt>Bulgu</dt><dd>{len(report.findings)}</dd></div>
    </dl>
  </div>
  <div class="rapor-okunabilirlik">
    {_readability_card(sc.atesman)}{_readability_card(sc.cetinkaya_uzun)}{_readability_card(sc.bezirci_yilmaz)}
  </div>
  <p class="etiket">Bu üç formülün amacı Kolay Dil değildir. Formüller yalnızca hece ve cümle uzunluğunu ölçer.</p>
  <details class="aciklama-paneli" open>
    <summary>Bu skor nasıl hesaplandı?</summary>
    <p class="formul">{_esc(c.formula)}</p>
    <p>Ağırlıklar: hata = {c.weights.get('hata', 3):g}, uyarı = {c.weights.get('uyarı', 1):g}, bilgi = {c.weights.get('bilgi', 0.25):g}.
    k = {c.k:g}. Cümle sayısı: {c.sentence_count}. Toplam ceza: {c.penalty:g}. Cümle başına ceza: {c.normalized:g}.</p>
    <table class="katki-tablosu"><thead><tr><th>Kural</th><th>Bulgu</th><th>Ceza</th></tr></thead><tbody>{contrib}</tbody></table>
  </details>
</section>
<section aria-labelledby="metin">
  <h2 id="metin">İşaretli metin</h2>
  <p class="rapor-lejant">
    <span><span class="imi imi--hata imi--gorunur lejant-ornek">düz kalın çizgi</span> hata</span>
    <span><span class="imi imi--uyari imi--gorunur lejant-ornek">fosforlu kalem</span> uyarı</span>
    <span><span class="imi imi--bilgi imi--gorunur lejant-ornek">noktalı çizgi</span> bilgi</span>
  </p>
  <div class="isaretli-metin">{marked}</div>
</section>
<section aria-labelledby="bulgular">
  <h2 id="bulgular">Bulgular ({len(report.findings)})</h2>
  {findings_html}
</section>
{ignored_html}
</main>
<footer class="altbilgi"><p>kolaymetin {_esc(report.version)} · Kod: Apache-2.0 · Rehber ve sözlük: CC BY 4.0</p>
<p>Bu araç yardımcıdır, hakem değildir. Metni hedef okurlarla test edin.</p></footer>
</div>
</body>
</html>
"""
