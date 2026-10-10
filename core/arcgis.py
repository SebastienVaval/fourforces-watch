"""Generic client for public ArcGIS REST layers (ArcGIS Hub open-data portals). No key.

Any city whose open-data portal runs on ArcGIS Hub publishes FeatureServer / MapServer
layers with a ``/query`` endpoint. Everything city-specific (layer URLs, label fields,
colours, attribution) lives in the city pack; this module only knows the REST protocol.

Two uses:
- ``layer_observations``: point layers (fire stations, cooling centres...) become
  reference ``Observation`` objects (``extra.reference = True``) for one force. Reference
  items are shown on the map but never change a neighborhood's status.
- ``overlay_geojson``: polygon / line layers (flood zones, evacuation zones, canals...)
  are served as GeoJSON overlays for the dashboard via ``/api/overlays/{id}``.
"""
from __future__ import annotations

import time

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place, utcnow_iso

DEFAULT_TTL = 6 * 3600          # reference layers change rarely; be polite to the county server
_CACHE: dict[str, tuple[float, dict]] = {}


def query_geojson(url: str, *, where: str = "1=1", out_fields: str = "*", max_features: int = 2000,
                  page_size: int = 1000, max_offset: float | None = None, http=None) -> dict:
    """Query ``<layer url>/query`` as GeoJSON (WGS84), following ArcGIS pagination
    (``exceededTransferLimit``) up to ``max_features``."""
    feats: list[dict] = []
    own = http is None
    c = http or client(timeout=30)
    try:
        while len(feats) < max_features:
            params = {"where": where, "outFields": out_fields, "outSR": 4326, "f": "geojson",
                      "resultOffset": len(feats), "resultRecordCount": min(page_size, max_features - len(feats))}
            if max_offset:
                params.update(maxAllowableOffset=max_offset, geometryPrecision=5)
            r = c.get(f"{url.rstrip('/')}/query", params=params)
            r.raise_for_status()
            j = r.json()
            if "error" in j:
                raise RuntimeError(f"ArcGIS error: {j['error'].get('message')}")
            page = j.get("features", [])
            feats += page
            more = (j.get("properties") or {}).get("exceededTransferLimit") or j.get("exceededTransferLimit")
            if not page or not more:
                break
    finally:
        if own:
            c.close()
    return {"type": "FeatureCollection", "features": feats[:max_features]}


def cached_geojson(layer: dict, ttl: int = DEFAULT_TTL, **kw) -> dict:
    key = f"{layer['url']}|{layer.get('where', '1=1')}|{layer.get('fields', '*')}"
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    fc = query_geojson(layer["url"], where=layer.get("where", "1=1"), out_fields=layer.get("fields", "*"),
                       max_features=int(layer.get("max_features", 2000)),
                       page_size=int(layer.get("page_size", 1000)), max_offset=layer.get("simplify"), **kw)
    _CACHE[key] = (time.time(), fc)
    return fc


def open_data(city: dict) -> dict:
    return city.get("open_data") or {}


def features_to_observations(fc: dict, layer: dict, force: str, source: str, attribution: str = "") -> list[Observation]:
    """Point features -> reference observations (status ok, never raise a tile status)."""
    out, now = [], utcnow_iso()
    label = layer.get("label_field")
    for i, f in enumerate(fc.get("features", [])):
        g, p = f.get("geometry") or {}, f.get("properties") or {}
        if g.get("type") != "Point":
            continue
        lon, lat = g["coordinates"][:2]
        name = str(p.get(label) or layer.get("name") or "Facility").strip()
        fid = f.get("id", p.get("OBJECTID", p.get("FID", i)))
        out.append(Observation(
            force=force, source=source,
            place=Place(id=f"{layer['id']}-{fid}", name=name.title() if name.isupper() else name, lat=lat, lon=lon),
            time=now, measurement=layer.get("measurement", layer["id"]), value=layer.get("name"), unit=None,
            status="ok",
            extra={"reference": True, "layer": layer["id"], "layer_name": layer.get("name"),
                   "attribution": attribution, "properties": {k: v for k, v in p.items() if v not in (None, "")},
                   "link": layer.get("link")},
        ))
    return out


def layer_observations(city: dict, force: str, source: str) -> list[Observation]:
    """Adapter body shared by adapters/<force>/county_gis.py."""
    od = open_data(city)
    layers = (city.get(force) or {}).get("county_gis") or []
    if not layers:
        raise SkipAdapter(f"no {force}.county_gis layers in city pack")
    out: list[Observation] = []
    errors = []
    for layer in layers:
        try:
            out += features_to_observations(cached_geojson(layer), layer, force, source, od.get("attribution", ""))
        except Exception as e:  # one bad layer must not hide the others
            errors.append(f"{layer['id']}: {e}")
    if errors and not out:
        raise RuntimeError("; ".join(errors)[:200])
    return out


def overlays(city: dict) -> list[dict]:
    return list(open_data(city).get("overlays") or [])


def overlay_meta(city: dict) -> list[dict]:
    od = open_data(city)
    return [{k: o.get(k) for k in ("id", "name", "force", "color", "style_field", "styles", "ramp", "label_field",
                                   "default", "geometry")} | {"attribution": od.get("attribution", "")}
            for o in overlays(city)]


def overlay_geojson(city: dict, overlay_id: str) -> dict | None:
    o = next((x for x in overlays(city) if x.get("id") == overlay_id), None)
    if o is None:
        return None
    fc = cached_geojson(o)
    return fc | {"attribution": open_data(city).get("attribution", ""), "name": o.get("name")}
