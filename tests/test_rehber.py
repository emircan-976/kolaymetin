"""Rehber öz-denetimi: rehberin kendi metni de sade dille yazılmalı (Bölüm 8).

Kötü örnekler alıntı bloklarında (>) durur ve denetime girmez. Tırnak içindeki kelimeler
bir kelimeden "söz etmek" içindir (örneğin "alınacaktır"); onlar da denetime girmez.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kolaymetin import analyze
from kolaymetin.rules import all_rules

REHBER = Path(__file__).resolve().parents[1] / "docs" / "rehber"
PAGES = sorted(REHBER.glob("*.md"))


def prose(markdown: str) -> str:
    """Alıntı bloklarını, kod bloklarını, tabloları ve tırnak içi örnekleri çıkarır."""
    lines = []
    in_code = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or stripped.startswith((">", "|")):
            continue
        if re.search(r"\(\d{4}[^)]*\)\.", line):
            continue  # kaynakça girdisi (eser adları sade dil denetimine girmez)
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"`[^`\n]*`", "Kod", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", "Eser", text)  # italik eser adları
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`]", "", text)
    text = re.sub(r'"[^"\n]*"', "Örnek", text)
    return text


def test_every_rule_has_a_page() -> None:
    names = {p.stem for p in PAGES}
    for rule in all_rules():
        assert rule.id in names, f"{rule.id} için rehber sayfası yok"
    for extra in ("index", "skorlar", "kaynaklar", "katki"):
        assert extra in names


@pytest.mark.parametrize("page", [p for p in PAGES if p.stem.startswith("KD-")], ids=lambda p: p.stem)
def test_rule_page_structure(page: Path) -> None:
    text = page.read_text(encoding="utf-8")
    assert text.startswith(f"# {page.stem} ")
    for heading in ("## Ne?", "## Neden?", "## Örnekler", "## İstisnalar"):
        assert heading in text, f"{page.name}: '{heading}' bölümü yok"
    assert text.count("**Kötü:**") >= 2, f"{page.name}: en az 2 kötü örnek gerekli"
    assert text.count("**İyi:**") >= 2, f"{page.name}: en az 2 iyi örnek gerekli"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_rehber_passes_its_own_rules(page: Path) -> None:
    report = analyze(prose(page.read_text(encoding="utf-8")), profile="kolay-dil")
    problems = [
        f"{f.rule_id} {f.severity}: {f.text[:80]!r}"
        for f in report.findings
        if (f.rule_id == "KD-C01" and f.severity == "hata")
        or (f.rule_id == "KD-C03" and f.severity != "bilgi")
    ]
    assert not problems, f"{page.name}:\n" + "\n".join(problems)
