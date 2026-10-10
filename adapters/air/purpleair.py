"""PurpleAir outdoor sensors in the city bbox (api.purpleair.com v1). Needs PURPLEAIR_API_KEY.

PM2.5 uses the US EPA correction (cf_1 + humidity) when both fields are present, else the uncorrected
10-minute average. AQI uses the 2024 EPA breakpoints.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from adapters.air._aqi import category, epa_correct, pm25_to_aqi, status
from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place

NAME, FORCE = "purpleair", "air"
API = "https://api.purpleair.com/v1/sensors"
FIELDS = "name,latitude,longitude,pm2.5_10minute,pm2.5_cf_1,humidity,last_seen,confidence"


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
    if not key:
        raise SkipAdapter("needs PURPLEAIR_API_KEY (read key: https://develop.purpleair.com/)")
    air, b = city.get("air") or {}, city["bbox"]
    with client() as c:
        r = c.get(API, headers={"X-API-Key": key}, params={
            "fields": FIELDS, "location_type": 0, "max_age": int((air.get("purpleair") or {}).get("max_age_s", 3600)),
            "nwlng": b["west"], "nwlat": b["north"], "selng": b["east"], "selat": b["south"]})
        if r.status_code in (401, 403):
            raise SkipAdapter(f"PurpleAir refused PURPLEAIR_API_KEY ({r.status_code})")
        r.raise_for_status()
        return parse(r.json(), air)
