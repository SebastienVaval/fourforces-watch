"""Session gate for the dashboard and data API.

Credentials come only from the environment. If any required variable is missing or
empty, the site fails closed: the login page explains that, and nothing else is served
except the public health check and static assets the login page needs.

Required environment variables (no defaults in this repository):
- DASHBOARD_USERNAME
- DASHBOARD_PASSWORD
- DASHBOARD_SESSION_SECRET  (signs the session cookie; required)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

COOKIE = "ff_session"
SESSION_TTL = 12 * 60 * 60
_LOGIN_HTML = (Path(__file__).resolve().parents[1] / "web" / "login.html").read_text(encoding="utf-8")
_NOT_CONFIGURED = (
    "Sign-in is not configured. An operator must set DASHBOARD_USERNAME, "
    "DASHBOARD_PASSWORD, and DASHBOARD_SESSION_SECRET on the server. "
    "There is no default password."
)
_BAD_LOGIN = "Invalid username or password."


@dataclass(frozen=True)
class AuthConfig:
    username: str
    password: str
    session_secret: str

    @property
    def configured(self) -> bool:
        return bool(self.username) and bool(self.password) and bool(self.session_secret)


def load_config() -> AuthConfig:
    """Read credentials on each call so a missing variable cannot be cached as success."""
    return AuthConfig(
        username=os.environ.get("DASHBOARD_USERNAME", ""),
        password=os.environ.get("DASHBOARD_PASSWORD", ""),
        session_secret=os.environ.get("DASHBOARD_SESSION_SECRET", ""),
    )


def secrets_equal(a: str, b: str) -> bool:
    """Constant-time equality that does not leak the length of either string."""
    return hmac.compare_digest(
        hashlib.sha256(a.encode("utf-8")).digest(),
        hashlib.sha256(b.encode("utf-8")).digest(),
    )


def credentials_ok(username: str, password: str, cfg: AuthConfig) -> bool:
    """Check both fields even when the username is already wrong."""
    user_ok = secrets_equal(username, cfg.username)
    pass_ok = secrets_equal(password, cfg.password)
    return user_ok and pass_ok


def _password_tag(password: str, secret: str) -> str:
    """Bound the cookie to the current password without storing a bare password hash."""
    return hmac.new(secret.encode("utf-8"), b"pw:" + password.encode("utf-8"), hashlib.sha256).hexdigest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_token(cfg: AuthConfig, ttl: int = SESSION_TTL, now: float | None = None) -> str:
    issued = int(time.time() if now is None else now)
    payload = {
        "u": cfg.username,
        "exp": issued + ttl,
        "n": os.urandom(16).hex(),
        "p": _password_tag(cfg.password, cfg.session_secret),
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    mac = hmac.new(cfg.session_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return _b64encode(body) + "." + _b64encode(mac)


def verify_token(token: str, cfg: AuthConfig, now: float | None = None) -> str | None:
    """Return the username if the cookie is signed, unexpired, and still matches the env."""
    if not cfg.configured or not token or token.count(".") != 1:
        return None
    body_b64, mac_b64 = token.split(".", 1)
    try:
        body = _b64decode(body_b64)
        mac = _b64decode(mac_b64)
        payload = json.loads(body.decode("utf-8"))
        username = payload["u"]
        exp = payload["exp"]
        nonce = payload["n"]
        pw_tag = payload["p"]
    except Exception:
        return None
    if not isinstance(username, str) or not isinstance(exp, int) or not isinstance(nonce, str) or not isinstance(pw_tag, str):
        return None
    expected = hmac.new(cfg.session_secret.encode("utf-8"), body, hashlib.sha256).digest()
    mac_ok = hmac.compare_digest(hashlib.sha256(mac).digest(), hashlib.sha256(expected).digest())
    user_ok = secrets_equal(username, cfg.username)
    tag_ok = secrets_equal(pw_tag, _password_tag(cfg.password, cfg.session_secret))
    fresh = exp > int(time.time() if now is None else now)
    if mac_ok and user_ok and tag_ok and fresh and len(nonce) >= 16:
        return username
    return None


def cookie_secure(request: Request) -> bool:
    """Secure on HTTPS, including Render's X-Forwarded-Proto when the app sees plain HTTP."""
    if request.url.scheme == "https":
        return True
    forwarded = request.headers.get("x-forwarded-proto", "")
    return forwarded.split(",")[0].strip().lower() == "https"


def _set_session_cookie(response, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
        path="/",
    )


def _clear_session_cookie(response, request: Request) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=cookie_secure(request))


def safe_next(raw: str | None) -> str:
    """Only same-site paths. Anything else, including scheme-relative URLs, stays on /."""
    if not raw:
        return "/"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        return "/"
    if not raw.startswith("/") or raw.startswith("//") or raw.startswith("/\\") or "\\" in raw:
        return "/"
    path = raw.split("?", 1)[0]
    if path.rstrip("/") in ("/login", "/logout"):
        return "/"
    return raw


