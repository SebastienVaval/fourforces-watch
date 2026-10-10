"""FL511 (Florida DOT) traffic cameras via the public ArcGIS FeatureServer. No key.

One observation per camera with status "unknown"; the app's detection step
(detect/grok.py) then sets water_on_road + status. Snapshot images are only
hot-linked by the browser and fetched transiently in memory for classification;
they are never stored or redistributed.
"""
from __future__ import annotations

from datetime import datetime

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place, to_utc_iso

NAME, FORCE = "fl511_cameras", "water"
URL = "https://services.arcgis.com/3wFbqsFPLeKqOlIK/arcgis/rest/services/FL511_Traffic_Cameras/FeatureServer/0/query"


def _ts(s: str | None) -> str | None:
    try:  # "07/20/2026 3:13:42 PM" (listing time, not snapshot time)
        return datetime.strptime(s, "%m/%d/%Y %I:%M:%S %p").isoformat() if s else None
    except ValueError:
        return s


def fetch(city: dict) -> list[Observation]:
    cam = (city.get("water") or {}).get("cameras")
    if not cam or cam.get("source") != "fl511":
        raise SkipAdapter("no fl511 camera source in city pack")
    b = city["bbox"]
    counties = ",".join(f"'{c}'" for c in cam.get("counties", []))
    params = {
        "where": f"COUNTY IN ({counties})" if counties else "1=1",
        "geometry": f"{b['west']},{b['south']},{b['east']},{b['north']}",
        "geometryType": "esriGeometryEnvelope", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
        "outFields": "ID,DESCRIPT,COUNTY,HIGHWAY,DIRECTION,LATITUDE,LONGITUDE,TIMESTAMP,IMAGE",
        "returnGeometry": "false", "resultRecordCount": 2000, "f": "json",
    }
    with client() as c:
        r = c.get(URL, params=params)
        r.raise_for_status()
        feats = r.json().get("features", [])
    out = []
    for f in feats:
        a = f["attributes"]
        if not a.get("IMAGE") or a.get("LATITUDE") is None:
            continue
        out.append(Observation(
            force=FORCE, source=NAME,
            place=Place(id=f"fl511-{a['ID']}", name=a.get("DESCRIPT") or a["ID"], lat=a["LATITUDE"], lon=a["LONGITUDE"]),
            time=to_utc_iso(None), measurement="water_on_road", value=None, unit="bool",
            threshold="water visible on road surface", status="unknown",
            extra={"image_url": a["IMAGE"], "highway": a.get("HIGHWAY"), "direction": a.get("DIRECTION"),
                   "county": a.get("COUNTY"), "listing_timestamp": _ts(a.get("TIMESTAMP")),
                   "attribution": "Camera: FL511 / Florida DOT"},
        ))
    return out
