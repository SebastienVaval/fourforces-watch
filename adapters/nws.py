"""Shared fetch of active NWS alerts (api.weather.gov), classified by force.

The thin adapters water/nws_flood, air/nws_wind, land/nws_land and fire/nws_heat
all use this so the API is called once per refresh.
"""
from __future__ import annotations

import time

from core.http import client
from core.schema import Observation, Place, to_utc_iso

_CACHE: dict = {"t": 0.0, "key": None, "data": []}
TTL = 120

KEYWORDS = {
    "water": ["flood", "surge", "hydrologic", "surf", "rip current", "tsunami", "coastal", "marine"],
    "fire": ["heat", "fire", "red flag", "smoke"],
    "air": ["wind", "hurricane", "tropical", "tornado", "storm", "air quality", "fog", "dust", "gale"],
    "land": ["evacuation", "civil", "shelter", "earthquake", "landslide", "debris", "law enforcement",
             "hazardous materials", "911", "local area emergency", "special weather"],
}
ORDER = ["water", "fire", "air", "land"]  # "Storm Surge Warning" -> water, "Tropical Storm Warning" -> air


def classify(event: str) -> str:
    e = event.lower()
    for force in ORDER:
        if any(k in e for k in KEYWORDS[force]):
            return force
    return "land"


def status_for(event: str, severity: str) -> str:
    e = event.lower()
    if "warning" in e or "emergency" in e or severity in ("Extreme", "Severe"):
        return "alert"
    return "watch"  # watch / advisory / statement


def _fetch_all(city: dict) -> list[dict]:
    nws = city["nws"]
    key = (tuple(nws.get("point", [])), tuple(nws.get("zones", [])))
    if _CACHE["key"] == key and time.time() - _CACHE["t"] < TTL:
        return _CACHE["data"]
    feats: dict[str, dict] = {}
    hdr = {"Accept": "application/geo+json"}
    with client() as c:
        lat, lon = nws["point"]
        r = c.get("https://api.weather.gov/alerts/active", params={"point": f"{lat},{lon}"}, headers=hdr)
        r.raise_for_status()
        feats.update({f["id"]: f for f in r.json().get("features", [])})
        if nws.get("zones"):
            r = c.get("https://api.weather.gov/alerts/active", params={"zone": ",".join(nws["zones"])}, headers=hdr)
            if r.status_code == 200:
                feats.update({f["id"]: f for f in r.json().get("features", [])})
    _CACHE.update(t=time.time(), key=key, data=list(feats.values()))
    return _CACHE["data"]


def observations(city: dict, force: str) -> list[Observation]:
    if not city.get("nws"):
        return []
    lat, lon = city["nws"]["point"]
    out = []
    for f in _fetch_all(city):
        p = f["properties"]
        event = p.get("event", "")
        if classify(event) != force:
            continue
        ugc = (p.get("geocode") or {}).get("UGC", [])
        mine = [z for z in ugc if z in (city["nws"].get("zones") or [])]
        out.append(Observation(
            force=force, source="nws_alerts",
            place=Place(id=p.get("id", "")[-40:], name=p.get("areaDesc", "")[:120], lat=lat, lon=lon),
            time=to_utc_iso(p.get("sent")), measurement=event, value=p.get("severity"),
            status=status_for(event, p.get("severity", "")),
            extra={"scope": "area", "zones": mine, "headline": p.get("headline"),
                   "description": (p.get("description") or "")[:1500], "instruction": p.get("instruction"),
                   "onset": p.get("onset"), "ends": p.get("ends") or p.get("expires"),
                   "certainty": p.get("certainty"), "observed": p.get("certainty") == "Observed",
                   "link": f.get("id")},
        ))
    return out
