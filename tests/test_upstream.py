"""Offline tests: a USGS 503 is retried, the last good reading stays up, and Sentry
hears about it only once the outage lasts. No live network."""
import httpx
import pytest

import app
from adapters.air import purpleair
from adapters.water import usgs_gauges
from core import http as core_http
from core.city import load_city

PA = {"fields": ["sensor_index", "name", "latitude", "longitude", "pm2.5_10minute",
                 "pm2.5_cf_1", "humidity", "last_seen", "confidence"],
      "data": [[101, "Doral A", 25.82, -80.355, 40.0, 60.0, 70, 1760115600, 100]]}


def _series():
    return {"sourceInfo": {"siteName": "MIAMI CANAL", "siteCode": [{"value": "02289500"}],
                           "geoLocation": {"geogLocation": {"latitude": 25.7617, "longitude": -80.1918}}},
            "variable": {"unit": {"unitCode": "ft"}},
            "values": [{"value": [
                {"value": "2.0", "dateTime": "2026-10-26T00:00:00.000-04:00", "qualifiers": ["P"]},
                {"value": "2.4", "dateTime": "2026-10-26T03:00:00.000-04:00", "qualifiers": ["P"]},
            ]}]}


def _body():
    return {"value": {"timeSeries": [_series()]}}


def _scripted(monkeypatch, module, script):
    """Serve ``script`` from the real retrying client. Each item is a status code,
    an exception, or ('json', payload)."""
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        item = script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, tuple) and item[0] == "json":
            return httpx.Response(200, json=item[1])
        return httpx.Response(item, text="unavailable")

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return core_http.client(*args, **kwargs)

    monkeypatch.setattr(module, "client", factory)
    monkeypatch.setattr(core_http, "sleep", lambda _seconds: None)
    return calls


