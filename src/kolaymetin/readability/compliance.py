"""Kolay Dil Uyum Skoru (0–100).

Kurala dayalı, şeffaf bir bileşik skor:

    ceza      = Σ (bulgu ağırlığı × güven)      ağırlıklar: hata=3, uyarı=1, bilgi=0,25
    normalize = ceza / max(cümle_sayısı, 1)
    skor      = round(100 × exp(−k × normalize))  k profilden gelir (kolay-dil: 0,6)
"""

from __future__ import annotations

import math
from collections import defaultdict

from kolaymetin.models import (
    CATEGORIES,
    CategoryScore,
    ComplianceScore,
    Finding,
    RuleContribution,
)

# Yalnızca cp1254 (Türkçe Windows konsolu) ile yazılabilen karakterler: "−" (U+2212) ve "Σ"
# orada UnicodeEncodeError verir.
FORMULA = (
    "skor = round(100 × exp(-k × ceza / max(cümle sayısı, 1))); "
    "ceza = bulguların toplamı (ağırlık × güven)"
)
MIN_RELIABLE_SENTENCES = 3


def _score(penalty: float, sentences: int, k: float) -> int:
    normalized = penalty / max(sentences, 1)
    return round(100 * math.exp(-k * normalized))


def compute(
    findings: list[Finding], sentence_count: int, k: float, weights: dict[str, float]
) -> ComplianceScore:
    per_rule: dict[str, RuleContribution] = {}
    per_cat_penalty: dict[str, float] = defaultdict(float)
    per_cat_count: dict[str, int] = defaultdict(int)
    total = 0.0
    for f in findings:
        p = weights.get(f.severity, 0.0) * f.confidence
        total += p
        per_cat_penalty[f.category] += p
        per_cat_count[f.category] += 1
        rc = per_rule.get(f.rule_id)
        if rc is None:
            rc = RuleContribution(
                rule_id=f.rule_id, rule_name=f.rule_name, category=f.category, count=0, penalty=0.0
            )
            per_rule[f.rule_id] = rc
        rc.count += 1
        rc.penalty = round(rc.penalty + p, 3)
    normalized = total / max(sentence_count, 1)
    reliable = sentence_count >= MIN_RELIABLE_SENTENCES
    return ComplianceScore(
        value=_score(total, sentence_count, k),
        penalty=round(total, 3),
        normalized=round(normalized, 3),
        k=k,
        sentence_count=sentence_count,
        reliable=reliable,
        note=None if reliable else "Metin çok kısa, skor güvenilir değil.",
        formula=FORMULA,
        weights=dict(weights),
        by_category=[
            CategoryScore(
                category=c,
                score=_score(per_cat_penalty[c], sentence_count, k),
                penalty=round(per_cat_penalty[c], 3),
                finding_count=per_cat_count[c],
            )
            for c in CATEGORIES
        ],
        contributions=sorted(per_rule.values(), key=lambda r: -r.penalty),
    )
