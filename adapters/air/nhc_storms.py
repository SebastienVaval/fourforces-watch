"""National Hurricane Center active storms (nhc.noaa.gov/CurrentStorms.json). No key."""
from __future__ import annotations

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place, haversine_km, to_utc_iso

NAME, FORCE = "nhc_storms", "air"
URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
CLASSES = {"TD": "Tropical Depression", "TS": "Tropical Storm", "HU": "Hurricane", "MH": "Major Hurricane",
           "STD": "Subtropical Depression", "STS": "Subtropical Storm", "PTC": "Post-tropical Cyclone",
           "PC": "Potential Tropical Cyclone"}


def fetch(city: dict) -> list[Observation]:
    air = city.get("air") or {}
    if "nhc_radius_km" not in air:
        raise SkipAdapter("no nhc settings in city pack")
    lat0, lon0 = city["center"]
    with client() as c:
        r = c.get(URL)
        r.raise_for_status()
        storms = r.json().get("activeStorms", [])
    out = []
    for s in storms:
        lat, lon = s.get("latitudeNumeric"), s.get("longitudeNumeric")
        if lat is None:
            continue
        d = round(haversine_km(lat0, lon0, lat, lon))
        status = "alert" if d <= air.get("nhc_alert_radius_km", 300) else "watch" if d <= air["nhc_radius_km"] else "ok"
        cls = CLASSES.get(s.get("classification"), s.get("classification"))
        out.append(Observation(
            force=FORCE, source=NAME, place=Place(id=f"nhc-{s['id']}", name=f"{cls} {s.get('name')}", lat=lat, lon=lon),
            time=to_utc_iso(s.get("lastUpdate")), measurement="tropical_cyclone_distance", value=d, unit="km",
            threshold=air["nhc_radius_km"], status=status,
            extra={"scope": "area", "zones": [], "intensity_kt": s.get("intensity"), "pressure_mb": s.get("pressure"),
                   "headline": f"{cls} {s.get('name')}: {s.get('intensity')} kt, {d} km from city center",
                   "link": (s.get("publicAdvisory") or {}).get("url") or "https://www.nhc.noaa.gov/"},
        ))
    return out
