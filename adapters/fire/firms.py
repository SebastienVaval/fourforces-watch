"""NASA FIRMS satellite active-fire detections (VIIRS + MODIS) in the city's fire bbox. Needs FIRMS_MAP_KEY (free).

Each detection is a point Observation (measurement ``active_fire``, value = fire radiative power in MW).
Confidence is normalised to low / nominal / high (VIIRS letters, MODIS 0-100). The per-neighborhood
status (distance + confidence thresholds from the city pack) is decided in ``forces/fire.py``.
"""
from __future__ import annotations

import csv
import io
import os

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place

NAME, FORCE = "nasa_firms", "fire"
DEFAULT_SOURCES = ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT", "MODIS_NRT"]
CONF_RANK = {"low": 0, "nominal": 1, "high": 2}


def norm_confidence(raw) -> str:
    """VIIRS: l / n / h. MODIS: 0-100 (<30 low, 30-79 nominal, >=80 high)."""
    s = str(raw or "").strip().lower()
    if s in ("h", "high"):
        return "high"
    if s in ("n", "nominal"):
        return "nominal"
    if s in ("l", "low"):
        return "low"
    try:
        v = float(s)
    except ValueError:
        return "low"
    return "high" if v >= 80 else "nominal" if v >= 30 else "low"


def parse_csv(text: str, product: str) -> list[Observation]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
        except (KeyError, ValueError):
            continue
        t = (row.get("acq_time") or "0000").zfill(4)
        conf = norm_confidence(row.get("confidence"))
        out.append(Observation(
            force=FORCE, source=NAME,
            place=Place(id=f"firms-{product}-{lat:.4f}-{lon:.4f}-{row.get('acq_date')}-{t}",
                        name="Satellite fire detection", lat=lat, lon=lon),
            time=f"{row.get('acq_date')}T{t[:2]}:{t[2:]}:00Z", measurement="active_fire",
            value=round(float(row.get("frp") or 0), 1), unit="MW FRP", threshold="detection within watch_km",
            status="alert" if conf == "high" else "watch" if conf == "nominal" else "ok",
            extra={"confidence": conf, "confidence_raw": row.get("confidence"), "product": product,
                   "satellite": row.get("satellite"), "instrument": row.get("instrument"),
                   "daynight": row.get("daynight"), "kind": "hotspot",
                   "headline": f"Satellite fire detection ({conf} confidence, {row.get('frp') or '?'} MW)",
                   "link": f"https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@{lon:.3f},{lat:.3f},12z"},
        ))
    return out


def fetch(city: dict) -> list[Observation]:
    key = os.getenv("FIRMS_MAP_KEY")
    if not key:
        raise SkipAdapter("FIRMS_MAP_KEY not set (free key: https://firms.modaps.eosdis.nasa.gov/api/map_key/)")
    cfg = (city.get("fire") or {}).get("firms") or {}
    b = cfg.get("bbox") or city["bbox"]
    days = int(cfg.get("days", 2))
    sources = cfg.get("sources") or ([cfg["source"]] if cfg.get("source") else DEFAULT_SOURCES)
    out, errors = [], []
    with client(timeout=30) as c:
        for product in sources:
            r = c.get(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{product}/"
                      f"{b['west']},{b['south']},{b['east']},{b['north']}/{days}")
            if r.status_code != 200 or r.text.startswith("Invalid"):
                errors.append(f"{product}: {r.text[:60] if r.status_code == 200 else r.status_code}")
                continue
            out += parse_csv(r.text, product)
    if errors and not out and len(errors) == len(sources):
        raise RuntimeError("; ".join(errors)[:200])
    return out
