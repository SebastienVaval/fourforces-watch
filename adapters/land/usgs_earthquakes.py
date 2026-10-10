"""USGS earthquake catalog (earthquake.usgs.gov FDSN, bbox query). No key. Generic; rarely fires in Florida.

Each event is a point (``extra.kind = earthquake``); forces/land.py turns distance + magnitude into a tile status.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place

NAME, FORCE = "usgs_earthquakes", "land"
API = "https://earthquake.usgs.gov/fdsnws/event/1/query"


def fetch(city: dict) -> list[Observation]:
    cfg = (city.get("land") or {}).get("earthquakes")
    if not cfg:
        raise SkipAdapter("no earthquakes settings in city pack")
    b, pad = city["bbox"], 1.0
    start = (datetime.now(timezone.utc) - timedelta(days=cfg.get("lookback_days", 30))).strftime("%Y-%m-%d")
    with client() as c:
        r = c.get(API, params={"format": "geojson", "starttime": start, "minmagnitude": cfg.get("min_magnitude", 2.5),
                               "minlatitude": b["south"] - pad, "maxlatitude": b["north"] + pad,
                               "minlongitude": b["west"] - pad, "maxlongitude": b["east"] + pad})
        r.raise_for_status()
        feats = r.json().get("features", [])
    return parse_geojson(feats)


def parse_geojson(feats: list[dict]) -> list[Observation]:
    out = []
    for f in feats:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        mag = p.get("mag") or 0
        out.append(Observation(
            force=FORCE, source=NAME, place=Place(id=f"usgs-eq-{f['id']}", name=p.get("place") or "", lat=lat, lon=lon),
            time=datetime.fromtimestamp(p["time"] / 1000, timezone.utc).isoformat().replace("+00:00", "Z"),
            measurement="earthquake_magnitude", value=mag, unit="M", threshold=4.5,
            status="alert" if mag >= 4.5 else "watch",
            extra={"kind": "earthquake", "depth_km": (f["geometry"]["coordinates"] + [None, None, None])[2],
                   "headline": p.get("title"), "link": p.get("url")},
        ))
    return out
