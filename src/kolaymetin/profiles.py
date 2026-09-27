"""Profil (kural ayarları) yükleme ve doğrulama."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from kolaymetin.models import Severity

BUILTIN_PROFILES = ("kolay-dil", "sade-dil")

_SEVERITY_ALIASES = {
    "hata": "hata",
    "error": "hata",
    "uyarı": "uyarı",
    "uyari": "uyarı",
    "warning": "uyarı",
    "bilgi": "bilgi",
    "info": "bilgi",
}


class ProfileError(ValueError):
    """Profil dosyası okunamadı ya da geçersiz."""


def normalize_severity(value: Any) -> Any:
    if value is None:
        return None
    key = str(value).strip().lower()
    if key not in _SEVERITY_ALIASES:
        raise ValueError(f"Geçersiz önem düzeyi: {value!r}. hata, uyarı ya da bilgi yazın.")
    return _SEVERITY_ALIASES[key]


class RuleConfig(BaseModel):
    enabled: bool = True
    severity: Severity | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("severity", mode="before")
    @classmethod
    def _sev(cls, v: Any) -> Any:
        return normalize_severity(v)

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)


class Profile(BaseModel):
    name: str
    title: str = ""
    description: str = ""
    extends: str | None = None
    compliance_k: float = 0.6
    weights: dict[str, float] = Field(
        default_factory=lambda: {"hata": 3.0, "uyarı": 1.0, "bilgi": 0.25}
    )
    rules: dict[str, RuleConfig] = Field(default_factory=dict)

    def rule(self, rule_id: str) -> RuleConfig:
        return self.rules.get(rule_id, RuleConfig())


def _read_builtin(name: str) -> dict[str, Any]:
    ref = resources.files("kolaymetin").joinpath("data", "profiles", f"{name}.yaml")
    data = yaml.safe_load(ref.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _read_file(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"Profil dosyası bulunamadı: {path}") from exc
    except yaml.YAMLError as exc:
        raise ProfileError(f"Profil dosyası okunamadı (YAML hatası): {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError(f"Profil dosyası bir sözlük (anahtar: değer) içermeli: {path}")
    return data


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if key == "rules" and isinstance(value, dict):
            rules = {k: dict(v or {}) for k, v in (base.get("rules") or {}).items()}
            for rid, cfg in value.items():
                cfg = dict(cfg or {})
                merged = dict(rules.get(rid, {}))
                params = dict(merged.get("params") or {})
                params.update(cfg.pop("params", None) or {})
                merged.update(cfg)
                merged["params"] = params
                rules[rid] = merged
            out["rules"] = rules
        elif key == "weights" and isinstance(value, dict):
            weights = dict(base.get("weights") or {})
            weights.update(value)
            out["weights"] = weights
        else:
            out[key] = value
    return out


def _parent_path(parent: str, base_dir: Path | None) -> str:
    """"extends: taban.yaml" önce profil dosyasının kendi klasöründe aranır, sonra çalışma
    klasöründe. Böylece /alt/klasor/ozel.yaml yanındaki taban.yaml'ı her yerden bulur."""
    if parent in BUILTIN_PROFILES or base_dir is None or Path(parent).is_absolute():
        return parent
    candidate = base_dir / parent
    return str(candidate) if candidate.is_file() or not Path(parent).is_file() else parent


def _resolve(data: dict[str, Any], depth: int = 0, base_dir: Path | None = None) -> dict[str, Any]:
    parent = data.get("extends")
    if not parent:
        return data
    if depth > 5:
        raise ProfileError("Profil zinciri çok uzun (extends döngüsü olabilir).")
    parent_ref = _parent_path(str(parent), base_dir)
    parent_dir = None if parent_ref in BUILTIN_PROFILES else Path(parent_ref).resolve().parent
    parent_data = _resolve(load_raw(parent_ref), depth + 1, parent_dir)
    merged = _merge(parent_data, {k: v for k, v in data.items() if k != "extends"})
    merged["extends"] = parent
    return merged


def load_raw(name_or_path: str) -> dict[str, Any]:
    if name_or_path in BUILTIN_PROFILES:
        return _read_builtin(name_or_path)
    return _read_file(Path(name_or_path))


def load_profile(name_or_path: str | Profile | dict[str, Any] = "kolay-dil") -> Profile:
    """Yerleşik bir profili (kolay-dil, sade-dil) ya da bir YAML dosyasını yükler."""
    if isinstance(name_or_path, Profile):
        return name_or_path
    raw = dict(name_or_path) if isinstance(name_or_path, dict) else load_raw(name_or_path)
    own_name = raw.get("name")
    base_dir = (
        Path(name_or_path).resolve().parent
        if isinstance(name_or_path, str) and name_or_path not in BUILTIN_PROFILES
        else None
    )
    data = _resolve(raw, base_dir=base_dir)
    if isinstance(name_or_path, dict):
        data["name"] = own_name or "ozel"
    else:
        data["name"] = own_name or Path(str(name_or_path)).stem
    try:
        return Profile.model_validate(data)
    except Exception as exc:
        raise ProfileError(f"Profil geçersiz: {exc}") from exc
