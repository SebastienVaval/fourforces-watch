"""Offline tests for optional Sentry monitoring. No live project and no network."""
import os
import subprocess
import sys

from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

import app
import sentry_sdk
from adapters.base import SkipAdapter
from core.sentry import redact_secrets

DSN = "https://public@example.ingest.sentry.io/1"


class DropTransport(Transport):
    """Accepts events in memory so tests never open a socket."""

    envelopes: list = []

    def capture_envelope(self, envelope):
        DropTransport.envelopes.append(envelope)


def _shutdown_sentry():
    if sentry_sdk.is_initialized():
        sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)


def _route_paths():
    return [getattr(route, "path", None) for route in app.app.routes]


def _init_with_drop(monkeypatch):
    real_init = sentry_sdk.init

    def wrapped(**kwargs):
        kwargs["transport"] = DropTransport
        return real_init(**kwargs)

    monkeypatch.setattr(sentry_sdk, "init", wrapped)


def test_app_starts_without_sentry_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.delenv("SENTRY_DEBUG_ROUTE", raising=False)
    _shutdown_sentry()
    called = []
    real_init = sentry_sdk.init

    def spy(*args, **kwargs):
        called.append(kwargs.get("dsn", args[0] if args else None))
        return real_init(*args, **kwargs)

    monkeypatch.setattr(sentry_sdk, "init", spy)
    assert app.init_sentry() is False
    monkeypatch.setenv("SENTRY_DSN", "   ")
    assert app.init_sentry() is False
    assert called == []
    assert sentry_sdk.is_initialized() is False
    response = TestClient(app.app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "/sentry-debug" not in _route_paths()


def test_app_starts_with_sentry_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", DSN)
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)
    _shutdown_sentry()
    seen = {}
    real_init = sentry_sdk.init

    def wrapped(**kwargs):
        seen.update(kwargs)
        kwargs["transport"] = DropTransport
        return real_init(**kwargs)

    monkeypatch.setattr(sentry_sdk, "init", wrapped)
    try:
        assert app.init_sentry() is True
        assert seen["dsn"] == DSN
        assert seen["environment"] == "production"
        assert seen["traces_sample_rate"] == 0.1
        assert seen["send_default_pii"] is False
        assert seen["include_local_variables"] is False
        client = sentry_sdk.get_client()
        assert client.options["environment"] == "production"
        assert client.options["send_default_pii"] is False
        assert client.options["traces_sample_rate"] == 0.1
        names = [type(item).__name__ for item in client.integrations.values()]
        assert "FastApiIntegration" in names
        response = TestClient(app.app).get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
    finally:
        _shutdown_sentry()


def test_sentry_environment_and_sample_rate_come_from_env(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", DSN)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.25")
    _shutdown_sentry()
    _init_with_drop(monkeypatch)
    try:
        assert app.init_sentry() is True
        options = sentry_sdk.get_client().options
        assert options["environment"] == "staging"
        assert options["traces_sample_rate"] == 0.25
        assert options["send_default_pii"] is False
        assert TestClient(app.app).get("/healthz").json() == {"ok": True}
    finally:
        _shutdown_sentry()


def test_invalid_dsn_still_serves_healthz(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "not-a-dsn")
    _shutdown_sentry()
    assert app.init_sentry() is False
    assert sentry_sdk.is_initialized() is False
    assert TestClient(app.app).get("/healthz").status_code == 200


class _Boom:
    NAME = "airnow"
    FORCE = "air"

    def fetch(self, city):
        raise RuntimeError("airnow down API_KEY=airnow-secret-value")


class _Skip:
    NAME = "purpleair"
    FORCE = "air"

    def fetch(self, city):
        raise SkipAdapter("needs PURPLEAIR_API_KEY")


def _events():
    found = []
    for envelope in DropTransport.envelopes:
        event = envelope.get_event()
        if event:
            found.append(event)
    return found


