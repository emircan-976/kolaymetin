from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="session", autouse=True)
def _warm_up() -> None:
    """Morfolojik çözümleyiciyi ve sözlüğü bir kez yükle."""
    from kolaymetin.lexicon import load_lexicon
    from kolaymetin.text import morphology

    morphology.warm_up()
    load_lexicon()


def rule_hits(text: str, rule_id: str, profile: str = "kolay-dil") -> list:
    from kolaymetin import analyze

    return [f for f in analyze(text, profile=profile).findings if f.rule_id == rule_id]
