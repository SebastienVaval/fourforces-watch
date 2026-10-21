"""Offline tests for the dashboard session gate. No network."""
import os
from pathlib import Path

from fastapi.testclient import TestClient

import core.auth as auth

ROOT = Path(__file__).resolve().parents[1]


def _client():
    import app
    return TestClient(app.app)


def _path(response) -> str:
    loc = response.headers["location"]
    if loc.startswith("http://") or loc.startswith("https://"):
        from urllib.parse import urlparse
        parsed = urlparse(loc)
        return parsed.path + (("?" + parsed.query) if parsed.query else "")
    return loc


def _cookie_flags(response) -> list[str]:
    return [part.strip().lower() for part in response.headers["set-cookie"].split(";")]


def test_healthz_stays_open_without_a_session():
    response = _client().get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_healthz_stays_open_when_sign_in_is_not_configured(unconfigured):
    response = _client().get("/healthz")
    assert response.status_code == 200 and response.json() == {"ok": True}


def test_pages_redirect_and_data_returns_401():
    client = _client()
    page = client.get("/", follow_redirects=False)
    assert page.status_code == 302
    assert _path(page).startswith("/login?next=")
    docs = client.get("/docs", follow_redirects=False)
    assert docs.status_code == 302 and _path(docs).startswith("/login")
    redoc = client.get("/redoc", follow_redirects=False)
    assert redoc.status_code == 302 and _path(redoc).startswith("/login")

    for method, path in (
        ("GET", "/api/status"),
        ("GET", "/api/observations"),
        ("GET", "/api/board"),
        ("GET", "/api/hazards"),
        ("GET", "/api/geojson"),
        ("GET", "/api/cap"),
        ("GET", "/api/config"),
        ("GET", "/api/overlays"),
        ("GET", "/api/cameras"),
        ("GET", "/api/tide"),
        ("GET", "/openapi.json"),
        ("GET", "/demo-images/anything.jpg"),
        ("POST", "/api/refresh"),
        ("POST", "/api/cameras/cam-1/check"),
    ):
        response = client.request(method, path, follow_redirects=False)
        assert response.status_code == 401, path
        assert response.json() == {"detail": "Not authenticated"}
        assert "text/html" not in response.headers["content-type"]


def test_login_page_matches_the_site_and_static_css_stays_available():
    client = _client()
    page = client.get("/login")
    assert page.status_code == 200
    assert "FourForces Watch" in page.text and "Sign in" in page.text
    assert 'href="/static/style.css"' in page.text
    assert 'class="logo"' in page.text
    assert "not configured" not in page.text.lower()
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_missing_env_fails_closed(unconfigured):
    client = _client()
    page = client.get("/login")
    assert page.status_code == 200
    assert "DASHBOARD_USERNAME" in page.text
    assert "DASHBOARD_PASSWORD" in page.text
    assert "DASHBOARD_SESSION_SECRET" in page.text
    assert "no default password" in page.text.lower()
    assert "<form" not in page.text
    posted = client.post("/login", data={"username": "someone", "password": "guess"}, follow_redirects=False)
    assert posted.status_code == 401
    assert "set-cookie" not in posted.headers
    assert "no default password" in posted.text.lower()
    assert client.get("/api/board", follow_redirects=False).status_code == 401
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 302


def test_partial_env_fails_closed(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "correct-horse")
    monkeypatch.delenv("DASHBOARD_SESSION_SECRET", raising=False)
    page = _client().get("/login")
    assert "not configured" in page.text.lower()
    assert "<form" not in page.text


def test_wrong_password_and_wrong_username_look_the_same():
    client = _client()
    user = os.environ["DASHBOARD_USERNAME"]
    password = os.environ["DASHBOARD_PASSWORD"]
    bad_user = client.post("/login", data={"username": "not-" + user, "password": password}, follow_redirects=False)
    bad_password = client.post("/login", data={"username": user, "password": "not-" + password}, follow_redirects=False)
    assert bad_user.status_code == bad_password.status_code == 401
    assert bad_user.text == bad_password.text
    assert "Invalid username or password." in bad_user.text
    assert "set-cookie" not in bad_user.headers
    assert "set-cookie" not in bad_password.headers