def test_adapter_failure_is_reported_and_keeps_fallback(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", DSN)
    monkeypatch.setenv("AIRNOW_API_KEY", "airnow-secret-value")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0")
    DropTransport.envelopes = []
    _shutdown_sentry()
    _init_with_drop(monkeypatch)
    try:
        assert app.init_sentry() is True
        _mod, res, status = app._run_adapter(_Boom())
        assert res is None
        assert status["ok"] is False
        assert status["error"].startswith("airnow down")
        events = _events()
        assert events, "caught adapter exception was not sent to Sentry"
        blob = str(events[-1])
        assert "airnow-secret-value" not in blob
        assert events[-1].get("tags", {}).get("adapter") == "airnow"
        assert events[-1].get("tags", {}).get("force") == "air"
    finally:
        _shutdown_sentry()
        DropTransport.envelopes = []


def test_skipped_adapter_is_not_reported(monkeypatch):
    seen = []
    monkeypatch.setattr(app, "report_adapter_failure", lambda *args: seen.append(args))
    _mod, res, status = app._run_adapter(_Skip())
    assert res == []
    assert status == {"ok": False, "skipped": "needs PURPLEAIR_API_KEY"}
    assert seen == []


def test_redact_secrets_strips_feed_keys(monkeypatch):
    monkeypatch.setenv("AIRNOW_API_KEY", "airnow-secret-value")
    monkeypatch.setenv("FIRMS_MAP_KEY", "firms-map-key-value")
    text = (
        "https://www.airnowapi.org/aq/data/?API_KEY=airnow-secret-value&format=json "
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/firms-map-key-value/VIIRS/1"
    )
    cleaned = redact_secrets(text)
    assert "airnow-secret-value" not in cleaned
    assert "firms-map-key-value" not in cleaned
    assert "[redacted]" in cleaned
    query_only = redact_secrets("https://example.test/path?token=abcdefghij&x=1")
    assert "abcdefghij" not in query_only


def test_sentry_debug_route_disabled_by_default(monkeypatch):
    for value in (None, "", "0", "true"):
        if value is None:
            monkeypatch.delenv("SENTRY_DEBUG_ROUTE", raising=False)
        else:
            monkeypatch.setenv("SENTRY_DEBUG_ROUTE", value)
        app.install_sentry_debug_route()
        assert "/sentry-debug" not in _route_paths()
    monkeypatch.delenv("SENTRY_DEBUG_ROUTE", raising=False)
    response = TestClient(app.app).get("/sentry-debug", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["location"]


def test_sentry_debug_route_raises_when_enabled(monkeypatch):
    monkeypatch.setenv("SENTRY_DEBUG_ROUTE", "1")
    app.install_sentry_debug_route()
    try:
        assert "/sentry-debug" in _route_paths()
        client = TestClient(app.app, raise_server_exceptions=False)
        response = client.get("/sentry-debug", follow_redirects=False)
        assert response.status_code == 500
    finally:
        monkeypatch.delenv("SENTRY_DEBUG_ROUTE", raising=False)
        app.install_sentry_debug_route()
        assert "/sentry-debug" not in _route_paths()


def test_fresh_process_starts_with_and_without_dsn():
    """Import the app in a clean interpreter so import-time init sees the env."""
    script = r"""
import os, sys
mode = sys.argv[1]
os.environ["SENTRY_DEBUG_ROUTE"] = "0"
if mode == "off":
    os.environ["SENTRY_DSN"] = ""
else:
    os.environ["SENTRY_DSN"] = "https://public@example.ingest.sentry.io/1"
    os.environ["SENTRY_ENVIRONMENT"] = "ci"
    os.environ["SENTRY_TRACES_SAMPLE_RATE"] = "0"
import sentry_sdk
from sentry_sdk.transport import Transport

class Drop(Transport):
    def capture_envelope(self, envelope):
        pass

_real = sentry_sdk.init

def _wrapped(**kwargs):
    kwargs["transport"] = Drop
    return _real(**kwargs)

sentry_sdk.init = _wrapped
import app
from fastapi.testclient import TestClient
response = TestClient(app.app).get("/healthz")
assert response.status_code == 200, response.text
assert response.json() == {"ok": True}
paths = [getattr(route, "path", None) for route in app.app.routes]
assert "/sentry-debug" not in paths
if mode == "off":
    assert sentry_sdk.is_initialized() is False
else:
    assert sentry_sdk.is_initialized() is True
    options = sentry_sdk.get_client().options
    assert options["environment"] == "ci"
    assert options["traces_sample_rate"] == 0.0
    assert options["send_default_pii"] is False
print("ok")
"""
    for mode in ("off", "on"):
        proc = subprocess.run(
            [sys.executable, "-c", script, mode],
            cwd=str(app.ROOT),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
