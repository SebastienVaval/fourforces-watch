"""Offline tests for the air force: AQI math, EPA correction, AirNow/PurpleAir (mocked HTTP), tile rule, demo labelling."""
import httpx
import pytest

from adapters.air import _aqi, airnow, purpleair
from adapters.base import SkipAdapter
from core.city import load_city
from demo import demo_mode
from forces import air
from forces.engine import board

AIRNOW_ROWS = [
    {"DateObserved": "2026-10-10 ", "HourObserved": 13, "LocalTimeZone": "EST", "ReportingArea": "Miami",
     "StateCode": "FL", "Latitude": 25.78, "Longitude": -80.21, "ParameterName": "O3", "AQI": 42,
     "Category": {"Number": 1, "Name": "Good"}},
    {"DateObserved": "2026-10-10 ", "HourObserved": 13, "LocalTimeZone": "EST", "ReportingArea": "Miami",
     "StateCode": "FL", "Latitude": 25.78, "Longitude": -80.21, "ParameterName": "PM2.5", "AQI": 112,
     "Category": {"Number": 3, "Name": "Unhealthy for Sensitive Groups"}},
    {"ParameterName": "PM10", "AQI": -1},
]
PA_JSON = {"api_version": "V1.0.11", "fields": ["sensor_index", "name", "latitude", "longitude", "pm2.5_10minute",
                                                "pm2.5_cf_1", "humidity", "last_seen", "confidence"],
           "data": [[101, "Doral A", 25.82, -80.355, 40.0, 60.0, 70, 1760115600, 100],
                    [102, "Doral B", 25.825, -80.35, 12.0, None, None, 1760115600, 98],
                    [103, "Broken", 25.82, -80.36, 500.0, 500.0, 50, 1760115600, 10]]}


def _mock(monkeypatch, module, payload, status=200, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(module, "client", lambda *a, **k: httpx.Client(transport=httpx.MockTransport(handler)))


def test_aqi_breakpoints_2024_and_correction():
    assert _aqi.pm25_to_aqi(9.0) == 50 and _aqi.pm25_to_aqi(9.1) == 51
    assert _aqi.pm25_to_aqi(35.49) == 100  # truncated to 35.4
    assert _aqi.pm25_to_aqi(55.4) == 150 and _aqi.pm25_to_aqi(125.4) == 200 and _aqi.pm25_to_aqi(400) == 500
    assert _aqi.category(101) == "Unhealthy for Sensitive Groups" and _aqi.category(350) == "Hazardous"
    assert _aqi.epa_correct(60.0, 70) == round(0.524 * 60 - 0.0862 * 70 + 5.75, 1)
    assert _aqi.epa_correct(10, None) is None and _aqi.epa_correct(0, 100) == 0.0


def test_airnow_parse_and_fetch(monkeypatch):
    monkeypatch.delenv("AIRNOW_API_KEY", raising=False)
    with pytest.raises(SkipAdapter, match="AIRNOW_API_KEY"):
        airnow.fetch(load_city("miami"))
    monkeypatch.setenv("AIRNOW_API_KEY", "test-key")
    seen = []
    _mock(monkeypatch, airnow, AIRNOW_ROWS, seen=seen)
    obs = airnow.fetch(load_city("miami"))
    q = seen[0].url.params
    assert seen[0].url.path == "/aq/observation/latLong/current/" and q["API_KEY"] == "test-key" and q["distance"] == "25"
    assert [o.value for o in obs] == [42, 112]  # negative AQI dropped
    pm = obs[1]
    assert pm.status == "watch" and pm.extra["kind"] == "aqi_area" and pm.extra["scope"] == "area"
    assert pm.time == "2026-10-10T18:00:00Z"
    _mock(monkeypatch, airnow, {"WebServiceError": [{"Message": "Invalid API key"}]}, status=401)
    with pytest.raises(SkipAdapter):
        airnow.fetch(load_city("miami"))


def test_purpleair_parse_and_fetch(monkeypatch):
    monkeypatch.delenv("PURPLEAIR_API_KEY", raising=False)
    with pytest.raises(SkipAdapter, match="PURPLEAIR_API_KEY"):
        purpleair.fetch(load_city("miami"))
    monkeypatch.setenv("PURPLEAIR_API_KEY", "pa-key")
    seen = []
    _mock(monkeypatch, purpleair, PA_JSON, seen=seen)
    obs = purpleair.fetch(load_city("miami"))
    req = seen[0]
    assert req.headers["X-API-Key"] == "pa-key" and req.url.params["location_type"] == "0"
    assert "pm2.5_cf_1" in req.url.params["fields"] and "humidity" in req.url.params["fields"]
    assert float(req.url.params["nwlat"]) > float(req.url.params["selat"])
    assert [o.place.id for o in obs] == ["purpleair-101", "purpleair-102"]  # low-confidence sensor dropped
    a, b = obs
    assert a.extra["epa_corrected"] and a.extra["pm25_ugm3"] == _aqi.epa_correct(60.0, 70)
    assert not b.extra["epa_corrected"] and b.value == _aqi.pm25_to_aqi(12.0)
    assert a.extra["kind"] == "aqi_sensor"


def test_tile_rule_median_then_airnow():
    city = load_city("miami")
    sensors = purpleair.parse(PA_JSON, city["air"])          # Doral: corrected ~31 ug/m3, and 12 ug/m3
    area = airnow.parse(AIRNOW_ROWS, city["air"])             # area worst = 112 (USG)
    tiles = {t["id"]: t for t in board(sensors + area, city)}
    d = tiles["doral"]["forces"]["air"]
    assert d["context"]["aqi"]["source"].startswith("median of 2")
    assert d["context"]["aqi"]["aqi"] == round((sensors[0].value + sensors[1].value) / 2)
    hb = tiles["miami-beach"]["forces"]["air"]                # no sensor near -> AirNow area AQI
    assert hb["context"]["aqi"]["aqi"] == 112 and hb["status"] == "watch"
    assert tiles["doral"]["forces"]["air"]["status"] == "ok"  # sensors near Doral override the area value


def test_demo_air_sensors_labelled_and_separate():
    city = load_city("miami")
    sims = demo_mode.air_sensors(city)
    assert len(sims) >= 2 and any(o.extra["category"] == "Unhealthy for Sensitive Groups" for o in sims)
    for o in sims:
        assert o.source == "demo_air" and o.extra["simulated"] is True
        assert o.place.name.startswith("SIMULATED") and o.extra["headline"].startswith("SIMULATED")
    tiles = {t["id"]: t for t in board(sims, city)}
    ctx = tiles["doral"]["forces"]["air"]["context"]["aqi"]
    assert tiles["doral"]["forces"]["air"]["status"] == "watch" and ctx["simulated"] is True
    assert tiles["homestead"]["forces"]["air"]["status"] == "unknown"


def test_air_tips_only_for_air_quality():
    from detect import messages
    st = {"water": "ok", "air": "watch", "land": "ok", "fire": "ok"}
    aq = messages._template("Doral", "watch", st, {"air": "air_quality"})
    storm = messages._template("Doral", "watch", st, {"air": "storm"})
    assert "windows" in aq["en"] and "ventanas" in aq["es"] and "fenèt" in aq["ht"]
    assert "windows" not in storm["en"] and "Hurricane" in storm["en"]
