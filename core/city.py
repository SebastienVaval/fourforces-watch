"""City pack loader. A city pack is a YAML file in cities/, selected by the CITY env var."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=None)
def load_city(name: str | None = None) -> dict:
    name = name or os.getenv("CITY", "miami")
    path = ROOT / "cities" / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"City pack not found: {path}")
    cfg = yaml.safe_load(path.read_text())
    cfg.setdefault("id", name)
    return cfg
