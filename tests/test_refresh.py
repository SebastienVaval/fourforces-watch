"""Offline tests for the fast board publish: the Hazard Board appears before any Grok work finishes,
Grok work is bounded (timeout, concurrency, cameras per cycle), a read-only disk never breaks a refresh,
and the 'Messages written by' label tells the truth. No network: adapters and xAI are mocked."""
import threading
import time
import types

import pytest

import app
from core.schema import Observation, Place
from detect import grok, messages

WEB_JS = (app.ROOT / "web" / "app.js").read_text()


def _cam(i):
    return Observation(force="water", source="fl511_cameras", place=Place(id=f"cam-{i}", name=f"Cam {i}",
                       lat=25.77 + i * 0.001, lon=-80.19), time="2026-10-10T20:00:00Z",
                       measurement="water_on_road", status="unknown", extra={"image_url": f"http://x/{i}.jpg"})


@pytest.fixture
def fresh_state(monkeypatch, tmp_path):
    """Isolated app state: one fake camera adapter, demo mode off, xAI key 'present', caches empty."""
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setattr(grok, "_cache", {})
    monkeypatch.setattr(grok, "CACHE_PATH", tmp_path / "grok_vision.json")
    monkeypatch.setattr(messages, "_cache", {})
    cams = [_cam(i) for i in range(30)]
    fake = types.SimpleNamespace(NAME="fl511_cameras", FORCE="water", __doc__="Fake cameras", fetch=lambda city: cams)
    for attr, val in (("adapters", [fake]), ("obs", {}), ("adapter_status", {}), ("detections", {}), ("rotation", 0),
                      ("board", []), ("last_refresh", None), ("refreshing", False), ("ai_pending", False)):
        monkeypatch.setattr(app.S, attr, val)
    monkeypatch.setattr(app, "_fetch_image", lambda cam: (cam.place.id.encode() * 300, "image/jpeg"))
    return cams


def test_board_published_before_slow_grok_finishes(fresh_state, monkeypatch):
    gate = threading.Event()
    vision_calls = []

    def slow_post(url, json=None, headers=None, timeout=None):  # Grok "hangs" until the test releases it
        gate.wait(10)
        model = json["model"]
        if model == grok.vision_model():
            vision_calls.append(1)
            text = '{"water_on_road": false, "confidence": 0.9, "note": "dry"}'
        else:
            text = '{"en": "All clear.", "es": "Todo bien.", "ht": "Tout bagay anfòm."}'
        return types.SimpleNamespace(status_code=200, text="", json=lambda: {"output_text": text})
    monkeypatch.setattr(grok.httpx, "post", slow_post)

    t = threading.Thread(target=app.refresh)
    t0 = time.time()
    t.start()
    deadline = time.time() + 5
    while not app.S.board and time.time() < deadline:
        time.sleep(0.02)
    try:
        assert app.S.board, "board not published while Grok was still running"
        assert time.time() - t0 < 5 and app.S.last_refresh and app.S.ai_pending
        assert all(tile["message"]["by"] == "template" for tile in app.S.board)
        b = app.api_board()
        assert b["tiles"] and b["ai_pending"] is True and b["message_label"] == "templates (Grok messages loading…)"
        assert app.api_status()["last_refresh"] == app.S.last_refresh
    finally:
        gate.set()
        t.join(30)
    assert not t.is_alive() and not app.S.ai_pending
    assert len(vision_calls) == app.MAX_CLASSIFY  # capped cameras per cycle, not all 30
    assert all(tile["message"]["by"] == grok.text_model() for tile in app.S.board)
    assert app.api_board()["message_label"] == grok.text_model()


