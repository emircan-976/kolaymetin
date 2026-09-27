"""Görsel dil denetimi (Bölüm 9.4.11): yasak listesindeki hiçbir öğe olmamalı."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import kontrast_denetle
from kolaymetin import analyze

STATIC = Path(__file__).resolve().parents[1] / "src" / "kolaymetin" / "web" / "static"
CSS_FILES = sorted(STATIC.glob("*.css"))
HTML_FILES = sorted(STATIC.glob("*.html"))
JS_FILES = sorted(STATIC.glob("*.js"))
ALL = CSS_FILES + HTML_FILES + JS_FILES

ALLOWED_FONTS = {"atkinson hyperlegible next", "atkinson hyperlegible mono", "inherit",
                 "var(--f-govde)", "var(--f-mono)"}
GENERIC_FALLBACKS = {"sans-serif", "monospace"}


def _css_texts() -> list[tuple[Path, str]]:
    out = [(p, p.read_text(encoding="utf-8")) for p in CSS_FILES]
    for p in HTML_FILES:
        html = p.read_text(encoding="utf-8")
        for block in re.findall(r"<style[^>]*>(.*?)</style>", html, re.S):
            out.append((p, block))
        for attr in re.findall(r'style="([^"]*)"', html):
            out.append((p, attr))
    return out


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_files_exist() -> None:
    names = {p.name for p in ALL}
    assert {"style.css", "index.html", "app.js", "rehber.html", "stil-rehberi.html"} <= names


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_no_gradients(path: Path) -> None:
    assert "gradient" not in path.read_text(encoding="utf-8").lower()


def test_no_border_radius_above_zero() -> None:
    for path, css in _css_texts():
        for value in re.findall(r"border-radius\s*:\s*([^;}\"]+)", _strip_comments(css)):
            assert re.fullmatch(r"\s*0(px)?\s*(!important)?\s*", value), f"{path.name}: border-radius {value}"


def test_no_blurred_shadows_or_filters() -> None:
    for path, css in _css_texts():
        css = _strip_comments(css)
        assert "backdrop-filter" not in css, path.name
        assert not re.search(r"filter\s*:\s*[^;]*blur", css), path.name
        for value in re.findall(r"box-shadow\s*:\s*([^;}\"]+)", css):
            for shadow in value.split(","):
                parts = [p for p in shadow.replace("inset", "").split() if not p.startswith("var(")]
                lengths = [p for p in parts if re.fullmatch(r"-?\d+(\.\d+)?(px)?", p)]
                blur = lengths[2] if len(lengths) >= 3 else "0"
                assert float(re.sub(r"px$", "", blur)) == 0, f"{path.name}: bulanık gölge {value}"


def test_raw_hex_only_inside_root() -> None:
    for path, css in _css_texts():
        css = _strip_comments(css)
        # :root bloklarını (media içindekiler dahil) çıkar
        without_root = re.sub(r":root[^{]*\{[^}]*\}", "", css)
        found = re.findall(r"(?<![\w&])#[0-9a-fA-F]{3,8}\b", without_root)
        assert not found, f"{path.name}: :root dışında ham renk {found}"


def test_js_uses_no_raw_colors() -> None:
    for path in JS_FILES:
        js = path.read_text(encoding="utf-8")
        assert not re.search(r"['\"]#[0-9a-fA-F]{3,8}['\"]", js), path.name
        assert "rgb(" not in js and "hsl(" not in js


def test_only_allowed_fonts() -> None:
    for path, css in _css_texts():
        for value in re.findall(r"font-family\s*:\s*([^;}]+)", _strip_comments(css)):
            families = [f.strip().strip("\"'").lower() for f in value.split(",")]
            assert families[0] in ALLOWED_FONTS, f"{path.name}: birincil yazı tipi {families[0]}"
            for fam in families[1:]:
                assert fam in ALLOWED_FONTS | GENERIC_FALLBACKS, f"{path.name}: {fam}"
    style = (STATIC / "style.css").read_text(encoding="utf-8")
    for banned in ("Inter", "Roboto", "Poppins", "Montserrat", "system-ui", "-apple-system", "Segoe UI"):
        assert banned not in style


def _is_external(url: str) -> bool:
    return url.startswith(("http://", "https://", "//"))


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_no_external_resources(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for url in re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", text):
        assert not _is_external(url), f"{path.name}: dış kaynak {url}"
    for url in re.findall(r"url\(\s*['\"]?([^'\")]+)", text):
        assert not _is_external(url), f"{path.name}: dış kaynak {url}"
    for url in re.findall(r"@import\s+['\"]?([^'\";]+)", text):
        assert not _is_external(url), f"{path.name}: dış içe aktarma {url}"
    if path.suffix == ".js":
        for url in re.findall(r"fetch\(\s*['\"]([^'\"]+)", text):
            assert url.startswith("/"), f"{path.name}: dış istek {url}"


def test_svg_namespaces_are_the_only_urls_in_icons() -> None:
    for svg in (STATIC / "ikon").glob("*.svg"):
        text = svg.read_text(encoding="utf-8")
        urls = re.findall(r"https?://[^\"' >]+", text)
        assert set(urls) <= {"http://www.w3.org/2000/svg"}, svg.name
        assert re.findall(r"<(\w+)", text) and set(re.findall(r"<(\w+)", text)) <= {"svg", "title", "rect"}


def test_no_icon_libraries_or_emoji() -> None:
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
    for path in ALL:
        text = path.read_text(encoding="utf-8")
        for lib in ("font-awesome", "fontawesome", "heroicons", "lucide", "material-icons", "bootstrap", "tailwind"):
            assert lib not in text.lower(), f"{path.name}: {lib}"
        assert not emoji.search(text), f"{path.name}: emoji"


def test_dark_theme_blocks_match() -> None:
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    media = re.search(r'@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)\s*\{([^}]*)\}', css)
    manual = re.search(r':root\[data-theme="dark"\]\s*\{([^}]*)\}', css)
    assert media and manual
    assert media.group(1).split() == manual.group(1).split()


def test_reduced_motion_and_print() -> None:
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media print" in css and "18mm" in css
    assert "--kagit" in css and "--sari" in css


def test_dither_not_behind_text() -> None:
    """Dither yalnızca metin içermeyen öğelerde (boş span/div) kullanılır."""
    for path in HTML_FILES:
        html = path.read_text(encoding="utf-8")
        for m in re.finditer(r'<(span|div)[^>]*class="[^"]*(dither|cubuk__dolgu)[^"]*"[^>]*>(.*?)</\1>', html, re.S):
            assert not re.sub(r"<[^>]+>", "", m.group(3)).strip(), f"{path.name}: dither içinde metin"


def test_contrast_script_passes() -> None:
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert kontrast_denetle.check(css) == []
    assert len(kontrast_denetle.report(css)) == 2 * len(kontrast_denetle.PAIRS)


def test_contrast_script_detects_failure() -> None:
    css = (STATIC / "style.css").read_text(encoding="utf-8").replace("--murekkep-soluk: #55504A", "--murekkep-soluk: #B0A99F", 1)
    assert kontrast_denetle.check(css)
    assert kontrast_denetle.contrast("#000000", "#FFFFFF") == pytest.approx(21.0)


def test_report_html_follows_style() -> None:
    html = analyze("Başvurular alınacaktır. Müracaatınızı ivedilikle yapın.").to_html()
    assert "gradient" not in html.lower() and "backdrop-filter" not in html


def test_style_guide_shows_every_component() -> None:
    guide = (STATIC / "stil-rehberi.html").read_text(encoding="utf-8")
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r'class="([^"]+)"', index)) | set(re.findall(r'"([a-z-]+(?:__[a-z-]+)?(?:--[a-z-]+)?)"', app_js))
    used_classes = {c for group in used for c in group.split()}
    component_roots = {"dugme", "not-kagidi", "imi", "kenar-isaret", "cubuk", "skor", "sekme", "onem",
                       "kimlik", "dither", "tarama", "cumle-cubugu", "secim", "kutu"}
    for root in component_roots:
        if any(c == root or c.startswith(root + "--") or c.startswith(root + "__") for c in used_classes):
            assert f'class="{root}' in guide or f" {root}" in guide or f'"{root} ' in guide, root
