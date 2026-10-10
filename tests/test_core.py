"""Offline tests: exports, rule engine, NWS classification, AQI, heat index."""
import xml.etree.ElementTree as ET

from adapters.air._aqi import pm25_to_aqi
from adapters.fire.heat_index import heat_index_f
from adapters.nws import classify, status_for
from core.city import load_city
from core.schema import Observation, Place, to_cap, to_geojson
from forces.engine import board


def _obs(force, status, lat=25.7617, lon=-80.1918, **extra):
    return Observation(force=force, source="test", place=Place(id=f"t-{force}", name="Test", lat=lat, lon=lon),
                       time="2026-10-10T15:00:00Z", measurement="m", value=1, unit="u", threshold=0,
                       status=status, extra=extra)


def test_geojson_and_cap():
    obs = [_obs("water", "alert"), _obs("air", "ok")]
    assert len(to_geojson(obs)["features"]) == 2
    xml = to_cap(obs).split("\n", 1)[1]
    assert len(ET.fromstring(xml).findall("{urn:oasis:names:tc:emergency:cap:1.2}alert")) == 1


def test_board_worst_status():
    tiles = {t["id"]: t for t in board([_obs("water", "alert"), _obs("fire", "watch", scope="area")], load_city("miami"))}
    assert tiles["downtown"]["forces"]["water"]["status"] == "alert"
    assert tiles["homestead"]["forces"]["water"]["status"] == "unknown"
    assert tiles["homestead"]["forces"]["fire"]["status"] == "watch"


def test_nws_classify():
    assert classify("Storm Surge Warning") == "water"
    assert classify("Tropical Storm Warning") == "air"
    assert classify("Extreme Heat Warning") == "fire"
    assert classify("Evacuation Immediate") == "land"
    assert status_for("Coastal Flood Statement", "Minor") == "watch"
    assert status_for("Flood Warning", "Moderate") == "alert"


def test_aqi_and_heat_index():
    assert pm25_to_aqi(9.0) == 50 and pm25_to_aqi(35.4) == 100
    assert 100 <= heat_index_f(90, 70) <= 108


def test_grok_without_key(monkeypatch):
    from detect import grok, messages
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    r = grok.classify_image(b"\xff\xd8not-really-a-jpeg")
    assert r["water_on_road"] is None and grok.status_from(r) == "unknown"
    m = messages.neighborhood_message("Miami", "Brickell", "watch", {"water": "watch", "air": "ok", "land": "ok", "fire": "ok"}, [])
    assert m["by"] == "template" and set(m) >= {"en", "es", "ht"}


def test_grok_response_parsing():
    from detect import grok
    resp = {"output": [{"type": "reasoning"}, {"type": "message", "content": [
        {"type": "output_text", "text": '{"water_on_road": true, "confidence": 0.9, "note": "street flooded"}'}]}]}
    j = grok.parse_json(grok._output_text(resp))
    assert j["water_on_road"] is True
    assert grok.status_from({"water_on_road": True, "confidence": 0.9}) == "alert"
    assert grok.status_from({"water_on_road": True, "confidence": 0.4}) == "watch"


def test_messages_built_from_simulated_facts_are_labelled(monkeypatch):
    from detect import grok, messages
    st = {"water": "alert", "air": "ok", "land": "ok", "fire": "ok"}
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    m = messages.neighborhood_message("Miami", "Brickell", "alert", st, ["SIMULATED: Water on road seen by camera X"])
    assert m["en"].startswith("[SIMULATED demo]") and m["es"].startswith("[Demo SIMULADA]") and m["simulated"]
    monkeypatch.setenv("XAI_API_KEY", "test")
    monkeypatch.setattr(grok, "generate_text", lambda *a, **k: '{"en": "Water on roads.", "es": "Agua.", "ht": "Dlo."}')
    g = messages.neighborhood_message("Miami", "Little Havana", "alert", st, ["SIMULATED: Water on road seen by camera Y"])
    assert g["by"] != "template" and g["en"] == "[SIMULATED demo] Water on roads." and g["ht"].startswith("[Demo SIMILE]")
    real = messages.neighborhood_message("Miami", "Doral", "alert", st, ["Flood Warning by NWS"])
    assert not real["en"].startswith("[") and "simulated" not in real
