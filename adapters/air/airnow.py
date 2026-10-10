"""EPA AirNow hourly AQI per monitor in the city bbox (www.airnowapi.org /aq/data/). Needs AIRNOW_API_KEY (free).

The older /aq/observation/latLong/current/ and zipCode/current services were retired on Oct 1, 2026 (they answer
HTTP 200 with a WebServiceError body). This adapter queries /aq/data/ for the last few hours (UTC,
YYYY-MM-DDTHH), keeps the latest hour per monitor + pollutant, and emits one point observation each.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from adapters.air._aqi import category, status
from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place, to_utc_iso

NAME, FORCE = "airnow", "air"
API = "https://www.airnowapi.org/aq/data/"


def window(now: datetime | None = None, hours: int = 3) -> tuple[str, str]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H"), now.strftime("%Y-%m-%dT%H")


def service_error(j) -> str | None:
    """AirNow reports errors as HTTP 200 + {"WebServiceError": [{"Message": ...}]}."""
    if isinstance(j, dict) and j.get("WebServiceError"):
        return "; ".join(str(e.get("Message", e)) for e in j["WebServiceError"])[:200]
    return None


def parse(rows: list, air: dict) -> list[Observation]:
    latest: dict = {}
    for row in rows or []:
        aqi = row.get("AQI")
        if aqi is None or aqi < 0 or row.get("Latitude") is None:
            continue
        station = row.get("FullAQSCode") or row.get("IntlAQSCode") or f"{row['Latitude']:.4f},{row['Longitude']:.4f}"
        key = (station, row.get("Parameter"))
        if key not in latest or (row.get("UTC") or "") > (latest[key].get("UTC") or ""):
            latest[key] = row | {"_station": station}
    out = []
    for (station, param), row in sorted(latest.items()):
        aqi, site = row["AQI"], row.get("SiteName") or station
        out.append(Observation(
            force=FORCE, source=NAME,
            place=Place(id=f"airnow-{station}-{param}", name=f"AirNow {site} ({param})",
                        lat=row["Latitude"], lon=row["Longitude"]),
            time=to_utc_iso(f"{row.get('UTC')}:00Z") if row.get("UTC") else to_utc_iso(None),
            measurement=f"AQI {param}", value=aqi, unit="AQI", threshold=air.get("aqi_watch", 101),
            status=status(aqi, air),
            extra={"kind": "aqi_sensor", "network": "AirNow", "official": True, "station_id": station,
                   "site": site, "parameter": param, "category": category(aqi), "category_number": row.get("Category"),
                   "agency": row.get("AgencyName"), "headline": f"AirNow {site}: {param} AQI {aqi} ({category(aqi)})",
                   "link": "https://www.airnow.gov/"},
        ))
    return out


def fetch(city: dict) -> list[Observation]:
    key = os.getenv("AIRNOW_API_KEY")
    if not key:
        raise SkipAdapter("needs AIRNOW_API_KEY (free key: https://docs.airnowapi.org/account/request/)")
    air = city.get("air") or {}
    cfg = air.get("airnow") or {}
    b = cfg.get("bbox") or city["bbox"]
    start, end = window(hours=int(cfg.get("hours", 3)))
    with client() as c:
        r = c.get(API, params={"startDate": start, "endDate": end, "parameters": cfg.get("parameters", "PM25,OZONE,PM10"),
                               "BBOX": f"{b['west']},{b['south']},{b['east']},{b['north']}", "dataType": "A",
                               "format": "application/json", "verbose": 1, "monitorType": 0,
                               "includerawconcentrations": 0, "API_KEY": key})
        if r.status_code in (401, 403):
            raise SkipAdapter(f"AirNow refused AIRNOW_API_KEY ({r.status_code})")
        r.raise_for_status()
        j = r.json()
    err = service_error(j)
    if err:
        if "key" in err.lower():
            raise SkipAdapter(f"AirNow refused AIRNOW_API_KEY: {err}")
        raise RuntimeError(f"AirNow WebServiceError: {err}")
    return parse(j, air)
