"""Optional Sentry error and performance monitoring.

The SDK starts only when ``SENTRY_DSN`` is a non-empty string. With an empty
DSN, ``init_sentry`` leaves Sentry uninitialized so local dev, tests, and demo
mode keep their current behavior.
"""
from __future__ import annotations

import logging
import os
import re
from urllib.parse import quote

import sentry_sdk

log = logging.getLogger("app")

# Values that can appear in feed URLs or exception text. Redacted before send.
_SECRET_ENVS = (
    "AIRNOW_API_KEY",
    "PURPLEAIR_API_KEY",
    "FIRMS_MAP_KEY",
    "XAI_API_KEY",
    "DASHBOARD_PASSWORD",
    "DASHBOARD_SESSION_SECRET",
    "MAPBOX_TOKEN",
    "SENTRY_DSN",
)
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:api[_-]?key|map_key|token|password|secret|access_token)=)([^&\s]+)"
)


def _traces_sample_rate() -> float:
    raw = os.getenv("SENTRY_TRACES_SAMPLE_RATE", "").strip()
    if not raw:
        return 0.1
    try:
        rate = float(raw)
    except ValueError:
        log.warning("invalid SENTRY_TRACES_SAMPLE_RATE %r; using 0.1", raw)
        return 0.1
    if rate < 0.0 or rate > 1.0:
        log.warning("SENTRY_TRACES_SAMPLE_RATE %r is outside 0..1; clamping", raw)
        return min(1.0, max(0.0, rate))
    return rate


def _secret_values() -> list[str]:
    found: list[str] = []
    for name in _SECRET_ENVS:
        value = os.getenv(name, "").strip()
        if len(value) < 8:
            continue
        found.append(value)
        encoded = quote(value, safe="")
        if encoded != value:
            found.append(encoded)
    return found


def redact_secrets(text: str) -> str:
    for value in _secret_values():
        if value in text:
            text = text.replace(value, "[redacted]")
    return _QUERY_SECRET.sub(r"\1[redacted]", text)


def _redact(obj):
    if isinstance(obj, str):
        return redact_secrets(obj)
    if isinstance(obj, dict):
        return {key: _redact(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_redact(value) for value in obj]
    if isinstance(obj, tuple):
        return tuple(_redact(value) for value in obj)
    return obj


def _before_send(event, _hint):
    return _redact(event)


def _before_breadcrumb(crumb, _hint):
    return _redact(crumb)


def init_sentry() -> bool:
    """Start Sentry when ``SENTRY_DSN`` is set. Returns whether the SDK is active."""
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    environment = os.getenv("SENTRY_ENVIRONMENT", "").strip() or "production"
    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=_traces_sample_rate(),
            # Pinned sentry-sdk 2.73 warns that data_collection will replace this.
            # The flag still controls PII, and it stays off.
            send_default_pii=False,
            include_local_variables=False,
            enable_logs=False,
            before_send=_before_send,
            before_send_transaction=_before_send,
            before_breadcrumb=_before_breadcrumb,
        )
    except Exception:
        log.exception("Sentry failed to start; continuing without it")
        return False
    log.info("Sentry enabled (environment=%s)", environment)
    return True


def report_adapter_failure(exc: BaseException, adapter: str, force: str) -> None:
    """Send a caught adapter error to Sentry.

    No-op when the SDK is off. Callers still log the failure and keep the
    previous observations. ``SkipAdapter`` is a configuration skip, so callers
    leave it out of this path.
    """
    if not sentry_sdk.is_initialized():
        return
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("adapter", adapter)
        scope.set_tag("force", force)
        sentry_sdk.capture_exception(exc)
