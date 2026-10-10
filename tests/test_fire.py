"""Offline tests for the fire force: FIRMS parsing, hotspot rule, nearest station, demo labelling, messages."""
from adapters.fire import firms
from core.city import load_city
from core.schema import Observation, Place
from demo import demo_mode
from forces import fire
from forces.engine import board

CSV_VIIRS = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
25.8195,-80.3900,330.1,0.4,0.4,2026-10-10,0642,N20,VIIRS,h,2.0NRT,290.0,12.3,N
25.4000,-80.8000,310.0,0.4,0.4,2026-10-10,1805,N20,VIIRS,l,2.0NRT,290.0,1.1,D
"""
CSV_MODIS = """latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight
25.70,-80.60,320.0,1.0,1.0,2026-10-10,1530,Aqua,MODIS,85,6.1NRT,300.0,20.0,D
"""


def _site(layer, name, lat, lon, force="fire"):
    return Observation(force=force, source="county_gis_fire", place=Place(id=f"{layer}-{name}", name=name, lat=lat, lon=lon),
                       time="2026-10-10T15:00:00Z", measurement=layer, status="ok",
                       extra={"reference": True, "layer": layer, "properties": {"ADDRESS": "1 Main St"}})


def test_firms_parse_and_confidence():
    obs = firms.parse_csv(CSV_VIIRS, "VIIRS_NOAA20_NRT") + firms.parse_csv(CSV_MODIS, "MODIS_NRT")
    assert [o.extra["confidence"] for o in obs] == ["high", "low", "high"]
    assert obs[0].time == "2026-10-10T06:42:00Z" and obs[0].value == 12.3 and obs[0].extra["kind"] == "hotspot"
    assert firms.norm_confidence("50") == "nominal" and firms.norm_confidence("n") == "nominal"
    assert firms.parse_csv("latitude,longitude\n", "X") == []


def test_firms_skips_without_key(monkeypatch):
    import pytest
    from adapters.base import SkipAdapter
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    with pytest.raises(SkipAdapter):
        firms.fetch(load_city("miami"))


def test_hotspot_rule_distance_and_confidence():
    city = load_city("miami")
    hoods = {n["id"]: n for n in city["neighborhoods"]}
    near_high, far_low, mid_high = firms.parse_csv(CSV_VIIRS, "V") + firms.parse_csv(CSV_MODIS, "M")
    doral = hoods["doral"]  # 25.8195,-80.3553 -> near_high ~3.5 km
    assert fire.hotspot_status(near_high, doral, city) == "alert"
    assert fire.hotspot_status(far_low, hoods["homestead"], city) is None          # low confidence ignored
    assert fire.hotspot_status(near_high, hoods["miami-beach"], city) is None      # > 15 km
    ten_km_east = dict(doral, lon=-80.29)  # 0.1 deg of longitude at 25.8 N ~ 10 km from the hotspot
    assert fire.hotspot_status(near_high, ten_km_east, city) == "watch"
    tiles = {t["id"]: t for t in board([near_high, far_low, mid_high], city)}
    assert tiles["doral"]["forces"]["fire"]["status"] == "alert"
    assert tiles["miami-beach"]["forces"]["fire"]["status"] == "unknown"


def test_nearest_station_and_cooling_context():
    city = load_city("miami")
    sites = [_site("mdc_fire_stations", "Station Near", 25.82, -80.38), _site("mdc_fire_stations", "Station Far", 25.47, -80.48),
             _site("mdc_cooling_centers", "Library A", 25.82, -80.36), _site("mdc_cooling_centers", "Library B", 25.83, -80.30),
             _site("mdc_cooling_centers", "Library C", 25.47, -80.47)]
    hot = firms.parse_csv(CSV_VIIRS, "V")[:1]
    tiles = {t["id"]: t for t in board(sites + hot, city)}
    assert hot[0].extra["nearest_station"]["name"] == "Station Near" and hot[0].extra["nearest_station"]["km"] < 1.5
    ctx = tiles["doral"]["forces"]["fire"]["context"]
    assert ctx["nearest_station"]["name"] == "Station Near"
    assert [c["name"] for c in ctx["cooling_centers"]] == ["Library A", "Library B"]
    assert ctx["nearest_hotspot"]["simulated"] is False
    assert tiles["homestead"]["forces"]["fire"]["context"]["nearest_station"]["name"] == "Station Far"


def test_demo_hotspot_is_labelled_and_separate():
    city = load_city("miami")
    sims = demo_mode.fire_hotspots(city)
    assert sims, "miami.yaml should define a demo hotspot"
    for o in sims:
        assert o.source == "demo_fire" and o.source != firms.NAME
        assert o.extra["simulated"] is True and o.extra["headline"].startswith("SIMULATED")
        assert o.place.name.startswith("SIMULATED") and o.extra["kind"] == "hotspot"
    tiles = {t["id"]: t for t in board(sims, city)}
    assert tiles["doral"]["forces"]["fire"]["status"] in ("watch", "alert")
    assert tiles["miami-beach"]["forces"]["fire"]["status"] == "unknown"
    assert tiles["doral"]["forces"]["fire"]["context"]["nearest_hotspot"]["simulated"] is True


def test_fire_template_messages_trilingual():
    from detect import messages
    m = messages._template("Doral", "watch", {"water": "ok", "air": "ok", "land": "ok", "fire": "watch"})
    assert "cooling center" in m["en"] and "911" in m["es"] and "dife" in m["ht"]
    assert "flooded" not in m["en"]
    ok = messages._template("Doral", "ok", {"water": "ok", "air": "ok", "land": "ok", "fire": "ok"})
    assert "911" not in ok["en"]
