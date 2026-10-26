"""Shared HTTP client with a polite User-Agent (api.weather.gov requires one).

GET and HEAD retry transient upstream failures: HTTP 408, 425, 429, and 5xx,
plus timeouts and connection errors. The wait is exponential with jitter.
Other methods are not retried. Any other 4xx is returned as-is so the caller
can treat it as a real error.
"""
from __future__ import annotations

import logging
import os
import random
import time
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("http")

RETRY_ATTEMPTS = 3
RETRY_BASE_SECONDS = 0.5
RETRY_MAX_SECONDS = 8.0
# 408 timeout, 425 too early, 429 rate limit. 5xx is the upstream, not our request.
TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
DEFAULT_TRANSIENT_POLLS = 3

# RemoteProtocolError is a dropped connection mid-response. LocalProtocolError is our bug.
_TRANSIENT_NETWORK = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


def sleep(seconds: float) -> None:
    """Indirection so tests can skip the wait."""
    time.sleep(seconds)


def retry_delay(attempt: int, rng=random.random) -> float:
    """Equal jitter for retry ``attempt`` (0-based): half the cap, plus a random half."""
    cap = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** attempt))
    return cap * (0.5 + 0.5 * rng())


def is_transient(exc: BaseException) -> bool:
    """True when the failure is usually an upstream blip, not a bug in this app."""
    if isinstance(exc, _TRANSIENT_NETWORK):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in TRANSIENT_STATUS
    return False


def transient_failures_before_sentry() -> int:
    """How many failed polls in a row before a transient outage is sent to Sentry.

    Each poll already retried. The default of 3 means Sentry hears about an outage
    only after three refresh cycles, not after one 503.
    """
    raw = os.getenv("ADAPTER_TRANSIENT_FAILURES_BEFORE_SENTRY", "").strip()
    if not raw:
        return DEFAULT_TRANSIENT_POLLS
    try:
        n = int(raw)
    except ValueError:
        log.warning("invalid ADAPTER_TRANSIENT_FAILURES_BEFORE_SENTRY %r; using %s", raw, DEFAULT_TRANSIENT_POLLS)
        return DEFAULT_TRANSIENT_POLLS
    if n < 1:
        log.warning("ADAPTER_TRANSIENT_FAILURES_BEFORE_SENTRY %r is below 1; using 1", raw)
        return 1
    return n


def should_report(exc: BaseException, consecutive_failures: int) -> bool:
    """Real bugs are reported immediately. A short upstream blip is not."""
    if not is_transient(exc):
        return True
    return consecutive_failures >= transient_failures_before_sentry()


def _safe_url(url) -> str:
    """Host and path only, so a retry log cannot include an API key from the query."""
    parts = urlsplit(str(url))
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _wait(method: str, url, reason: str, attempt: int, attempts: int) -> None:
    delay = retry_delay(attempt)
    log.debug("retrying %s %s after %s (attempt %s/%s, wait %.2fs)",
              method.upper(), _safe_url(url), reason, attempt + 1, attempts, delay)
    sleep(delay)


class PoliteClient(httpx.Client):
    def __init__(self, *args, retry: bool = True, **kwargs):
        self._retry = retry
        super().__init__(*args, **kwargs)

    def request(self, method, url, **kwargs):
        retryable = self._retry and method.upper() in {"GET", "HEAD"}
        attempts = RETRY_ATTEMPTS if retryable else 1
        attempt = 0
        while True:
            try:
                response = super().request(method, url, **kwargs)
            except _TRANSIENT_NETWORK as exc:
                if attempt + 1 >= attempts:
                    raise
                _wait(method, url, type(exc).__name__, attempt, attempts)
                attempt += 1
                continue
            if not (retryable and response.status_code in TRANSIENT_STATUS and attempt + 1 < attempts):
                return response
            code = response.status_code
            response.close()
            _wait(method, url, f"HTTP {code}", attempt, attempts)
            attempt += 1


def client(timeout: float = 20.0, transport: httpx.BaseTransport | None = None, retry: bool = True) -> httpx.Client:
    contact = os.getenv("CONTACT", "fourforces-watch@example.org")
    kwargs = {}
    if transport is not None:
        kwargs["transport"] = transport
    return PoliteClient(
        timeout=timeout,
        follow_redirects=True,
        retry=retry,
        headers={"User-Agent": f"FourForcesWatch/0.1 ({contact})", "Accept": "application/json, */*"},
        **kwargs,
    )