def _esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _login_body(cfg: AuthConfig, nxt: str, error: str | None) -> str:
    if not cfg.configured:
        return f'<p class="login-note">{_esc(_NOT_CONFIGURED)}</p>'
    parts = []
    if error:
        parts.append(f'<p class="login-error">{_esc(error)}</p>')
    parts.append(
        '<form method="post" action="/login">'
        f'<input type="hidden" name="next" value="{_esc(nxt)}">'
        '<label for="username">Username</label>'
        '<input id="username" name="username" type="text" autocomplete="username" required autofocus>'
        '<label for="password">Password</label>'
        '<input id="password" name="password" type="password" autocomplete="current-password" required>'
        '<button type="submit">Sign in</button>'
        "</form>"
    )
    return "".join(parts)


def login_page(cfg: AuthConfig, nxt: str, error: str | None, status: int) -> HTMLResponse:
    html = _LOGIN_HTML.replace("__BODY__", _login_body(cfg, nxt, error))
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store"})


def _parse_form(raw: bytes) -> dict[str, str]:
    if len(raw) > 8192:
        return {}
    try:
        text = raw.decode("utf-8")
        parsed = parse_qs(text, keep_blank_values=True, max_num_fields=8, separator="&")
    except (UnicodeDecodeError, ValueError):
        return {}
    return {k: v[0] if v else "" for k, v in parsed.items()}


def classify(path: str) -> str:
    """public: no session. data: 401 JSON. page: redirect to /login."""
    p = path if path == "/" else path.rstrip("/")
    # The verification route is registered only while this flag is 1, and it
    # has to be reachable without a session so a curl confirms the Sentry event.
    if p == "/sentry-debug" and os.getenv("SENTRY_DEBUG_ROUTE", "").strip() == "1":
        return "public"
    if p in ("/healthz", "/login", "/logout") or p == "/static" or path.startswith("/static/"):
        return "public"
    if p == "/api" or path.startswith("/api/") or p == "/demo-images" or path.startswith("/demo-images/") or p == "/openapi.json":
        return "data"
    return "page"


def _login_location(scope) -> str:
    path = scope.get("path") or "/"
    qs = scope.get("query_string") or b""
    target = path + (("?" + qs.decode("latin-1")) if qs else "")
    return "/login?next=" + quote(target, safe="")


def _session_ok(scope) -> bool:
    cfg = load_config()
    token = Request(scope).cookies.get(COOKIE, "")
    return verify_token(token, cfg) is not None


class AuthGate:
    """Reject every page and data route that has no valid session cookie."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or "/"
        kind = classify(path)
        if kind == "public":
            await self.app(scope, receive, send)
            return
        if _session_ok(scope):
            await self.app(scope, receive, _private_cache(send))
            return
        if kind == "data":
            response = JSONResponse(
                {"detail": "Not authenticated"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
        else:
            response = RedirectResponse(_login_location(scope), status_code=302, headers={"Cache-Control": "no-store"})
        await response(scope, receive, send)


def _private_cache(send):
    async def wrapped(message):
        if message["type"] == "http.response.start":
            headers = MutableHeaders(scope=message)
            headers["Cache-Control"] = "private, no-store"
        await send(message)
    return wrapped


async def login_get(request: Request):
    cfg = load_config()
    nxt = safe_next(request.query_params.get("next"))
    if cfg.configured and verify_token(request.cookies.get(COOKIE, ""), cfg):
        return RedirectResponse(nxt, status_code=303)
    return login_page(cfg, nxt, error=None, status=200)


async def login_post(request: Request):
    cfg = load_config()
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > 8192:
        form: dict[str, str] = {}
    else:
        form = _parse_form(await request.body())
    nxt = safe_next(form.get("next") or request.query_params.get("next"))
    if not cfg.configured:
        return login_page(cfg, "/", error=None, status=401)
    if credentials_ok(form.get("username", ""), form.get("password", ""), cfg):
        response = RedirectResponse(nxt, status_code=303, headers={"Cache-Control": "no-store"})
        _set_session_cookie(response, request, issue_token(cfg))
        return response
    return login_page(cfg, nxt, error=_BAD_LOGIN, status=401)


async def logout(request: Request):
    response = RedirectResponse("/login", status_code=303, headers={"Cache-Control": "no-store"})
    _clear_session_cookie(response, request)
    return response


def install(app) -> None:
    app.add_api_route("/login", login_get, methods=["GET"], include_in_schema=False)
    app.add_api_route("/login", login_post, methods=["POST"], include_in_schema=False)
    app.add_api_route("/logout", logout, methods=["GET"], include_in_schema=False)
    app.add_middleware(AuthGate)
