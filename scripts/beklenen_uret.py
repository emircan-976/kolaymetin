"""Korpus metinleri için beklenen.yaml taslağı üretir (gözden geçirmek için).

Kullanım: python scripts/beklenen_uret.py tests/corpus/KLASOR [--yaz]
Üretilen dosya elle gözden geçirilmeli; araç yalnızca başlangıç önerir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from kolaymetin import analyze

CORE = ["KD-C01", "KD-C02", "KD-C03", "KD-C05", "KD-C07", "KD-C11", "KD-K01", "KD-K02", "KD-K03",
        "KD-K07", "KD-B04", "KD-B05", "KD-B06", "KD-B07"]


def draft(folder: Path) -> dict:
    text = (folder / "metin.txt").read_text(encoding="utf-8")
    r = analyze(text, profile="kolay-dil")
    kind = folder.name.rsplit("-", 1)[-1]
    out: dict = {"profil": "kolay-dil"}
    if kind == "kolay":
        out["skor_en_az"] = 85
        out["hata_yok"] = True
    elif kind == "burokratik":
        out["skor_en_cok"] = 40
    seen: dict[str, dict] = {}
    for f in r.findings:
        if f.confidence < 1 or f.severity == "bilgi" or f.rule_id in seen:
            continue
        item = {"kural": f.rule_id, "cumle": (f.sentence_index or 0) + 1}
        if f.category == "kelime" or f.rule_id in ("KD-B04", "KD-B05", "KD-C03", "KD-C04", "KD-C11"):
            item["ifade"] = f.text
        seen[f.rule_id] = item
    out["tetiklenmeli"] = list(seen.values())[:10]
    fired = {f.rule_id for f in r.findings}
    out["tetiklenmemeli"] = [c for c in CORE if c not in fired]
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    folder = Path(sys.argv[1])
    data = draft(folder)
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
    if "--yaz" in sys.argv:
        header = "# Beklenen bulgular (cumle: 1'den başlayan cümle numarası, başlıklar dahil)\n"
        (folder / "beklenen.yaml").write_text(header + text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
