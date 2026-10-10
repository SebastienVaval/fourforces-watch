"""Offline tests for the Grok (xAI) path: vision verdict parsing, status thresholds, image-hash cache,
simulated-vs-real separation, message fallback and the demo-banner condition. xAI HTTP is mocked."""
import json
from pathlib import Path

import pytest

from detect import grok, messages
from core.schema import Observation, Place

ROOT = Path(__file__).resolve().parent.parent


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload or {}, text

    def json(self):
        return self._p


def _reply(text):
    return _Resp(payload={"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]})


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setattr(grok, "_cache", {})
    monkeypatch.setattr(grok, "CACHE_PATH", tmp_path / "grok_vision.json")
    monkeypatch.setattr(messages, "_cache", {})


def _mock_post(monkeypatch, *responses):
    calls = []

    def post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "body": json, "headers": headers})
        r = responses[min(len(calls), len(responses)) - 1]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(grok.httpx, "post", post)
    return calls


def test_vision_yes_verdict_and_payload(monkeypatch):
    calls = _mock_post(monkeypatch, _reply('{"water_on_road": true, "confidence": 0.88, "note": "Standing water"}'))
    r = grok.classify_image(b"img-yes")
    assert r["water_on_road"] is True and r["confidence"] == 0.88 and r["model"] == grok.vision_model()
    assert r["cached"] is False and grok.status_from(r) == "alert"
    body = calls[0]["body"]
    assert calls[0]["url"].endswith("/responses") and calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert body["model"] == grok.vision_model() and body["store"] is False
    img = body["input"][0]["content"][0]
    assert img["type"] == "input_image" and img["image_url"].startswith("data:image/jpeg;base64,")


def test_vision_no_verdict_with_markdown_fences(monkeypatch):
    _mock_post(monkeypatch, _reply('```json\n{"water_on_road": false, "confidence": 0.95, "note": "Dry"}\n```'))
    r = grok.classify_image(b"img-no")
    assert r["water_on_road"] is False and grok.status_from(r) == "ok"


def test_vision_output_text_shortcut(monkeypatch):
    _mock_post(monkeypatch, _Resp(payload={"output_text": '{"water_on_road": true, "confidence": 0.4}'}))
    assert grok.status_from(grok.classify_image(b"img-ot")) == "watch"


def test_vision_malformed_json_is_unknown_and_not_cached(monkeypatch):
    _mock_post(monkeypatch, _reply("I think there is some water {not json"))
    r = grok.classify_image(b"img-bad")
    assert r["water_on_road"] is None and grok.status_from(r) == "unknown"
    assert r["image_sha256"] not in grok._cache


def test_vision_http_error_degrades(monkeypatch):
    _mock_post(monkeypatch, _Resp(status=429, text="rate limited"))
    r = grok.classify_image(b"img-429")
    assert r["water_on_road"] is None and r["note"].startswith("error: xAI API 429") and grok.status_from(r) == "unknown"


def test_vision_without_key_never_calls_api(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY")
    calls = _mock_post(monkeypatch, _reply("{}"))
    r = grok.classify_image(b"img-nokey")
    assert calls == [] and r["note"] == "no XAI_API_KEY" and grok.status_from(r) == "unknown"


@pytest.mark.parametrize("res,status", [
    ({"water_on_road": True, "confidence": 0.6}, "alert"),
    ({"water_on_road": True, "confidence": 0.59}, "watch"),
    ({"water_on_road": True, "confidence": None}, "watch"),
    ({"water_on_road": False, "confidence": 0.99}, "ok"),
    ({"water_on_road": None, "confidence": 0.9}, "unknown"),
])
def test_status_from_thresholds(res, status):
    assert grok.status_from(res) == status


def test_cache_by_image_hash(monkeypatch):
    calls = _mock_post(monkeypatch, _reply('{"water_on_road": true, "confidence": 0.9, "note": "x"}'),
                       _reply('{"water_on_road": false, "confidence": 0.9, "note": "y"}'))
    a = grok.classify_image(b"same-bytes")
    b = grok.classify_image(b"same-bytes")
    assert len(calls) == 1 and b["cached"] is True and b["water_on_road"] is True
    assert a["image_sha256"] == b["image_sha256"]
    assert json.loads(grok.CACHE_PATH.read_text())[a["image_sha256"]]["water_on_road"] is True
    c = grok.classify_image(b"other-bytes")
    assert len(calls) == 2 and c["water_on_road"] is False and c["cached"] is False


def _cam(sim):
    return Observation(force="water", source="demo_cameras" if sim else "fl511_cameras",
                       place=Place(id="cam-1", name="I-95 @ Test", lat=25.76, lon=-80.19),
                       time="2026-10-10T18:00:00Z", measurement="water_on_road", status="unknown",
                       extra={"simulated": sim})


def test_simulated_and_real_verdicts_never_mix():
    import app
    det = {"water_on_road": True, "confidence": 0.9, "note": "water", "model": "grok-4.7", "simulated": True}
    app.S.detections["cam-1"] = det
    try:
        real = _cam(False)
        app._apply_detection(real)
        assert real.status == "unknown" and "detection" not in real.extra
        sim = _cam(True)
        app._apply_detection(sim)
        assert sim.status == "alert" and sim.extra["headline"].startswith("SIMULATED: ")
        app.S.detections["cam-1"] = det | {"simulated": False}
        real2 = _cam(False)
        app._apply_detection(real2)
        assert real2.status == "alert" and not real2.extra["headline"].startswith("SIMULATED")
    finally:
        app.S.detections.pop("cam-1", None)


ST = {"water": "alert", "air": "ok", "land": "ok", "fire": "ok"}


def test_message_written_by_grok(monkeypatch):
    calls = _mock_post(monkeypatch, _reply('{"en": "Flooding.", "es": "Inundación.", "ht": "Inondasyon."}'))
    m = messages.neighborhood_message("Miami", "Doral", "alert", ST, ["Flood Warning by NWS"])
    assert m["by"] == grok.text_model() and m["es"] == "Inundación." and calls[0]["body"]["model"] == grok.text_model()


@pytest.mark.parametrize("resp", [_Resp(status=500, text="boom"), RuntimeError("network down"), _reply("not json")])
def test_message_falls_back_to_template_on_api_error(monkeypatch, resp):
    _mock_post(monkeypatch, resp)
    m = messages.neighborhood_message("Miami", "Doral", "alert", ST, ["Flood Warning by NWS"])
    assert m["by"] == "template" and all(m[k] for k in ("en", "es", "ht"))
    assert messages._cache == {}  # fallback is not cached, so Grok is retried on the next refresh


def test_demo_banner_aqi_phrase_only_when_simulated_aqi_active():
    html = (ROOT / "web" / "index.html").read_text()
    js = (ROOT / "web" / "app.js").read_text()
    assert '<span id="bannerAqi">' in html and "SIMULATED AQI" in html.split('id="bannerAqi"')[1].split("</span>")[0]
    assert "getElementById('bannerAqi').classList.toggle('hidden', !o.some(x => x.source === 'demo_air'))" in js
    src = (ROOT / "demo" / "demo_mode.py").read_text()
    assert 'source="demo_air"' in src