def _quiet_app(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("ADAPTER_TRANSIENT_FAILURES_BEFORE_SENTRY", raising=False)
    for attr, val in (
        ("adapters", [usgs_gauges]), ("obs", {}), ("adapter_status", {}), ("detections", {}),
        ("rotation", 0), ("board", []), ("last_refresh", None), ("refreshing", False), ("ai_pending", False),
    ):
        monkeypatch.setattr(app.S, attr, val)


def test_retry_delay_is_exponential_with_jitter():
    assert core_http.RETRY_ATTEMPTS == 3
    assert core_http.retry_delay(0, rng=lambda: 0) == pytest.approx(0.25)
    assert core_http.retry_delay(0, rng=lambda: 1) == pytest.approx(0.5)
    assert core_http.retry_delay(1, rng=lambda: 1) == pytest.approx(1.0)
    assert core_http.retry_delay(2, rng=lambda: 1) == pytest.approx(2.0)
    assert core_http.retry_delay(20, rng=lambda: 1) == pytest.approx(core_http.RETRY_MAX_SECONDS)


def test_sentry_policy_and_threshold_env(monkeypatch):
    request = httpx.Request("GET", "https://waterservices.usgs.gov/nwis/iv/")
    busy = httpx.HTTPStatusError("503", request=request, response=httpx.Response(503, request=request))
    missing = httpx.HTTPStatusError("404", request=request, response=httpx.Response(404, request=request))
    limited = httpx.HTTPStatusError("429", request=request, response=httpx.Response(429, request=request))
    assert core_http.is_transient(busy) and core_http.is_transient(limited)
    assert core_http.is_transient(httpx.ReadTimeout("slow"))
    assert core_http.is_transient(httpx.ConnectError("refused"))
    assert not core_http.is_transient(missing)
    assert not core_http.is_transient(KeyError("value"))
    assert not core_http.is_transient(RuntimeError("bug"))
    monkeypatch.delenv("ADAPTER_TRANSIENT_FAILURES_BEFORE_SENTRY", raising=False)
    assert core_http.transient_failures_before_sentry() == 3
    assert not core_http.should_report(busy, 1) and not core_http.should_report(busy, 2)
    assert core_http.should_report(busy, 3)
    assert core_http.should_report(missing, 1) and core_http.should_report(KeyError("x"), 1)
    monkeypatch.setenv("ADAPTER_TRANSIENT_FAILURES_BEFORE_SENTRY", "nope")
    assert core_http.transient_failures_before_sentry() == 3
    monkeypatch.setenv("ADAPTER_TRANSIENT_FAILURES_BEFORE_SENTRY", "0")
    assert core_http.transient_failures_before_sentry() == 1
    monkeypatch.setenv("ADAPTER_TRANSIENT_FAILURES_BEFORE_SENTRY", "2")
    assert core_http.should_report(busy, 2) and not core_http.should_report(httpx.ConnectError("x"), 1)


def test_usgs_retries_503_then_parses(monkeypatch):
    calls = _scripted(monkeypatch, usgs_gauges, [503, 503, ("json", _body())])
    obs = usgs_gauges.fetch(load_city("miami"))
    assert len(calls) == 3
    assert calls[0].url.params["countyCd"] == "12086"
    assert "FourForcesWatch" in calls[0].headers["user-agent"]
    assert len(obs) == 1 and obs[0].value == 2.4 and obs[0].status == "ok"
    assert obs[0].extra.get("stale") is not True


def test_usgs_503_gives_up_after_three_and_400_is_not_retried(monkeypatch):
    calls = _scripted(monkeypatch, usgs_gauges, [503, 503, 503])
    with pytest.raises(httpx.HTTPStatusError) as exc:
        usgs_gauges.fetch(load_city("miami"))
    assert exc.value.response.status_code == 503 and len(calls) == 3

    calls = _scripted(monkeypatch, usgs_gauges, [400])
    with pytest.raises(httpx.HTTPStatusError) as exc:
        usgs_gauges.fetch(load_city("miami"))
    assert exc.value.response.status_code == 400 and len(calls) == 1


def test_usgs_retries_timeout_and_connection_error(monkeypatch):
    calls = _scripted(monkeypatch, usgs_gauges, [
        httpx.ReadTimeout("slow"), httpx.ConnectError("refused"), ("json", _body()),
    ])
    obs = usgs_gauges.fetch(load_city("miami"))
    assert len(calls) == 3 and obs[0].value == 2.4

    calls = _scripted(monkeypatch, usgs_gauges, [httpx.ReadTimeout("slow")] * 3)
    with pytest.raises(httpx.ReadTimeout):
        usgs_gauges.fetch(load_city("miami"))
    assert len(calls) == 3


def test_purpleair_retries_503_then_returns_sensors(monkeypatch):
    purpleair._cache.clear()
    monkeypatch.setenv("PURPLEAIR_API_KEY", "pa-key")
    monkeypatch.setenv("PURPLEAIR_REFRESH_SECONDS", "0")
    try:
        calls = _scripted(monkeypatch, purpleair, [503, ("json", PA)])
        obs = purpleair.fetch(load_city("miami"))
        assert len(calls) == 2 and obs[0].place.id == "purpleair-101"
        calls = _scripted(monkeypatch, purpleair, [503, 503, 503])
        with pytest.raises(httpx.HTTPStatusError):
            purpleair.fetch(load_city("miami"))
        assert len(calls) == 3
    finally:
        purpleair._cache.clear()


def test_usgs_503_keeps_last_good_reading_and_recovers(monkeypatch, caplog):
    """The production failure: USGS answers 503. One poll must not reach Sentry.
    Three polls in a row do. The next good response clears the stale flag."""
    caplog.set_level("WARNING", logger="app")
    _quiet_app(monkeypatch)
    script = []
    calls = _scripted(monkeypatch, usgs_gauges, script)
    reported = []

    def capture(exc, adapter, force, **tags):
        reported.append((type(exc), adapter, force, tags))

    monkeypatch.setattr(app, "report_adapter_failure", capture)

    script.append(("json", _body()))
    app.refresh()
    assert app.S.board and app.S.last_refresh
    status = app.S.adapter_status["usgs_gauges"]
    assert status["ok"] is True and status["consecutive_failures"] == 0
    assert "stale" not in status and reported == []
    last_ok = status["last_ok"]
    reading = app.S.obs["usgs_gauges"][0].value
    downtown = next(t for t in app.S.board if t["id"] == "downtown")
    assert downtown["forces"]["water"]["context"]["gauge"]["ft"] == reading
    assert "stale" not in downtown["forces"]["water"]["context"]["gauge"]
    assert not any(r.levelname == "ERROR" for r in caplog.records)

    for expected in (1, 2):
        script.extend([503, 503, 503])
        app.refresh()
        status = app.S.adapter_status["usgs_gauges"]
        assert status["ok"] is False and status["stale"] is True and status["transient"] is True
        assert status["consecutive_failures"] == expected and status["last_ok"] == last_ok
        assert status["count"] == 1 and reported == []
        kept = app.S.obs["usgs_gauges"][0]
        assert kept.value == reading and kept.extra["stale"] is True
        served = app.api_observations(force=None, source="usgs_gauges")
        assert served[0]["extra"]["stale"] is True and served[0]["value"] == reading
    assert any("transient upstream failure" in r.message and r.levelname == "WARNING" for r in caplog.records)
    assert not any(r.levelname == "ERROR" for r in caplog.records)
    downtown = next(t for t in app.S.board if t["id"] == "downtown")
    assert downtown["forces"]["water"]["context"]["gauge"]["stale"] is True

    script.extend([503, 503, 503])
    app.refresh()
    assert len(reported) == 1
    kind, adapter, force, tags = reported[0]
    assert kind is httpx.HTTPStatusError and adapter == "usgs_gauges" and force == "water"
    assert tags["consecutive_failures"] == "3" and tags["transient"] == "true"
    assert app.S.obs["usgs_gauges"][0].extra["stale"] is True
    assert len(calls) == 1 + 3 * 3  # one good poll, then three polls of three 503s

    script.append(("json", _body()))
    app.refresh()
    status = app.S.adapter_status["usgs_gauges"]
    assert status["ok"] is True and status["consecutive_failures"] == 0 and "stale" not in status
    assert app.S.obs["usgs_gauges"][0].extra.get("stale") is not True
    assert len(reported) == 1
    downtown = next(t for t in app.S.board if t["id"] == "downtown")
    assert "stale" not in downtown["forces"]["water"]["context"]["gauge"]


def test_first_503_does_not_crash_the_poll_or_alert(monkeypatch):
    _quiet_app(monkeypatch)
    script = [503, 503, 503]
    _scripted(monkeypatch, usgs_gauges, script)
    reported = []
    monkeypatch.setattr(app, "report_adapter_failure", lambda *a, **k: reported.append(a))
    app.refresh()
    assert app.S.board and app.S.last_refresh
    assert "usgs_gauges" not in app.S.obs
    status = app.S.adapter_status["usgs_gauges"]
    assert status["ok"] is False and status["transient"] is True and status["consecutive_failures"] == 1
    assert "stale" not in status and reported == []
    assert not app.S.refreshing


def test_parse_error_is_reported_immediately_and_keeps_last_reading(monkeypatch):
    _quiet_app(monkeypatch)
    script = [("json", _body()), ("json", {"unexpected": True})]
    calls = _scripted(monkeypatch, usgs_gauges, script)
    reported = []
    monkeypatch.setattr(app, "report_adapter_failure", lambda exc, adapter, force, **tags: reported.append(type(exc)))
    app.refresh()
    reading = app.S.obs["usgs_gauges"][0].value
    app.refresh()
    assert reported == [KeyError]
    assert len(calls) == 2  # a 200 with a bad body is not retried
    status = app.S.adapter_status["usgs_gauges"]
    assert status["transient"] is False and status["stale"] is True and status["consecutive_failures"] == 1
    assert app.S.obs["usgs_gauges"][0].value == reading and app.S.obs["usgs_gauges"][0].extra["stale"] is True
