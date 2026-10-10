"""PurpleAir outdoor sensors in the city bbox (api.purpleair.com). Needs PURPLEAIR_API_KEY."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from adapters.air._aqi import category, pm25_to_aqi, status
from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place

NAME, FORCE = "purpleair", "air"
API = "https://api.purpleair.com/v1/sensors"


def fetch(city: dict) -> list[Observation]:
    key = os.getenv("PURPLEAIR_API_KEY")
    if not key:
        raise SkipAdapter("PURPLEAIR_API_KEY not set (key: https://develop.purpleair.com/)")
    air, b = city.get("air") or {}, city["bbox"]
    with client() as c:
        r = c.get(API, headers={"X-API-Key": key}, params={
            "fields": "name,latitude,longitude,pm2.5_10minute,last_seen,confidence", "location_type": 0,
            "max_age": 3600, "nwlng": b["west"], "nwlat": b["north"], "selng": b["east"], "selat": b["south"]})
        r.raise_for_status()
        j = r.json()
    rows = [dict(zip(j["fields"], d)) for d in j.get("data", [])][: (air.get("purpleair") or {}).get("max_sensors", 60)]
    out = []
    for row in rows:
        pm = row.get("pm2.5_10minute")
        aqi = pm25_to_aqi(pm)
        out.append(Observation(
            force=FORCE, source=NAME,
            place=Place(id=f"purpleair-{row['sensor_index']}", name=row.get("name") or "PurpleAir sensor",
                        lat=row.get("latitude"), lon=row.get("longitude")),
            time=datetime.fromtimestamp(row.get("last_seen") or 0, timezone.utc).isoformat().replace("+00:00", "Z"),
            measurement="AQI PM2.5 (10-min, uncorrected)", value=aqi, unit="AQI",
            threshold=air.get("aqi_watch", 101), status=status(aqi, air),
            extra={"pm25_ugm3": pm, "category": category(aqi), "confidence": row.get("confidence"),
                   "link": f"https://map.purpleair.com/?select={row['sensor_index']}"},
        ))
    return out
