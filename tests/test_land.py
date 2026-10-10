"""Offline tests for the land force: OpenFEMA, USGS earthquakes, evacuation zones/shelters, rules, demo labelling."""
import httpx

from adapters.land import evac_zones, fema_declarations, usgs_earthquakes
from core.city import load_city
from core.schema import Observation, Place
from demo import demo_mode
from forces import land
from forces.engine import board


def _mock(monkeypatch, module, handler_or_payload, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        p = handler_or_payload(request) if callable(handler_or_payload) else handler_or_payload
        return httpx.Response(200, json=p)
    monkeypatch.setattr(module, "client", lambda *a, **k: httpx.Client(transport=httpx.MockTransport(handler)))


def _quake(mag, lat, lon, eid="x1"):
    return {"id": eid, "geometry": {"coordinates": [lon, lat, 10.0]},
            "properties": {"mag": mag, "place": "test", "time": 1760115600000, "title": f"M {mag} - test", "url": "u"}}


def test_fema_open_and_closed_declarations(monkeypatch):
    rows = {"DisasterDeclarationsSummaries": [
        {"disasterNumber": 9001, "declarationTitle": "HURRICANE TEST", "declarationDate": "2026-10-01T00:00:00.000Z",
         "incidentType": "Hurricane", "declarationType": "DR", "incidentEndDate": None, "designatedArea": "Miami-Dade (County)"},
        {"disasterNumber": 9001, "declarationTitle": "dup", "declarationDate": "2026-10-01T00:00:00.000Z",
         "incidentType": "Hurricane", "declarationType": "DR", "designatedArea": "Miami-Dade (County)"},
        {"disasterNumber": 8000, "declarationTitle": "OLD STORM", "declarationDate": "2025-11-01T00:00:00.000Z",
         "incidentType": "Hurricane", "declarationType": "EM", "incidentEndDate": "2025-11-05T00:00:00.000Z"}]}
    seen = []
    _mock(monkeypatch, fema_declarations, rows, seen)
    city = load_city("miami")
    obs = fema_declarations.fetch(city)
    assert [o.status for o in obs] == ["watch", "ok"]                     # deduplicated, open one is watch
    flt = seen[0].url.params["$filter"]
    assert "state eq 'FL'" in flt and "fipsCountyCode eq '086'" in flt
    tiles = {t["id"]: t for t in board(obs, city)}
    assert all(t["forces"]["land"]["status"] == "watch" for t in tiles.values())   # county-wide
    assert "HURRICANE TEST" in tiles["doral"]["forces"]["land"]["context"]["fema_open"][0]


def test_usgs_quakes_distance_and_magnitude_rule(monkeypatch):
    seen = []
    _mock(monkeypatch, usgs_earthquakes, {"features": [_quake(5.0, 25.80, -80.30, "near"), _quake(3.0, 26.9, -80.2, "far")]}, seen)
    city = load_city("miami")
    near, far = usgs_earthquakes.fetch(city)
    assert near.extra["kind"] == "earthquake" and near.value == 5.0 and near.time == "2025-10-10T17:00:00Z"
    assert "minlatitude" in seen[0].url.params and seen[0].url.params["format"] == "geojson"
    hoods = {n["id"]: n for n in city["neighborhoods"]}
    assert land.quake_status(near, hoods["doral"], city) == "alert"            # M5 ~6 km away
    assert land.quake_status(far, hoods["north-miami"], city) == "watch"       # M3 ~112 km away
    assert land.quake_status(far, hoods["homestead"], city) is None            # > 150 km
    tiles = {t["id"]: t for t in board([near, far], city)}
    assert tiles["doral"]["forces"]["land"]["status"] == "alert"
    assert land.quake_status(near, dict(hoods["doral"], lat=26.35), city) == "watch"   # M5 ~60 km away: > alert_km


def test_evac_zones_and_order_flag(monkeypatch):
    def handler(req):
        url = str(req.url)
        if "EvacuationOrder" in url:
            return {"features": [{"attributes": {"ZONEID": "A", "EVACORDER": "Y"}}]}
        if "Shelters" in url:
            return {"features": [{"attributes": {"shelter_name": "Shelter One", "address": "1 Main St"},
                                  "geometry": {"x": -80.20, "y": 25.77}}]}
        return {"features": [{"attributes": {"ZONEID": "A"}}]}
    evac_zones._ZONES.clear()
    _mock(monkeypatch, evac_zones, handler)
    city = load_city("miami")
    obs = evac_zones.fetch(city)
    zones = [o for o in obs if o.source == evac_zones.NAME]
    assert len(zones) == len(city["neighborhoods"]) and all(o.status == "watch" for o in zones)  # trust_orders false
    assert "confirm with official channels" in zones[0].extra["headline"]
    tiles = {t["id"]: t for t in board(obs, city)}
    lh = tiles["little-havana"]["forces"]["land"]
    assert lh["status"] == "watch" and "evac_shelters" not in lh["sources"]   # shelter is not a hazard
    assert lh["context"]["evac_zone"] == {"zone": "A", "order_flag": True, "simulated": False}
    assert lh["context"]["nearest_shelter"]["name"] == "Shelter One" and lh["context"]["nearest_shelter"]["km"] < 2
    evac_zones._ZONES.clear()


def test_bus_pickup_context_never_a_status():
    city = load_city("miami")
    stop = Observation(force="land", source="county_gis_land", place=Place(id="b1", name="Stop 1", lat=25.82, lon=-80.355),
                       time="2026-10-10T15:00:00Z", measurement="evacuation_bus_pickup", status="ok",
                       extra={"reference": True, "layer": "mdc_evac_bus_pickup", "properties": {"ADDRESS": "2 Main"}})
    t = {t["id"]: t for t in board([stop], city)}["doral"]["forces"]["land"]
    assert t["status"] == "unknown" and t["context"]["nearest_bus_pickup"]["address"] == "2 Main"


def test_demo_evac_order_is_labelled_and_separate():
    city = load_city("miami")
    sims = demo_mode.land_evac_orders(city)
    assert sims, "miami.yaml should define a demo evacuation order"
    for o in sims:
        assert o.source == "demo_land" and o.source != evac_zones.NAME
        assert o.extra["simulated"] is True and o.extra["headline"].startswith("SIMULATED")
        assert o.place.name.startswith("SIMULATED")
    tiles = {t["id"]: t for t in board(sims, city)}
    mb = tiles["miami-beach"]["forces"]["land"]
    assert mb["status"] == "watch" and mb["context"]["evac_zone"]["simulated"] is True
    assert tiles["doral"]["forces"]["land"]["status"] == "unknown"
    from detect import messages
    m = messages._label_simulated({"en": "x", "es": "y", "ht": "z"}, mb["reasons"])
    assert m["simulated"] and m["en"].startswith("[SIMULATED demo]")
