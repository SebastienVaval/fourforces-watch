"""Adapter interface.

An adapter is any module exposing:

    NAME:  str                         unique source name, e.g. "noaa_tide"
    FORCE: "water" | "air" | "land" | "fire"
    def fetch(city: dict) -> list[Observation]

Raise ``SkipAdapter("reason")`` when it cannot run (missing key, section absent
from the city pack); the app logs the reason and carries on. Observations that
apply to a whole area rather than a point set ``extra["scope"] = "area"`` and
optionally ``extra["zones"] = [...]``.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType

log = logging.getLogger("adapters")
BUILTIN = ["adapters.water", "adapters.air", "adapters.land", "adapters.fire"]


class SkipAdapter(Exception):
    """Adapter not configured / no key. Not an error."""


def discover(extra_packages: list[str] | None = None) -> list[ModuleType]:
    """Find adapter modules under adapters/<force>/ plus any extra importable packages
    (env ADAPTER_PACKAGES), so adapters kept in another repository plug in unchanged."""
    found: list[ModuleType] = []
    for pkg_name in BUILTIN + (extra_packages or []):
        try:
            pkg = importlib.import_module(pkg_name)
        except ImportError as e:
            log.warning("cannot import adapter package %s: %s", pkg_name, e)
            continue
        for info in pkgutil.iter_modules(pkg.__path__):
            if info.name.startswith("_"):
                continue
            mod = importlib.import_module(f"{pkg_name}.{info.name}")
            if hasattr(mod, "fetch") and hasattr(mod, "FORCE"):
                found.append(mod)
    return found
