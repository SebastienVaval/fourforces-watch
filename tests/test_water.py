"""Offline tests for the water force: tide build (predictions, trend, next high), USGS gauge rule,
NWS mapping, flood-zone context, tile rule and SIMULATED labelling."""
from datetime import datetime, timezone

from adapters.nws import classify
from adapters.water import flood_zones, noaa_tide, usgs_gauges
from core.city import load_city
from core.schema import Observation, Place
from forces.engine import board

CFG = {"station": "8723214", "datum": "MLLW", "watch_ft": 3.0, "minor_flood_ft": 3.53,
       "moderate_flood_ft": 3.93, "major_flood_ft": 4.73}
NOW = datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc)
LATEST = {"metadata": {"id": "8723214", "name": "Virginia Key", "lat": "25.7314", "lon": "-80.1618"},
          "data": [{"t": "2026-10-10 18:00", "v": "1.60"}]}
PRED6 = {"predictions": [{"t": "2026-10-10 18:00", "v": "0.90"}, {"t": "2026-10-10 19:00", "v": "1.30"}]}
HILO = {"predictions": [{"t": "2026-10-10 15:20", "v": "0.20", "type": "L"},
                        {"t": "2026-10-10 21:33", "v": "2.79", "type": "H"}]}


def _cam(status, lat=25.7620, lon=-80.1920, sim=False):
    return Observation(force="water", source="fl511_cameras", place=Place(id=f"cam-{status}-{lat}", name="I-95 @ Test",
                       lat=lat, lon=lon), time="2026-10-10T18:00:00Z", measurement="water_on_road", status=status,
                       extra={"simulated": sim})


def test_tide_build_trend_and_next_high():
    o = noaa_tide.build(LATEST, PRED6, HILO, CFG, NOW)
    assert o.value == 1.6 and o.extra["predicted"] == 0.9 and o.extra["anomaly_ft"] == 0.7
    assert o.extra["trend"] == "rising"
    assert o.extra["next_high"] == {"time": "2026-10-10T21:33:00Z", "predicted_ft": 2.79, "projected_ft": 3.49}
    high = noaa_tide.build({**LATEST, "data": [{"t": "2026-10-10 18:00", "v": "3.60"}]}, PRED6, HILO, CFG, NOW)
    assert high.status == "alert" and high.extra["flood_level"] == "minor"


def test_tide_status_thresholds():
    o = noaa_tide.build(LATEST, PRED6, HILO, CFG, NOW)
    # 1.60 ft is below watch (3.0); projected next high 3.49 < minor 3.53 -> ok
    assert o.extra["next_high"]["projected_ft"] == 3.49 and o.status == "ok"
    near = noaa_tide.build(LATEST, PRED6, {"predictions": [{"t": "2026-10-10 21:33", "v": "2.90", "type": "H"}]}, CFG, NOW)
    assert near.status == "watch"  # projected 3.60 >= minor flood


def test_usgs_parse_rapid_rise_and_site_threshold():
    def ts(site, vals):
        return {"sourceInfo": {"siteName": f"CANAL {site}", "siteCode": [{"value": site}],
                               "geoLocation": {"geogLocation": {"latitude": 25.8, "longitude": -80.3}}},
                "variable": {"unit": {"unitCode": "ft"}},
                "values": [{"value": [{"value": str(v), "dateTime": "2026-10-10T13:00:00.000-04:00", "qualifiers": ["P"]}
                                      for v in vals]}]}
    obs = usgs_gauges.parse([ts("1", [2.0, 2.1]), ts("2", [2.0, 2.7]), ts("3", [5.0, 5.1]), ts("4", [-999999])],
                            {"rapid_rise_ft_3h": 0.5, "site_thresholds": {"3": {"watch": 4.5, "alert": 5.0}}})
    st = {o.extra["site_no"]: o.status for o in obs}
    assert st == {"1": "ok", "2": "watch", "3": "alert"}
    assert obs[0].time == "2026-10-10T17:00:00Z" and obs[0].extra["provisional"] is True


def test_nws_water_mapping():
    for ev in ("Flood Warning", "Coastal Flood Advisory", "Storm Surge Warning", "Flash Flood Watch"):
        assert classify(ev) == "water"


def test_flood_zone_context_and_never_a_status():
    city = load_city("miami")
    hood = next(n for n in city["neighborhoods"] if n["id"] == "downtown")
    fz = flood_zones.observation(hood, {"FZONE": "AE", "ELEV": 12}, "FZONE", "Miami-Dade County Open Data")
    assert fz.extra["reference"] and fz.extra["meaning"].startswith("1% annual chance")
    tiles = {t["id"]: t for t in board([fz], city)}
    w = tiles["downtown"]["forces"]["water"]
    assert w["status"] == "unknown" and w["context"]["flood_zone"]["zone"] == "AE"
    assert "flood_zone" not in tiles["hialeah"]["forces"]["water"]["context"]


def test_tile_rule_cameras_tide_coastal_only():
    city = load_city("miami")
    tide = noaa_tide.build({**LATEST, "data": [{"t": "2026-10-10 18:00", "v": "3.60"}]}, PRED6, HILO, CFG, NOW)
    tiles = {t["id"]: t for t in board([tide, _cam("ok")], city)}
    assert tiles["downtown"]["forces"]["water"]["status"] == "alert"      # coastal zone FLZ173
    assert tiles["hialeah"]["forces"]["water"]["status"] == "unknown"     # inland zone: tide does not count
    ctx = tiles["downtown"]["forces"]["water"]["context"]
    assert ctx["tide"]["applies"] and ctx["camera"]["verdict"] == "dry"
    assert tiles["hialeah"]["forces"]["water"]["context"]["tide"]["applies"] is False


def test_nearest_camera_prefers_wet_and_labels_simulated():
    city = load_city("miami")
    cams = [_cam("ok", 25.7618, -80.1919), _cam("alert", 25.7700, -80.1950, sim=True), _cam("unknown", 25.7617, -80.1918)]
    tiles = {t["id"]: t for t in board(cams, city)}
    c = tiles["downtown"]["forces"]["water"]["context"]["camera"]
    assert c["status"] == "alert" and c["verdict"] == "water on road" and c["simulated"] is True and c["n_wet"] == 1
    assert tiles["downtown"]["forces"]["water"]["status"] == "alert"


def test_water_tip_only_when_water_is_the_cause():
    from detect import messages
    wet = messages._template("Brickell", "watch", {"water": "watch", "air": "ok", "land": "ok", "fire": "ok"})
    dry = messages._template("Brickell", "watch", {"water": "ok", "air": "ok", "land": "ok", "fire": "watch"})
    assert "flooded roads" in wet["en"] and "inundadas" in wet["es"] and "inonde" in wet["ht"]
    assert "flooded" not in dry["en"]
