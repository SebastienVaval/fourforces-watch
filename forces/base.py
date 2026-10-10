"""Generic relevance rule: which observations count for a neighborhood tile."""
from __future__ import annotations

from core.schema import Observation, haversine_km


def applies_to(o: Observation, hood: dict, city: dict) -> bool:
    """Neighborhood-tagged items match by id; area-wide items match when their zone
    list is empty or contains the tile's zone; point items match within nearby_km."""
    if o.extra.get("neighborhood"):
        return o.extra["neighborhood"] == hood["id"]
    if o.extra.get("scope") == "area":
        zones = o.extra.get("zones") or []
        return not zones or hood.get("zone") in zones
    if o.place.lat is None or o.place.lon is None:
        return False
    return haversine_km(hood["lat"], hood["lon"], o.place.lat, o.place.lon) <= city.get("nearby_km", 6)


def fact(o: Observation) -> str:
    if o.extra.get("headline"):
        return str(o.extra["headline"])
    return f"{o.measurement} at {o.place.name}: {o.value}{' ' + o.unit if o.unit else ''} ({o.status})"
