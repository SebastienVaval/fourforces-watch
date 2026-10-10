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
