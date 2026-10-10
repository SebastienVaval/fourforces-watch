"""Offline tests for the air force: AQI math, EPA correction, AirNow/PurpleAir (mocked HTTP), tile rule, demo labelling."""
import httpx
import pytest

from adapters.air import _aqi, airnow, purpleair
from adapters.base import SkipAdapter
from core.city import load_city
from demo import demo_mode
from forces import air
from forces.engine import board

AIRNOW_ROWS = [  # /aq/data/ verbose=1 shape
    {"Latitude": 25.686942, "Longitude": -80.399988, "UTC": "2026-10-10T16:00", "Parameter": "PM2.5", "Unit": "UG/M3",
     "AQI": 30, "Category": 1, "SiteName": "Kendall", "FullAQSCode": "120860034"},
    {"Latitude": 25.686942, "Longitude": -80.399988, "UTC": "2026-10-10T17:00", "Parameter": "PM2.5", "Unit": "UG/M3",
     "AQI": 112, "Category": 3, "SiteName": "Kendall", "FullAQSCode": "120860034"},
    {"Latitude": 25.7325, "Longitude": -80.162201, "UTC": "2026-10-10T17:00", "Parameter": "OZONE", "Unit": "PPB",
     "AQI": 24, "Category": 1, "SiteName": "Rosenstiel", "FullAQSCode": "120860027"},
    {"Latitude": 25.7325, "Longitude": -80.162201, "UTC": "2026-10-10T17:00", "Parameter": "PM10", "Unit": "UG/M3",
     "AQI": -999, "Category": 0, "SiteName": "Rosenstiel", "FullAQSCode": "120860027"},
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
    assert seen[0].url.path == "/aq/data/" and q["API_KEY"] == "test-key" and q["dataType"] == "A"
    assert q["BBOX"] == "-80.87,25.13,-80.11,25.98" and "PM25" in q["parameters"] and "OZONE" in q["parameters"]
    assert len(q["startDate"]) == 13 and q["startDate"] < q["endDate"]  # YYYY-MM-DDTHH, UTC
    assert [(o.extra["site"], o.extra["parameter"], o.value) for o in obs] == [
        ("Rosenstiel", "OZONE", 24), ("Kendall", "PM2.5", 112)]  # latest hour kept, negative AQI dropped
    k = obs[1]
    assert k.status == "watch" and k.extra["kind"] == "aqi_sensor" and k.extra["network"] == "AirNow"
    assert k.time == "2026-10-10T17:00:00Z" and k.place.lat == 25.686942


def test_airnow_web_service_error(monkeypatch):
    monkeypatch.setenv("AIRNOW_API_KEY", "test-key")
    retired = {"WebServiceError": [{"Message": "This web service has been retired as of October 1, 2026."}]}
    _mock(monkeypatch, airnow, retired)
    with pytest.raises(RuntimeError, match="retired"):
        airnow.fetch(load_city("miami"))
    _mock(monkeypatch, airnow, {"WebServiceError": [{"Message": "Invalid API key"}]})
    with pytest.raises(SkipAdapter, match="Invalid API key"):
        airnow.fetch(load_city("miami"))
    _mock(monkeypatch, airnow, {}, status=401)
    with pytest.raises(SkipAdapter):
        airnow.fetch(load_city("miami"))


def test_airnow_window_format():
    from datetime import datetime, timezone
    assert airnow.window(datetime(2026, 10, 10, 18, 37, tzinfo=timezone.utc), 3) == ("2026-10-10T15", "2026-10-10T18")


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
    sensors = purpleair.parse(PA_JSON, city["air"])          # Doral: two PurpleAir sensors
    official = airnow.parse(AIRNOW_ROWS, city["air"])         # Kendall PM2.5 112 (USG), Rosenstiel O3 24
    tiles = {t["id"]: t for t in board(sensors + official, city)}
    d = tiles["doral"]["forces"]["air"]
    assert d["context"]["aqi"]["source"].startswith("median of 2")
    assert d["context"]["aqi"]["aqi"] == round((sensors[0].value + sensors[1].value) / 2)
    assert d["status"] == "ok"                                # sensors near Doral override the city-wide value
    kb = tiles["key-biscayne"]["forces"]["air"]               # Rosenstiel monitor ~4.3 km away
    assert kb["context"]["aqi"]["aqi"] == 24 and "AirNow" in kb["context"]["aqi"]["source"]
    hb = tiles["miami-beach"]["forces"]["air"]                # nothing within 5 km -> worst AirNow monitor
    assert hb["context"]["aqi"]["aqi"] == 112 and hb["status"] == "watch"
    assert hb["context"]["aqi"]["source"].startswith("AirNow area, worst monitor: Kendall")


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