def test_refresh_survives_unwritable_cache(fresh_state, monkeypatch, tmp_path):
    """Root cause on Render: /app is root-owned, so writing .cache/ raised and aborted every refresh."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setattr(grok, "CACHE_PATH", blocker / "grok_vision.json")  # mkdir fails: parent is a file
    monkeypatch.setattr(grok.httpx, "post", lambda url, json=None, headers=None, timeout=None: types.SimpleNamespace(
        status_code=200, text="", json=lambda: {"output_text": '{"water_on_road": false, "confidence": 0.9}'}))
    r = grok.classify_image(b"some-image")
    assert r["water_on_road"] is False and grok._cache  # kept in memory, no exception
    app.refresh()
    assert app.S.board and app.S.last_refresh and app.S.ai_pending is False


def test_one_failing_camera_never_aborts_refresh(fresh_state, monkeypatch):
    monkeypatch.setattr(app, "classify_camera", lambda cam: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(messages, "neighborhood_message", lambda *a, **k: {"en": "x", "es": "x", "ht": "x",
                                                                           "by": "template"})
    app.refresh()
    assert app.S.board and app.S.last_refresh


def test_no_key_publishes_templates_without_calling_grok(fresh_state, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY")
    monkeypatch.setattr(grok.httpx, "post", lambda *a, **k: pytest.fail("Grok called without a key"))
    app.refresh()
    b = app.api_board()
    assert b["tiles"] and b["ai_pending"] is False and b["message_label"] == "templates (no xAI key)"


@pytest.mark.parametrize("by,key,pending,label", [
    ("template", False, False, "templates (no xAI key)"),
    ("template", True, True, "templates (Grok messages loading…)"),
    ("template", True, False, "templates (Grok unavailable)"),
    ("grok-4.20-0309-non-reasoning", True, False, "grok-4.20-0309-non-reasoning"),
    ("grok-4.20-0309-non-reasoning", True, True, "grok-4.20-0309-non-reasoning"),
])
def test_message_label(by, key, pending, label):
    assert app.message_label([{"message": {"by": "template"}}, {"message": {"by": by}}], key, pending) == label
    assert app.message_label([], False, False) == "templates (no xAI key)"
    assert app.message_label([], True, False) == "templates (Grok messages loading…)"  # before first publish


def test_web_label_uses_server_label_and_keeps_ids():
    assert 'id="msgModel"' in (app.ROOT / "web" / "index.html").read_text()
    assert "msgLabel(BOARD, STATUS)" in WEB_JS and "board.message_label" in WEB_JS
    for s in ("templates (no xAI key)", "templates (Grok messages loading…)"):
        assert s in WEB_JS


def test_grok_call_timeout_default(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    seen = []
    monkeypatch.setattr(grok.httpx, "post", lambda url, json=None, headers=None, timeout=None: (
        seen.append(timeout), types.SimpleNamespace(status_code=200, text="", json=lambda: {"output_text": "ok"}))[1])
    assert grok.respond([{"type": "input_text", "text": "hi"}], "m") == "ok"
    assert seen == [grok.TIMEOUT] and grok.TIMEOUT <= 30


def test_grok_concurrency_capped(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    lock, state = threading.Lock(), {"now": 0, "max": 0}

    def post(url, json=None, headers=None, timeout=None):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return types.SimpleNamespace(status_code=200, text="", json=lambda: {"output_text": "ok"})
    monkeypatch.setattr(grok.httpx, "post", post)
    threads = [threading.Thread(target=grok.respond, args=([{"type": "input_text", "text": "x"}], "m"))
               for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert state["max"] == grok.CONCURRENCY == 4


def test_messages_ai_false_never_calls_grok_but_reuses_its_text(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setattr(messages, "_cache", {})
    calls = []
    monkeypatch.setattr(grok, "generate_text", lambda p, max_tokens=400: (calls.append(1),
                        '{"en": "A", "es": "B", "ht": "C"}')[1])
    st = {"water": "ok", "air": "ok", "land": "ok", "fire": "ok"}
    assert messages.neighborhood_message("Miami", "Brickell", "ok", st, [], ai=False)["by"] == "template"
    assert calls == []
    assert messages.neighborhood_message("Miami", "Brickell", "ok", st, [])["by"] == grok.text_model()
    assert messages.neighborhood_message("Miami", "Brickell", "ok", st, [], ai=False)["by"] == grok.text_model()
    assert calls == [1]
