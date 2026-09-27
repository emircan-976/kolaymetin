"""Korpus testleri: her metin için beklenen.yaml dosyasındaki beklentiler."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kolaymetin import analyze

CORPUS = Path(__file__).parent / "corpus"
CASES = sorted(p for p in CORPUS.iterdir() if (p / "metin.txt").is_file())


def test_corpus_size() -> None:
    assert len(CASES) >= 15
    for kind in ("burokratik", "sade", "kolay"):
        assert sum(1 for c in CASES if c.name.endswith(kind)) >= 5


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_corpus_expectations(case: Path) -> None:
    text = (case / "metin.txt").read_text(encoding="utf-8")
    exp = yaml.safe_load((case / "beklenen.yaml").read_text(encoding="utf-8"))
    report = analyze(text, profile=exp.get("profil", "kolay-dil"))
    score = report.scores.compliance.value
    if "skor_en_az" in exp:
        assert score >= exp["skor_en_az"], f"skor {score} < {exp['skor_en_az']}"
    if "skor_en_cok" in exp:
        assert score <= exp["skor_en_cok"], f"skor {score} > {exp['skor_en_cok']}"
    if exp.get("hata_yok"):
        errors = [f"{f.rule_id}: {f.text}" for f in report.findings if f.severity == "hata"]
        assert not errors, errors
    for item in exp.get("tetiklenmeli", []):
        matches = [
            f for f in report.findings
            if f.rule_id == item["kural"]
            and ("cumle" not in item or f.sentence_index == item["cumle"] - 1)
            and ("ifade" not in item or item["ifade"] in f.text)
        ]
        assert matches, f"beklenen bulgu yok: {item}"
    fired = {f.rule_id for f in report.findings}
    for rule_id in exp.get("tetiklenmemeli", []):
        assert rule_id not in fired, f"{rule_id} tetiklenmemeliydi"


@pytest.mark.parametrize("topic", sorted({c.name.rsplit("-", 1)[0] for c in CASES}))
def test_versions_are_ordered(topic: str) -> None:
    """Aynı içeriğin Kolay Dil hâli, Sade Dil hâlinden; o da bürokratik hâlden iyi olmalı."""
    scores = {}
    for kind in ("burokratik", "sade", "kolay"):
        text = (CORPUS / f"{topic}-{kind}" / "metin.txt").read_text(encoding="utf-8")
        scores[kind] = analyze(text).scores.compliance.value
    assert scores["burokratik"] <= scores["sade"] <= scores["kolay"], scores
