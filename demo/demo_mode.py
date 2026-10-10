"""DEMO_MODE=1: swap a few camera snapshots for openly licensed flood photos.

Clearly labelled SIMULATED everywhere (API field, map popup, banner). Grok
still classifies the swapped images live, so the detection path is real.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import yaml

from core.http import client
from core.schema import Observation, haversine_km

log = logging.getLogger("demo")
DIR = Path(__file__).resolve().parent
IMG_DIR = DIR / "images"
COMMONS = "https://commons.wikimedia.org/w/api.php"


def enabled() -> bool:
    return os.getenv("DEMO_MODE", "0").lower() in ("1", "true", "yes")


def _cfg() -> dict:
    return yaml.safe_load((DIR / "sources.yaml").read_text())


def _slug(title: str) -> str:
    stem = title.rsplit(".", 1)[0]
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:80] + ".jpg"


def ensure_images() -> list[dict]:
    """Download (once) the demo images; return their metadata."""
    IMG_DIR.mkdir(exist_ok=True)
    out = []
    with client(timeout=30) as c:
        for item in _cfg()["images"]:
            fname = _slug(item["title"])
            path = IMG_DIR / fname
            if not path.exists():
                try:
                    r = c.get(COMMONS, params={"action": "query", "titles": "File:" + item["title"], "prop": "imageinfo",
                                               "iiprop": "url", "iiurlwidth": 800, "format": "json"})
                    info = next(iter(r.json()["query"]["pages"].values()))["imageinfo"][0]
                    img = c.get(info.get("thumburl") or info["url"])
                    img.raise_for_status()
                    path.write_bytes(img.content)
                except Exception as e:
                    log.warning("demo image download failed for %s: %s", item["title"], e)
                    continue
            out.append({**item, "file": fname,
                        "page": "https://commons.wikimedia.org/wiki/File:" + item["title"].replace(" ", "_")})
    return out


def apply(cameras: list[Observation], city: dict) -> list[Observation]:
    """Mark the camera nearest each demo neighborhood as SIMULATED with a flood photo."""
    images = ensure_images()
    if not images or not cameras:
        return []
    hoods = {n["id"]: n for n in city.get("neighborhoods", [])}
    chosen: list[Observation] = []
    for i, hid in enumerate(_cfg().get("neighborhoods", [])):
        h = hoods.get(hid)
        if not h:
            continue
        cam = min((c for c in cameras if c not in chosen),
                  key=lambda c: haversine_km(h["lat"], h["lon"], c.place.lat, c.place.lon))
        img = images[i % len(images)]
        cam.extra.update({"simulated": True, "image_url": f"/demo-images/{img['file']}",
                          "local_image": str(IMG_DIR / img["file"]),
                          "image_credit": f"SIMULATED demo image: '{img['title']}' by B137, Wikimedia Commons, {img['license']}",
                          "image_page": img["page"]})
        chosen.append(cam)
    return chosen


def fire_hotspots(city: dict) -> list[Observation]:
    """SIMULATED satellite fire detections from the city pack (``fire.demo_hotspots``) for a dry-day demo.

    Own source name (``demo_fire``) so they never mix with real NASA FIRMS data, and labelled SIMULATED in
    ``extra.simulated``, the headline, the map popup and the page banner.
    """
    from core.schema import Place, utcnow_iso
    out = []
    for i, h in enumerate((city.get("fire") or {}).get("demo_hotspots") or []):
        conf = h.get("confidence", "nominal")
        out.append(Observation(
            force="fire", source="demo_fire",
            place=Place(id=f"sim-fire-{i}", name=f"SIMULATED fire detection: {h.get('name', 'demo')}",
                        lat=float(h["lat"]), lon=float(h["lon"])),
            time=utcnow_iso(), measurement="active_fire", value=float(h.get("frp", 10.0)), unit="MW FRP",
            threshold="detection within watch_km", status="alert" if conf == "high" else "watch",
            extra={"kind": "hotspot", "simulated": True, "confidence": conf, "product": "SIMULATED",
                   "headline": f"SIMULATED: satellite fire detection near {h.get('name', 'demo')} ({conf} confidence)",
                   "note": "Demo only (DEMO_MODE=1). Not a real detection; real ones come from NASA FIRMS."},
        ))
    return out


def air_sensors(city: dict) -> list[Observation]:
    """SIMULATED AQI sensors from the city pack (``air.demo_sensors``) for a demo without AirNow/PurpleAir keys.

    Only used when both real AQI adapters are skipped. Own source name (``demo_air``), ``extra.simulated``,
    SIMULATED names/headlines; never mixed with real readings.
    """
    from adapters.air._aqi import category, status
    from core.schema import Place, utcnow_iso
    air = city.get("air") or {}
    out = []
    for i, s in enumerate(air.get("demo_sensors") or []):
        aqi = int(s["aqi"])
        out.append(Observation(
            force="air", source="demo_air",
            place=Place(id=f"sim-aqi-{i}", name=f"SIMULATED AQI sensor: {s.get('name', 'demo')}",
                        lat=float(s["lat"]), lon=float(s["lon"])),
            time=utcnow_iso(), measurement="AQI PM2.5 (SIMULATED)", value=aqi, unit="AQI",
            threshold=air.get("aqi_watch", 101), status=status(aqi, air),
            extra={"kind": "aqi_sensor", "simulated": True, "network": "SIMULATED", "category": category(aqi),
                   "headline": f"SIMULATED: AQI {aqi} ({category(aqi)}) at {s.get('name', 'demo')}",
                   "note": "Demo only (DEMO_MODE=1, no AirNow/PurpleAir key). Not a real reading."},
        ))
    return out


def land_evac_orders(city: dict) -> list[Observation]:
    """SIMULATED evacuation order flags from the city pack (``land.demo_evac_orders``) for a calm-day demo.

    Own source name (``demo_land``), ``extra.simulated``, SIMULATED headline; never mixed with the county layer.
    """
    from core.schema import Place, utcnow_iso
    hoods = {n["id"]: n for n in city.get("neighborhoods", [])}
    out = []
    for d in (city.get("land") or {}).get("demo_evac_orders") or []:
        n = hoods.get(d.get("neighborhood"))
        if not n:
            continue
        zone = d.get("zone", "A")
        out.append(Observation(
            force="land", source="demo_land",
            place=Place(id=f"sim-evac-{n['id']}", name=f"SIMULATED evacuation order: {n['name']}", lat=n["lat"], lon=n["lon"]),
            time=utcnow_iso(), measurement="hurricane_evacuation_zone", value=zone, unit="zone",
            threshold="evacuation order in effect", status="watch",
            extra={"neighborhood": n["id"], "evac_order_flag": True, "simulated": True,
                   "headline": f"SIMULATED: evacuation order for zone {zone} ({n['name']}) - demo only",
                   "note": "Demo only (DEMO_MODE=1). Not a real order; real flags come from the county layer."},
        ))
    return out
