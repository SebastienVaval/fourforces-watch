"""Land: the tile's evacuation zone/order flag, FEMA declarations, earthquakes, NWS land alerts.

Earthquake rule (city pack ``land.earthquakes``): an event within ``alert_km`` of a neighborhood with magnitude
at or above ``alert_magnitude`` is alert; any event at or above ``min_magnitude`` within ``watch_km`` is watch;
farther away it does not count. Open shelters, bus pickups and hospitals are context only, never a status.
"""
from __future__ import annotations

from core.schema import haversine_km
from forces.base import applies_to

FORCE = "land"
DEFAULT_QUAKE = {"watch_km": 150, "alert_km": 50, "alert_magnitude": 4.5}


def _rule(city) -> dict:
    return DEFAULT_QUAKE | ((city.get("land") or {}).get("earthquakes") or {})


def is_quake(o) -> bool:
    return o.force == FORCE and o.extra.get("kind") == "earthquake" and o.place.lat is not None


def quake_status(o, hood, city) -> str | None:
    """Status of one earthquake for one tile, or None when it is too far away to count."""
    r = _rule(city)
    d = haversine_km(hood["lat"], hood["lon"], o.place.lat, o.place.lon)
    if d <= r["alert_km"] and float(o.value or 0) >= r["alert_magnitude"]:
        return "alert"
    return "watch" if d <= r["watch_km"] else None


def relevant(o, hood, city) -> bool:
    if o.source == "evac_shelters":  # open shelters are information, not a hazard
        return False
    if is_quake(o):
        return quake_status(o, hood, city) is not None
    return applies_to(o, hood, city)


def status_for(o, hood, city) -> str:
    return (quake_status(o, hood, city) or o.status) if is_quake(o) else o.status


def _nearest(lat, lon, sites, n=1):
    ranked = sorted(((haversine_km(lat, lon, s.place.lat, s.place.lon), s) for s in sites), key=lambda x: x[0])
    return [{"name": s.place.name, "km": round(d, 1), "lat": s.place.lat, "lon": s.place.lon,
             "address": s.extra.get("address") or (s.extra.get("properties") or {}).get("ADDRESS")}
            for d, s in ranked[:n]]


def context(hood, observations, city) -> dict:
    """Evacuation zone, nearest open shelter / evacuation bus pickup, open FEMA declarations (information only)."""
    out = {}
    for o in observations:
        if o.force == FORCE and o.extra.get("neighborhood") == hood["id"] and o.measurement == "hurricane_evacuation_zone":
            if not out.get("evac_zone") or o.extra.get("simulated"):
                out["evac_zone"] = {"zone": o.value, "order_flag": bool(o.extra.get("evac_order_flag")),
                                    "simulated": bool(o.extra.get("simulated"))}
    shelters = [o for o in observations if o.source == "evac_shelters" and o.place.lat is not None]
    pickups = [o for o in observations if o.extra.get("layer") == "mdc_evac_bus_pickup" and o.place.lat is not None]
    if shelters:
        out["nearest_shelter"] = _nearest(hood["lat"], hood["lon"], shelters)[0]
    if pickups:
        out["nearest_bus_pickup"] = _nearest(hood["lat"], hood["lon"], pickups)[0]
    fema = [o for o in observations if o.source == "openfema_declarations" and o.status != "ok"]
    if fema:
        out["fema_open"] = [o.extra.get("headline") for o in fema][:3]
    return out
