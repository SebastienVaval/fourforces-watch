"""EPA AirNow current observations (www.airnowapi.org). Needs AIRNOW_API_KEY (free)."""
from __future__ import annotations

import os

from adapters.air._aqi import status
from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place, utcnow_iso

NAME, FORCE = "airnow", "air"
API = "https://www.airnowapi.org/aq/observation/latLong/current/"


def fetch(city: dict) -> list[Observation]:
    key = os.getenv("AIRNOW_API_KEY")
    if not key:
        raise SkipAdapter("AIRNOW_API_KEY not set (free key: https://docs.airnowapi.org/account/request/)")
    air = city.get("air") or {}
    lat, lon = city["center"]
    with client() as c:
        r = c.get(API, params={"format": "application/json", "latitude": lat, "longitude": lon,
                               "distance": (air.get("airnow") or {}).get("distance_miles", 25), "API_KEY": key})
        r.raise_for_status()
        rows = r.json()
    out = []
    for row in rows:
        aqi = row.get("AQI")
        out.append(Observation(
            force=FORCE, source=NAME,
            place=Place(id=f"airnow-{row.get('ReportingArea')}-{row.get('ParameterName')}",
                        name=f"{row.get('ReportingArea')} ({row.get('ParameterName')})",
                        lat=row.get("Latitude"), lon=row.get("Longitude")),
            time=utcnow_iso(), measurement=f"AQI {row.get('ParameterName')}", value=aqi, unit="AQI",
            threshold=air.get("aqi_watch", 101), status=status(aqi, air),
            extra={"scope": "area", "category": (row.get("Category") or {}).get("Name"),
                   "observed_local": f"{(row.get('DateObserved') or '').strip()} {row.get('HourObserved')}:00 {row.get('LocalTimeZone')}",
                   "link": "https://www.airnow.gov/"},
        ))
    return out
