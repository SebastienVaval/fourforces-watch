"""FEMA flood zone (FIRM) for each neighborhood point, from a public county ArcGIS layer. No key.

Context only (``extra.reference``): shown on the Hazard Board water tile, never changes a status.
Zone membership changes rarely, so lookups are cached for 24 h.
"""
from __future__ import annotations

import time

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place, utcnow_iso

NAME, FORCE = "flood_zones", "water"
TTL = 24 * 3600
_CACHE: dict = {}
# Plain-language meaning of the common FIRM zones
MEANING = {"VE": "coastal high hazard (1% annual chance + waves)", "AE": "1% annual chance flood (base flood elevation set)",
           "AH": "1% annual chance shallow ponding", "AO": "1% annual chance sheet flow", "A": "1% annual chance flood",
           "X": "outside the 1% annual chance floodplain", "D": "undetermined"}


def zone_lookup(c, layer: str, lat: float, lon: float, field: str) -> dict:
    r = c.get(f"{layer}/query", params={"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
                                        "spatialRel": "esriSpatialRelIntersects", "outFields": f"{field},ELEV",
                                        "returnGeometry": "false", "f": "json"})
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"].get("message"))
    feats = [f["attributes"] for f in j.get("features", [])]
    # several polygons can touch a point: report the most hazardous
    order = ["VE", "AE", "AH", "AO", "A", "X", "D"]
    feats.sort(key=lambda a: order.index(a.get(field)) if a.get(field) in order else 99)
    return feats[0] if feats else {}


def observation(hood: dict, attrs: dict, field: str, attribution: str) -> Observation:
    z = attrs.get(field) or "none"
    return Observation(
        force=FORCE, source=NAME, place=Place(id=f"fz-{hood['id']}", name=hood["name"], lat=hood["lat"], lon=hood["lon"]),
        time=utcnow_iso(), measurement="fema_flood_zone", value=z, unit="zone", status="ok",
        extra={"reference": True, "neighborhood": hood["id"], "kind": "flood_zone", "zone": z,
               "meaning": MEANING.get(z, ""), "bfe_ft": attrs.get("ELEV") if (attrs.get("ELEV") or 0) > 0 else None,
               "attribution": attribution},
    )


def fetch(city: dict) -> list[Observation]:
    cfg = (city.get("water") or {}).get("flood_zones")
    if not cfg:
        raise SkipAdapter("no water.flood_zones layer in city pack")
    field = cfg.get("field", "FZONE")
    attribution = (city.get("open_data") or {}).get("attribution", "")
    out = []
    with client() as c:
        for h in city.get("neighborhoods", []):
            key = (cfg["layer"], h["id"])
            if key not in _CACHE or time.time() - _CACHE[key][0] > TTL:
                _CACHE[key] = (time.time(), zone_lookup(c, cfg["layer"], h["lat"], h["lon"], field))
            out.append(observation(h, _CACHE[key][1], field, attribution))
    return out
