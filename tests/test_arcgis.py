"""Offline tests for the generic ArcGIS Hub client, county_gis adapters, overlays and Mapbox config."""
import httpx
import pytest

from adapters.base import SkipAdapter
from core import arcgis
from core.city import load_city
from core.schema import Observation, Place
from forces.engine import board

LAYER = "https://example.org/arcgis/rest/services/FireStation_gdb/FeatureServer/0"


def _fake_http(pages):
    """httpx client whose /query answers with the given GeoJSON pages in order."""
    calls = []

    def handler(request: httpx.Request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=pages[len(calls) - 1])
    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def _pt(i, name, lon=-80.19, lat=25.76):
    return {"type": "Feature", "id": i, "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"NAME": name, "ADDRESS": "1 Main St", "EMPTY": None}}


def test_query_geojson_follows_pagination():
    http, calls = _fake_http([
        {"type": "FeatureCollection", "features": [_pt(1, "A"), _pt(2, "B")], "properties": {"exceededTransferLimit": True}},
        {"type": "FeatureCollection", "features": [_pt(3, "C")]},
    ])
    fc = arcgis.query_geojson(LAYER, page_size=2, max_offset=0.001, http=http)
    assert [f["id"] for f in fc["features"]] == [1, 2, 3]
    assert calls[0]["f"] == "geojson" and calls[0]["outSR"] == "4326" and calls[1]["resultOffset"] == "2"
    assert calls[0]["maxAllowableOffset"] == "0.001"


def test_query_geojson_raises_on_arcgis_error():
    http, _ = _fake_http([{"error": {"code": 400, "message": "Invalid query"}}])
    with pytest.raises(RuntimeError):
        arcgis.query_geojson(LAYER, http=http)


def test_point_features_become_reference_observations():
    fc = {"features": [_pt(7, "STATION 1"), {"geometry": {"type": "Polygon", "coordinates": []}, "properties": {}}]}
    layer = {"id": "mdc_fire_stations", "name": "Fire station", "label_field": "NAME", "measurement": "fire_station"}
    obs = arcgis.features_to_observations(fc, layer, "fire", "county_gis_fire", "Miami-Dade County Open Data")
    assert len(obs) == 1
    o = obs[0]
    assert o.place.name == "Station 1" and o.place.id == "mdc_fire_stations-7" and o.status == "ok"
    assert o.extra["reference"] is True and o.extra["attribution"] == "Miami-Dade County Open Data"
    assert "EMPTY" not in o.extra["properties"]


def test_county_gis_adapter_uses_city_pack(monkeypatch):
    from adapters.fire import county_gis
    monkeypatch.setattr(arcgis, "cached_geojson", lambda layer, **kw: {"features": [_pt(1, layer["id"])]})
    city = load_city("miami")
    obs = county_gis.fetch(city)
    assert {o.extra["layer"] for o in obs} == {"mdc_fire_stations", "mdc_cooling_centers"}
    assert all(o.force == "fire" and o.source == "county_gis_fire" for o in obs)
    with pytest.raises(SkipAdapter):
        county_gis.fetch({"fire": {}})


def test_reference_sites_never_change_tile_status():
    ref = Observation(force="fire", source="county_gis_fire", place=Place(id="s", name="S", lat=25.7617, lon=-80.1918),
                      time="2026-10-10T15:00:00Z", measurement="fire_station", status="ok", extra={"reference": True})
    tiles = {t["id"]: t for t in board([ref], load_city("miami"))}
    assert tiles["downtown"]["forces"]["fire"]["status"] == "unknown"


def test_miami_overlays_configured():
    city = load_city("miami")
    meta = {m["id"]: m for m in arcgis.overlay_meta(city)}
    assert {"mdc_surge_zones", "mdc_fema_ve", "mdc_canals"} <= set(meta)
    assert all(m["attribution"] == "Miami-Dade County Open Data" for m in meta.values())
    assert all(o["url"].startswith("https://") and "/FeatureServer/" in o["url"] for o in arcgis.overlays(city))
    assert arcgis.overlay_geojson(city, "nope") is None


def test_config_exposes_only_public_mapbox_token(monkeypatch):
    import app
    monkeypatch.setenv("MAPBOX_TOKEN", "sk.secret-token")
    assert app.api_config()["mapbox_token"] is None
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.public-test")
    assert app.api_config()["mapbox_token"] == "pk.public-test"
    monkeypatch.delenv("MAPBOX_TOKEN")
    cfg = app.api_config()
    assert cfg["mapbox_token"] is None and cfg["open_data"]["attribution"] == "Miami-Dade County Open Data"
