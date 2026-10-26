"""Water: Grok camera checks + USGS gauges nearby, tide gauge for coastal zones, NWS flood/coastal/surge alerts.

Status rule: cameras (water on road: alert >= 0.6 confidence, else watch), USGS gauges within ``nearby_km``
(site thresholds or rapid rise), the tide gauge only for ``coastal_zones`` (watch / minor flood thresholds),
NWS flood alerts for the tile's zone. FEMA flood zones are context (``extra.reference``), never a status.
"""
from __future__ import annotations

from core.schema import haversine_km
from forces.base import applies_to

FORCE = "water"


def relevant(o, hood, city) -> bool:
    if o.extra.get("coastal_only"):
        return hood.get("zone") in set(city.get("coastal_zones") or [])
    return applies_to(o, hood, city)


def _near(hood, items, radius):
    ranked = sorted(((haversine_km(hood["lat"], hood["lon"], o.place.lat, o.place.lon), o) for o in items
                     if o.place.lat is not None), key=lambda x: x[0])
    return [(d, o) for d, o in ranked if d <= radius]


def context(hood, observations, city) -> dict:
    """Water facts for a tile: flood zone, tide now + next high, nearest camera verdict, nearest canal gauge."""
    ctx_cfg = (city.get("water") or {}).get("context") or {}
    out: dict = {}
    fz = next((o for o in observations if o.source == "flood_zones" and o.extra.get("neighborhood") == hood["id"]), None)
    if fz:
        out["flood_zone"] = {"zone": fz.extra["zone"], "meaning": fz.extra.get("meaning"), "bfe_ft": fz.extra.get("bfe_ft")}
    tide = next((o for o in observations if o.source == "noaa_tide"), None)
    if tide:
        nh = tide.extra.get("next_high") or {}
        out["tide"] = {"ft": tide.value, "unit": tide.unit, "status": tide.status, "trend": tide.extra.get("trend"),
                       "anomaly_ft": tide.extra.get("anomaly_ft"), "next_high": nh or None,
                       "applies": hood.get("zone") in set(city.get("coastal_zones") or [])}
    cams = [o for o in observations if o.source == "fl511_cameras"]
    near = _near(hood, cams, float(ctx_cfg.get("camera_radius_km", 3)))
    if near:
        wet = [(d, o) for d, o in near if o.status in ("watch", "alert")]
        checked = [(d, o) for d, o in near if o.status != "unknown"]
        d, o = (wet or checked or near)[0]
        out["camera"] = {"name": o.place.name, "km": round(d, 1), "status": o.status, "id": o.place.id,
                         "verdict": {"alert": "water on road", "watch": "possible water", "ok": "dry"}.get(o.status, "not checked"),
                         "simulated": bool(o.extra.get("simulated")), "n_nearby": len(near), "n_wet": len(wet)}
    gauges = [o for o in observations if o.source == "usgs_gauges"]
    g = _near(hood, gauges, float(ctx_cfg.get("gauge_radius_km", 10)))
    if g:
        d, o = g[0]
        out["gauge"] = {"name": o.place.name, "km": round(d, 1), "ft": o.value, "rise_3h_ft": o.extra.get("rise_3h_ft"),
                        "status": o.status}
        if o.extra.get("stale"):
            out["gauge"]["stale"] = True
    return out
