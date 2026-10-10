"""Fire: heat index (observed + forecast), NWS heat/red-flag alerts, FIRMS satellite hotspots near a tile.

Hotspot rule (city pack ``fire.hotspots``): a detection at or above ``min_confidence`` within ``alert_km``
of a neighborhood is alert, within ``watch_km`` is watch, farther away it does not count. Context for each
tile (nearest fire station, nearest cooling centers) comes from county reference layers (``fire.context``).
"""
from __future__ import annotations

from core.schema import haversine_km
from forces.base import applies_to

FORCE = "fire"
CONF_RANK = {"low": 0, "nominal": 1, "high": 2}
DEFAULT_RULE = {"watch_km": 15, "alert_km": 5, "min_confidence": "nominal"}


def _rule(city) -> dict:
    return DEFAULT_RULE | ((city.get("fire") or {}).get("hotspots") or {})


def is_hotspot(o) -> bool:
    return o.force == FORCE and o.extra.get("kind") == "hotspot" and o.place.lat is not None


def hotspot_status(o, hood, city) -> str | None:
    """Status of one hotspot for one tile, or None when it does not count (too far / low confidence)."""
    r = _rule(city)
    if CONF_RANK.get(o.extra.get("confidence"), 0) < CONF_RANK.get(r["min_confidence"], 1):
        return None
    d = haversine_km(hood["lat"], hood["lon"], o.place.lat, o.place.lon)
    return "alert" if d <= r["alert_km"] else "watch" if d <= r["watch_km"] else None


def relevant(o, hood, city) -> bool:
    if is_hotspot(o):
        return hotspot_status(o, hood, city) is not None
    return applies_to(o, hood, city)


def status_for(o, hood, city) -> str:
    return hotspot_status(o, hood, city) or o.status if is_hotspot(o) else o.status


def _nearest(lat, lon, sites, n=1):
    ranked = sorted(((haversine_km(lat, lon, s.place.lat, s.place.lon), s) for s in sites), key=lambda x: x[0])
    return [{"name": s.place.name, "km": round(d, 1), "lat": s.place.lat, "lon": s.place.lon,
             "address": (s.extra.get("properties") or {}).get("ADDRESS") or (s.extra.get("properties") or {}).get("Street")}
            for d, s in ranked[:n]]


def _layer(observations, layer_id):
    return [o for o in observations if o.extra.get("layer") == layer_id and o.place.lat is not None]


def annotate(observations, city) -> None:
    """Add the nearest fire station (straight-line km) to every hotspot, in place."""
    ctx = (city.get("fire") or {}).get("context") or {}
    stations = _layer(observations, ctx.get("stations_layer"))
    if not stations:
        return
    for o in observations:
        if is_hotspot(o):
            o.extra["nearest_station"] = _nearest(o.place.lat, o.place.lon, stations)[0]


def context(hood, observations, city) -> dict:
    """Nearest fire station and cooling centers for a tile (information, not a status)."""
    ctx = (city.get("fire") or {}).get("context") or {}
    out = {}
    stations = _layer(observations, ctx.get("stations_layer"))
    cooling = _layer(observations, ctx.get("cooling_layer"))
    if stations:
        out["nearest_station"] = _nearest(hood["lat"], hood["lon"], stations)[0]
    if cooling:
        out["cooling_centers"] = _nearest(hood["lat"], hood["lon"], cooling, int(ctx.get("cooling_count", 2)))
    hot = [o for o in observations if is_hotspot(o)]
    if hot:  # only reported when it is within the watch distance
        d, o = min(((haversine_km(hood["lat"], hood["lon"], o.place.lat, o.place.lon), o) for o in hot), key=lambda x: x[0])
        if d <= _rule(city)["watch_km"]:
            out["nearest_hotspot"] = {"km": round(d, 1), "confidence": o.extra.get("confidence"),
                                      "simulated": bool(o.extra.get("simulated"))}
    return out
