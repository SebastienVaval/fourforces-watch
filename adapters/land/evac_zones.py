"""Hurricane evacuation zones / order flags / open shelters from public county ArcGIS layers. No key.

Zone membership is information (status ok). An order flag is reported as
'watch - confirm with official channels' unless the city pack sets trust_orders.
"""
from __future__ import annotations

import time

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place, utcnow_iso

NAME, FORCE = "evac_zones", "land"
_ZONES: dict = {}
ZONE_TTL = 24 * 3600


def _point(c, layer, lat, lon, fields):
    r = c.get(f"{layer}/query", params={"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
                                        "spatialRel": "esriSpatialRelIntersects", "outFields": fields,
                                        "returnGeometry": "false", "f": "json"})
    r.raise_for_status()
    return [f["attributes"] for f in r.json().get("features", [])]


def fetch(city: dict) -> list[Observation]:
    cfg = (city.get("land") or {}).get("evac_zones")
    if not cfg:
        raise SkipAdapter("no evac_zones layers in city pack")
    out, now = [], utcnow_iso()
    with client() as c:
        for n in city.get("neighborhoods", []):
            key = (cfg["zones_layer"], n["id"])
            if key not in _ZONES or time.time() - _ZONES[key][0] > ZONE_TTL:
                attrs = _point(c, cfg["zones_layer"], n["lat"], n["lon"], "ZONEID,CATEGORY")
                _ZONES[key] = (time.time(), (attrs[0] if attrs else {}).get("ZONEID"))
            zone = _ZONES[key][1]
            ordered = False
            if cfg.get("orders_layer"):
                ordered = any((o.get("EVACORDER") or "").upper() == "Y"
                              for o in _point(c, cfg["orders_layer"], n["lat"], n["lon"], "ZONEID,EVACORDER"))
            status = ("alert" if cfg.get("trust_orders") else "watch") if ordered else "ok"
            out.append(Observation(
                force=FORCE, source=NAME, place=Place(id=f"evac-{n['id']}", name=n["name"], lat=n["lat"], lon=n["lon"]),
                time=now, measurement="hurricane_evacuation_zone", value=zone or "none", unit="zone",
                threshold="evacuation order in effect", status=status,
                extra={"neighborhood": n["id"], "evac_order_flag": ordered,
                       "headline": (f"County layer flags an evacuation order for zone {zone} - confirm with official channels"
                                    if ordered else f"Evacuation zone {zone or 'none'}: no order flagged"),
                       "link": cfg.get("info_url")},
            ))
        if cfg.get("shelters_layer"):
            r = c.get(f"{cfg['shelters_layer']}/query", params={
                "where": "1=1", "outFields": "shelter_name,address,shelter_status,petfriendly,capacity,occupancy",
                "outSR": 4326, "f": "json"})
            if r.status_code == 200:
                for f in r.json().get("features", []):
                    a, g = f["attributes"], f.get("geometry") or {}
                    out.append(Observation(
                        force=FORCE, source="evac_shelters",
                        place=Place(id=f"shelter-{a.get('shelter_name')}", name=a.get("shelter_name") or "Shelter",
                                    lat=g.get("y"), lon=g.get("x")),
                        time=now, measurement="shelter_open", value=a.get("shelter_status"), status="ok",
                        extra={"address": a.get("address"), "pet_friendly": a.get("petfriendly"),
                               "capacity": a.get("capacity"), "occupancy": a.get("occupancy")},
                    ))
    return out
