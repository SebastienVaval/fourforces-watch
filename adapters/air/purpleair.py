"""PurpleAir outdoor sensors in the city bbox (api.purpleair.com v1). Needs PURPLEAIR_API_KEY.

PM2.5 uses the US EPA correction (cf_1 + humidity) when both fields are present, else the uncorrected
10-minute average. AQI uses the 2024 EPA breakpoints.

The app refresh stays on ``REFRESH_SECONDS``. This adapter calls PurpleAir at most once per
``PURPLEAIR_REFRESH_SECONDS`` (default 1800, 30 minutes) and serves the last result until then.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from datetime import datetime, timezone

from adapters.air._aqi import category, epa_correct, pm25_to_aqi, status
from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place

log = logging.getLogger("purpleair")
NAME, FORCE = "purpleair", "air"
API = "https://api.purpleair.com/v1/sensors"
DEFAULT_REFRESH_S = 1800

# GET /v1/sensors base cost is 5. Averaged readings are 2 points per returned row;
# station fields are 1. sensor_index is always returned and is not requested.
# last_seen is priced with the other station fields (name, latitude, longitude, confidence).
# Source: PurpleAir's points formula and the published per-field examples. The developer
# dashboard is the live price list if a field cost changes.
ENDPOINT_BASE = 5
FIELD_COST = {
    "name": 1,             # place name
    "latitude": 1,         # map and neighborhood distance
    "longitude": 1,
    "pm2.5_10minute": 2,   # fallback when the EPA correction inputs are missing
    "pm2.5_cf_1": 2,       # EPA correction
    "humidity": 2,         # EPA correction (averaged humidity, not a single channel)
    "last_seen": 1,        # observation time
    "confidence": 1,       # drop sensors whose A/B channels disagree
}
FIELDS = ",".join(FIELD_COST)
# Round illustration for the README: sensors the bbox call returns, before max_sensors trims them.
EXAMPLE_SENSORS = 100

_lock = threading.Lock()
_cache: dict[tuple, tuple[float, str, list[Observation]]] = {}


def refresh_seconds() -> int:
    raw = os.getenv("PURPLEAIR_REFRESH_SECONDS", "").strip()
    if not raw:
        return DEFAULT_REFRESH_S
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_REFRESH_S


def points_per_call(n_rows: int) -> int:
    """Points for one bbox call that returns ``n_rows`` sensors."""
    return ENDPOINT_BASE + sum(FIELD_COST.values()) * max(0, n_rows)


def points_per_day(n_rows: int, interval_s: int | None = None) -> int:
    """Points/day if every call returns ``n_rows`` and polls wait ``interval_s`` seconds."""
    interval = DEFAULT_REFRESH_S if interval_s is None else interval_s
    if interval <= 0:
        raise ValueError("interval_s must be positive")
    return (86_400 // interval) * points_per_call(n_rows)


def _cache_key(city: dict) -> tuple:
    b = city.get("bbox") or {}
    cfg = (city.get("air") or {}).get("purpleair") or {}
    return (city.get("id"), b.get("west"), b.get("south"), b.get("east"), b.get("north"),
            cfg.get("max_sensors"), cfg.get("max_age_s"), cfg.get("min_confidence"))


def _key_tag(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def parse(j: dict, air: dict) -> list[Observation]:
    fields = j.get("fields") or []
    rows = [dict(zip(fields, d)) for d in j.get("data", [])]
    cfg = air.get("purpleair") or {}
    min_conf = cfg.get("min_confidence", 50)
    out = []
    for row in rows:
        if row.get("latitude") is None or row.get("longitude") is None:
            continue
        if row.get("confidence") is not None and row["confidence"] < min_conf:
            continue  # A/B channels disagree: likely a faulty sensor
        corrected = epa_correct(row.get("pm2.5_cf_1"), row.get("humidity"))
        pm = corrected if corrected is not None else row.get("pm2.5_10minute")
        aqi = pm25_to_aqi(pm)
        if aqi is None:
            continue
        out.append(Observation(
            force=FORCE, source=NAME,
            place=Place(id=f"purpleair-{row.get('sensor_index')}", name=row.get("name") or "PurpleAir sensor",
                        lat=row["latitude"], lon=row["longitude"]),
            time=datetime.fromtimestamp(row.get("last_seen") or 0, timezone.utc).isoformat().replace("+00:00", "Z"),
            measurement="AQI PM2.5 (EPA-corrected)" if corrected is not None else "AQI PM2.5 (10-min, uncorrected)",
            value=aqi, unit="AQI", threshold=air.get("aqi_watch", 101), status=status(aqi, air),
            extra={"kind": "aqi_sensor", "pm25_ugm3": pm, "pm25_raw_10min": row.get("pm2.5_10minute"),
                   "epa_corrected": corrected is not None, "humidity": row.get("humidity"),
                   "category": category(aqi), "confidence": row.get("confidence"), "network": "PurpleAir",
                   "link": f"https://map.purpleair.com/?select={row.get('sensor_index')}"},
        ))
    return out[: int(cfg.get("max_sensors", 60))]


def fetch(city: dict) -> list[Observation]:
    key = os.getenv("PURPLEAIR_API_KEY")
    ck = _cache_key(city)
    if not key:
        with _lock:
            _cache.pop(ck, None)
        raise SkipAdapter("needs PURPLEAIR_API_KEY (read key: https://develop.purpleair.com/)")
    tag = _key_tag(key)
    interval = refresh_seconds()
    now = time.monotonic()
    with _lock:
        hit = _cache.get(ck)
        if hit and hit[1] == tag and interval > 0 and (now - hit[0]) < interval:
            log.debug("purpleair cache hit (%ss interval)", interval)
            return list(hit[2])
    air, b = city.get("air") or {}, city["bbox"]
    with client() as c:
        r = c.get(API, headers={"X-API-Key": key}, params={
            "fields": FIELDS, "location_type": 0, "max_age": int((air.get("purpleair") or {}).get("max_age_s", 3600)),
            "nwlng": b["west"], "nwlat": b["north"], "selng": b["east"], "selat": b["south"]})
        if r.status_code in (401, 403):
            with _lock:
                _cache.pop(ck, None)
            raise SkipAdapter(f"PurpleAir refused PURPLEAIR_API_KEY ({r.status_code})")
        r.raise_for_status()
        obs = parse(r.json(), air)
    with _lock:
        _cache[ck] = (time.monotonic(), tag, obs)
    return list(obs)
