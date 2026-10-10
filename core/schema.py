"""Common observation schema shared by every adapter.

Every adapter returns ``list[Observation]``. The rest of the app (rule engine,
API, map, GeoJSON and CAP exports) only sees this one shape, so a new data
source only has to map its feed into it.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

FORCES = ("water", "air", "land", "fire")
STATUSES = ("ok", "watch", "alert", "unknown")
STATUS_RANK = {"unknown": -1, "ok": 0, "watch": 1, "alert": 2}


@dataclass
class Place:
    id: str
    name: str
    lat: float | None = None
    lon: float | None = None


@dataclass
class Observation:
    force: str            # water | air | land | fire
    source: str           # adapter / feed name
    place: Place
    time: str             # ISO 8601 UTC
    measurement: str
    value: Any = None
    unit: str | None = None
    threshold: Any = None
    status: str = "ok"    # ok | watch | alert | unknown
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def uid(self) -> str:
        return hashlib.sha1(f"{self.source}|{self.place.id}|{self.measurement}".encode()).hexdigest()[:16]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_utc_iso(value: str | datetime | None) -> str:
    """Best-effort conversion of a timestamp to ISO UTC ('Z')."""
    if value is None:
        return utcnow_iso()
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def worst(statuses) -> str:
    out = "unknown"
    for s in statuses:
        if STATUS_RANK.get(s, -1) > STATUS_RANK[out]:
            out = s
    return out


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- GeoJSON
def to_geojson(observations: list[Observation]) -> dict:
    features = []
    for o in observations:
        geom = None
        if o.place.lat is not None and o.place.lon is not None:
            geom = {"type": "Point", "coordinates": [o.place.lon, o.place.lat]}
        props = o.to_dict()
        props.pop("place")
        props.update({"place_id": o.place.id, "place_name": o.place.name, "uid": o.uid})
        features.append({"type": "Feature", "id": o.uid, "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "generated": utcnow_iso(), "features": features}


# ---------------------------------------------------------------- CAP 1.2
_SEVERITY = {"alert": "Severe", "watch": "Moderate", "ok": "Minor", "unknown": "Unknown"}
_CATEGORY = {"water": "Met", "air": "Env", "land": "Geo", "fire": "Fire"}


def to_cap(observations: list[Observation], sender: str = "fourforces-watch", area_name: str = "") -> str:
    """Export watch/alert observations as OASIS CAP 1.2 <alert> elements.

    CAP has no multi-alert container, so the alerts are wrapped in <capFeed>;
    consumers can split on <alert>.
    """
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<capFeed>"]
    for o in observations:
        if o.status not in ("watch", "alert"):
            continue
        headline = o.extra.get("headline") or f"{o.measurement} {o.status} at {o.place.name}"
        desc = o.extra.get("description") or f"{o.measurement} = {o.value} {o.unit or ''} (threshold {o.threshold})"
        circle = f"<circle>{o.place.lat:.5f},{o.place.lon:.5f} 1.0</circle>" if o.place.lat is not None else ""
        out.append(
            '<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
            f"<identifier>{escape(sender)}-{o.uid}-{escape(o.time)}</identifier>"
            f"<sender>{escape(sender)}</sender><sent>{escape(o.time.replace('Z', '+00:00'))}</sent>"
            "<status>Actual</status><msgType>Alert</msgType><scope>Public</scope>"
            f"<info><language>en-US</language><category>{_CATEGORY.get(o.force, 'Other')}</category>"
            f"<event>{escape(o.measurement)}</event><urgency>Unknown</urgency>"
            f"<severity>{_SEVERITY[o.status]}</severity>"
            f"<certainty>{'Observed' if o.extra.get('observed', True) else 'Likely'}</certainty>"
            f"<senderName>{escape(o.source)}</senderName>"
            f"<headline>{escape(str(headline)[:160])}</headline>"
            f"<description>{escape(str(desc)[:2000])}</description>"
            f"<parameter><valueName>force</valueName><value>{o.force}</value></parameter>"
            f"<area><areaDesc>{escape(o.place.name or area_name)}</areaDesc>{circle}</area>"
            "</info></alert>"
        )
    out.append("</capFeed>")
    return "\n".join(out)
