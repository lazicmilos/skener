"""Učitavanje pragova iz TOML-a (§11.2). Čita disk, ništa drugo ne radi.

`skener.toml` iz repoa je podrazumevana konfiguracija. `--config` se **spaja
preko** nje, pa parcijalna korisnička konfiguracija ne gubi ostale pragove.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from skener.models import CATEGORIES, INDUSTRIES

CONFIG_NAME = "skener.toml"


class ConfigError(Exception):
    """Konfiguracija je korisnički ulaz — puca glasno i imenuje ključ."""


def default_config_path() -> Path:
    """Prvo radni direktorijum, pa koren repoa pored paketa."""
    for candidate in (Path.cwd() / CONFIG_NAME, Path(__file__).resolve().parent.parent / CONFIG_NAME):
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"{CONFIG_NAME} nije nađen ni u {Path.cwd()} ni pored paketa. "
        f"Pokreni alat iz korena repoa ili prosledi --config PUTANJA."
    )


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = _read(default_config_path())
    if path is not None:
        user_path = Path(path)
        if not user_path.is_file():
            raise ConfigError(f"konfiguracija ne postoji: {user_path}")
        if user_path.resolve() != default_config_path().resolve():
            _merge(cfg, _read(user_path))
    _validate(cfg)
    return cfg


def get(cfg: dict[str, Any], dotted: str) -> Any:
    """`get(cfg, "thresholds.perf.image_ratio")` — puca ako ključ ne postoji."""
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(f"nedostaje ključ u konfiguraciji: {dotted}")
        node = node[part]
    return node


def multiplier(cfg: dict[str, Any], industry: str, category: str) -> float:
    """Množilac po delatnosti (§9.2); nepoznata delatnost pada na `ostalo`."""
    table = cfg["industry_multipliers"]
    return float(table.get(industry, table["ostalo"])[category])


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: neispravan TOML — {exc}") from exc


def _merge(base: dict[str, Any], over: dict[str, Any]) -> None:
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def _validate(cfg: dict[str, Any]) -> None:
    for severity in ("critical", "high", "medium", "low"):
        if severity not in cfg.get("severity_points", {}):
            raise ConfigError(f"severity_points.{severity} nedostaje")
    table = cfg.get("industry_multipliers", {})
    for industry in INDUSTRIES:
        if industry not in table:
            raise ConfigError(f"industry_multipliers.{industry} nedostaje")
        for category in CATEGORIES:
            if category not in table[industry]:
                raise ConfigError(f"industry_multipliers.{industry}.{category} nedostaje")
