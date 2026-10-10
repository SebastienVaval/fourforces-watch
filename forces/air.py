"""Air: AQI (AirNow area-wide, PurpleAir sensors near a tile), NHC storms, NWS wind/tropical/air-quality alerts.

AQI rule (city pack ``air``): the tile AQI is the median, across monitors/sensors within ``sensor_radius_km``,
of each one's worst pollutant (``kind: aqi_sensor``: AirNow monitors, PurpleAir, demo). With none near, the
area AQI applies: the worst current official AirNow reading in the city (or a legacy ``aqi_area`` row). Watch at
``aqi_watch`` (101, Unhealthy for Sensitive Groups), alert at ``aqi_alert`` (151, Unhealthy).
Storms and NWS alerts keep their own status.
"""
from __future__ import annotations

import statistics

from adapters.air._aqi import category, status
from core.schema import haversine_km
from forces.base import applies_to

FORCE = "air"
_TILE: dict = {}   # (city id, hood id) -> tile AQI summary, rebuilt by annotate() on every board


def _radius(city) -> float:
    return float((city.get("air") or {}).get("sensor_radius_km", 5))


def is_sensor(o) -> bool:
    return o.force == FORCE and o.extra.get("kind") == "aqi_sensor" and o.place.lat is not None


def is_area_aqi(o) -> bool:
    return o.force == FORCE and o.extra.get("kind") == "aqi_area"


def _is_official(o) -> bool:
    return is_area_aqi(o) or (is_sensor(o) and o.extra.get("network") == "AirNow")


def tile_aqi(hood, observations, city) -> dict | None:
    """AQI summary for one tile: sensor median within radius, else worst AirNow pollutant."""
    air = city.get("air") or {}
    near = [o for o in observations if is_sensor(o) and o.value is not None
            and haversine_km(hood["lat"], hood["lon"], o.place.lat, o.place.lon) <= _radius(city)]
    if near:
        per_site: dict = {}  # worst pollutant per monitor, then median across monitors
        for o in near:
            k = o.extra.get("station_id") or o.place.id
            per_site[k] = max(per_site.get(k, o.value), o.value)
        aqi = round(statistics.median(per_site.values()))
        n = len(per_site)
        nets = sorted({o.extra.get("network", o.source) for o in near})
        sim = any(o.extra.get("simulated") for o in near)
        return {"aqi": aqi, "category": category(aqi), "status": status(aqi, air), "n": n,
                "source": f"median of {n} {'/'.join(nets)} sensor{'s' if n > 1 else ''} "
                          f"within {_radius(city):g} km", "simulated": sim}
    area = [o for o in observations if _is_official(o) and o.value is not None]
    if area:
        o = max(area, key=lambda x: x.value)
        where = o.extra.get("site") or "reporting area"
        return {"aqi": o.value, "category": category(o.value), "status": status(o.value, air), "n": 1,
                "source": f"AirNow area, worst monitor: {where} ({o.extra.get('parameter')})",
                "simulated": bool(o.extra.get("simulated"))}
    return None


def annotate(observations, city) -> None:
    _TILE.clear()
    for hood in city.get("neighborhoods", []):
        _TILE[(city.get("id"), hood["id"])] = tile_aqi(hood, observations, city)


def relevant(o, hood, city) -> bool:
    if is_sensor(o) and haversine_km(hood["lat"], hood["lon"], o.place.lat, o.place.lon) <= _radius(city):
        return True
    if _is_official(o):  # official AirNow readings count city-wide only when no sensor is near the tile
        t = _TILE.get((city.get("id"), hood["id"]))
        return bool(t) and t["source"].startswith("AirNow area")
    if is_sensor(o):
        return False
    return applies_to(o, hood, city)


def status_for(o, hood, city) -> str:
    if is_sensor(o) or is_area_aqi(o):
        t = _TILE.get((city.get("id"), hood["id"]))
        return t["status"] if t else "unknown"
    return o.status


def context(hood, observations, city) -> dict:
    out = {}
    t = _TILE.get((city.get("id"), hood["id"]))
    if t:
        out["aqi"] = t
    storms = [o for o in observations if o.source == "nhc_storms" and o.place.lat is not None]
    if storms:
        d, s = min(((haversine_km(hood["lat"], hood["lon"], s.place.lat, s.place.lon), s) for s in storms),
                   key=lambda x: x[0])
        out["nearest_storm"] = {"name": s.place.name, "km": round(d), "status": s.status,
                                "intensity_kt": s.extra.get("intensity_kt")}
    return out
