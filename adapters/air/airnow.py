"""EPA AirNow current observations for the city's reporting area (www.airnowapi.org). Needs AIRNOW_API_KEY (free).

Endpoint: /aq/observation/latLong/current/ (latitude, longitude, distance in miles, API_KEY, format=application/json).
One row per pollutant (O3, PM2.5, PM10) with AQI and Category {Number, Name}. Applies to the whole area.
"""
from __future__ import annotations

import os

from adapters.air._aqi import category, status
from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place, to_utc_iso, utcnow_iso

NAME, FORCE = "airnow", "air"
API = "https://www.airnowapi.org/aq/observation/latLong/current/"
TZ = {"EST": "-05:00", "EDT": "-04:00", "CST": "-06:00", "CDT": "-05:00", "MST": "-07:00", "MDT": "-06:00",
      "PST": "-08:00", "PDT": "-07:00", "AKST": "-09:00", "AKDT": "-08:00", "HST": "-10:00"}


def _time(row) -> str:
    d, h, tz = (row.get("DateObserved") or "").strip(), row.get("HourObserved"), TZ.get(row.get("LocalTimeZone") or "")
    if not d or h is None or not tz:
        return utcnow_iso()
    return to_utc_iso(f"{d}T{int(h):02d}:00:00{tz}")


def parse(rows: list, air: dict) -> list[Observation]:
    out = []
    for row in rows or []:
        aqi = row.get("AQI")
        if aqi is None or aqi < 0:
            continue
        param = row.get("ParameterName")
        cat = (row.get("Category") or {}).get("Name") or category(aqi)
        out.append(Observation(
            force=FORCE, source=NAME,
            place=Place(id=f"airnow-{row.get('ReportingArea')}-{param}", name=f"AirNow {row.get('ReportingArea')} ({param})",
                        lat=row.get("Latitude"), lon=row.get("Longitude")),
            time=_time(row), measurement=f"AQI {param}", value=aqi, unit="AQI",
            threshold=air.get("aqi_watch", 101), status=status(aqi, air),
            extra={"scope": "area", "zones": [], "kind": "aqi_area", "network": "AirNow", "parameter": param,
                   "category": cat, "headline": f"AirNow {row.get('ReportingArea')}: {param} AQI {aqi} ({cat})",
                   "link": "https://www.airnow.gov/"},
        ))
    return out


def fetch(city: dict) -> list[Observation]:
    key = os.getenv("AIRNOW_API_KEY")
    if not key:
        raise SkipAdapter("needs AIRNOW_API_KEY (free key: https://docs.airnowapi.org/account/request/)")
    air = city.get("air") or {}
    lat, lon = city["center"]
    with client() as c:
        r = c.get(API, params={"format": "application/json", "latitude": lat, "longitude": lon,
                               "distance": (air.get("airnow") or {}).get("distance_miles", 25), "API_KEY": key})
        if r.status_code in (401, 403):
            raise SkipAdapter(f"AirNow refused AIRNOW_API_KEY ({r.status_code})")
        r.raise_for_status()
        return parse(r.json(), air)
