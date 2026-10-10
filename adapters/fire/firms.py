"""NASA FIRMS satellite active-fire detections in the city bbox. Needs FIRMS_MAP_KEY (free)."""
from __future__ import annotations

import csv
import io
import os

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place

NAME, FORCE = "nasa_firms", "fire"


def fetch(city: dict) -> list[Observation]:
    key = os.getenv("FIRMS_MAP_KEY")
    if not key:
        raise SkipAdapter("FIRMS_MAP_KEY not set (free key: https://firms.modaps.eosdis.nasa.gov/api/map_key/)")
    cfg, b = (city.get("fire") or {}).get("firms") or {}, city["bbox"]
    url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{cfg.get('source', 'VIIRS_SNPP_NRT')}/"
           f"{b['west']},{b['south']},{b['east']},{b['north']}/{cfg.get('days', 1)}")
    with client(timeout=30) as c:
        r = c.get(url)
        r.raise_for_status()
    if r.text.startswith("Invalid"):
        raise SkipAdapter(f"FIRMS refused key: {r.text[:80]}")
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        lat, lon = float(row["latitude"]), float(row["longitude"])
        t = row.get("acq_time", "0000").zfill(4)
        conf = row.get("confidence", "")
        out.append(Observation(
            force=FORCE, source=NAME, place=Place(id=f"firms-{lat:.4f}-{lon:.4f}-{t}", name="Satellite fire detection",
                                                  lat=lat, lon=lon),
            time=f"{row.get('acq_date')}T{t[:2]}:{t[2:]}:00Z", measurement="active_fire_frp",
            value=float(row.get("frp") or 0), unit="MW", threshold="any detection",
            status="alert" if conf in ("h", "high") else "watch",
            extra={"confidence": conf, "satellite": row.get("satellite"), "link": "https://firms.modaps.eosdis.nasa.gov/map/"},
        ))
    return out