def test_login_compares_both_fields(monkeypatch):
    calls = []
    real = auth.secrets_equal

    def spy(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(auth, "secrets_equal", spy)
    _client().post(
        "/login",
        data={"username": "definitely-wrong", "password": "also-wrong"},
        follow_redirects=False,
    )
    assert len(calls) >= 2


def test_secrets_equal_ignores_length_difference():
    assert auth.secrets_equal("same", "same") is True
    assert auth.secrets_equal("short", "much-longer-value") is False
    assert auth.secrets_equal("", "x") is False


def test_successful_login_sets_a_hardened_cookie_and_opens_the_site(signed_in):
    home = signed_in.get("/")
    assert home.status_code == 200 and 'id="landViewBtn"' in home.text
    assert 'href="/logout"' in home.text
    assert signed_in.get("/api/status").status_code == 200
    assert signed_in.get("/api/observations").status_code == 200
    assert "tiles" in signed_in.get("/api/board").json()


def test_cookie_is_secure_on_https_and_forwarded_https():
    import app
    user = os.environ["DASHBOARD_USERNAME"]
    password = os.environ["DASHBOARD_PASSWORD"]
    data = {"username": user, "password": password}
    https = TestClient(app.app, base_url="https://testserver")
    secure = https.post("/login", data=data, follow_redirects=False)
    flags = _cookie_flags(secure)
    assert "httponly" in flags and "samesite=lax" in flags and "secure" in flags

    forwarded = _client().post("/login", data=data, headers={"x-forwarded-proto": "https"}, follow_redirects=False)
    assert "secure" in _cookie_flags(forwarded)

    plain = _client().post("/login", data=data, follow_redirects=False)
    plain_flags = _cookie_flags(plain)
    assert "httponly" in plain_flags and "samesite=lax" in plain_flags
    assert "secure" not in plain_flags


def test_open_redirect_is_rejected(signed_in):
    user = os.environ["DASHBOARD_USERNAME"]
    password = os.environ["DASHBOARD_PASSWORD"]
    for nxt in ("https://evil.example/phish", "//evil.example", "/\\evil.example", "/login", "/logout"):
        response = signed_in.post(
            "/login",
            data={"username": user, "password": password, "next": nxt},
            follow_redirects=False,
        )
        assert response.status_code == 303, nxt
        assert "evil.example" not in _path(response)
        assert _path(response) == "/"


def test_logout_ends_the_session(signed_in):
    response = signed_in.get("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert _path(response) == "/login"
    assert signed_in.get("/api/status", follow_redirects=False).status_code == 401
    home = signed_in.get("/", follow_redirects=False)
    assert home.status_code == 302


def test_tampered_and_expired_cookies_are_rejected():
    cfg = auth.load_config()
    token = auth.issue_token(cfg, now=1_700_000_000)
    assert auth.verify_token(token, cfg, now=1_700_000_000) == cfg.username
    assert auth.verify_token(token, cfg, now=1_700_000_000 + auth.SESSION_TTL - 1) == cfg.username
    assert auth.verify_token(token, cfg, now=1_700_000_000 + auth.SESSION_TTL) is None
    flipped = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert auth.verify_token(flipped, cfg, now=1_700_000_000) is None
    renamed = auth.AuthConfig("other-user", cfg.password, cfg.session_secret)
    assert auth.verify_token(token, renamed, now=1_700_000_000) is None
    rotated = auth.AuthConfig(cfg.username, cfg.password + "-rotated", cfg.session_secret)
    assert auth.verify_token(token, rotated, now=1_700_000_000) is None

    client = _client()
    client.cookies.set(auth.COOKIE, flipped)
    assert client.get("/api/board", follow_redirects=False).status_code == 401


def test_password_change_blocks_an_existing_session(monkeypatch, signed_in):
    monkeypatch.setenv("DASHBOARD_PASSWORD", os.environ["DASHBOARD_PASSWORD"] + "-new")
    assert signed_in.get("/api/observations", follow_redirects=False).status_code == 401


def test_unauthenticated_camera_check_does_not_run(monkeypatch):
    import app

    def boom(*_a, **_k):
        raise AssertionError("camera check should not run")

    monkeypatch.setattr(app, "classify_camera", boom)
    monkeypatch.setattr(app, "refresh", boom)
    client = _client()
    assert client.post("/api/cameras/cam-1/check", follow_redirects=False).status_code == 401
    assert client.post("/api/refresh", follow_redirects=False).status_code == 401


def test_application_source_has_no_default_password():
    for rel in ("app.py", "core/auth.py", "web/login.html", "web/index.html", ".env.example"):
        text = (ROOT / rel).read_text()
        assert "ff-test-password" not in text
        assert "ff-test-session-secret" not in text
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "password123" not in stripped.lower()
            assert "changeme" not in stripped.lower()
