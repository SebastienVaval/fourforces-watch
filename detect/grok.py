"""Grok (xAI API) client: water-on-road check for camera snapshots + text generation.

Uses the xAI Responses API (https://api.x.ai/v1/responses) over httpx, as documented at
https://docs.x.ai/docs/guides/image-understanding.

Env:
    XAI_API_KEY        required for AI features (without it: cameras stay "not checked")
    XAI_VISION_MODEL   image flood check model (default grok-4.7)
    XAI_TEXT_MODEL     trilingual message model (default grok-4.20-0309-non-reasoning)
    XAI_IMAGE_DETAIL   low | high (default high)
    XAI_TIMEOUT        seconds per xAI call (default 20)
    XAI_CONCURRENCY    max xAI calls in flight at once (default 4)
    GROK_CACHE_DIR     where the vision cache is written (default ./.cache; failures are non-fatal)

Vision results are cached per image SHA-256, so an unchanged snapshot is never re-sent.
Requests set store=false (xAI advises not storing history when sending images).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import threading
from pathlib import Path

import httpx

log = logging.getLogger("grok")
API = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")
CACHE_PATH = Path(os.getenv("GROK_CACHE_DIR") or Path(__file__).resolve().parent.parent / ".cache") / "grok_vision.json"
TIMEOUT = float(os.getenv("XAI_TIMEOUT", "20"))
CONCURRENCY = max(1, int(os.getenv("XAI_CONCURRENCY", "4")))
_slots = threading.BoundedSemaphore(CONCURRENCY)  # caps xAI calls in flight across all threads
_lock = threading.Lock()
_cache: dict[str, dict] = {}
_warned = False
_save_warned = False

PROMPT = (
    "You are checking a single traffic-camera or street photo for flooding. "
    "Answer ONLY with compact JSON, no markdown: "
    '{"water_on_road": true|false, "confidence": <0..1>, "note": "<max 15 words>"}. '
    "water_on_road is true only if standing or flowing water covers part of a road, street, parking lot "
    "or sidewalk surface (not just wet pavement from light rain, not a river, canal or bay next to the road). "
    "If the image is blank, a 'camera offline' placeholder, or too dark to tell, answer false with "
    "confidence <= 0.3 and say so in note."
)


def vision_model() -> str:
    return os.getenv("XAI_VISION_MODEL", "grok-4.7")


def text_model() -> str:
    return os.getenv("XAI_TEXT_MODEL", "grok-4.20-0309-non-reasoning")


def api_key() -> str | None:
    global _warned
    key = os.getenv("XAI_API_KEY")
    if not key and not _warned:
        log.warning("XAI_API_KEY not set - camera checks stay 'not checked', board uses templates")
        _warned = True
    return key or None


def available() -> bool:
    return api_key() is not None


def parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _output_text(resp: dict) -> str:
    if isinstance(resp.get("output_text"), str):
        return resp["output_text"]
    parts = []
    for item in resp.get("output", []):
        for c in item.get("content", []) or []:
            if c.get("type") in ("output_text", "text") and c.get("text"):
                parts.append(c["text"])
    return "".join(parts)


def respond(content: list[dict], model: str, max_tokens: int = 400, timeout: float | None = None) -> str:
    """POST /v1/responses with one user message; returns the output text.

    At most CONCURRENCY calls run at once; each is bounded by ``timeout`` (default XAI_TIMEOUT)."""
    key = api_key()
    if not key:
        return ""
    body = {"model": model, "store": False, "max_output_tokens": max_tokens,
            "input": [{"role": "user", "content": content}]}
    with _slots:
        r = httpx.post(f"{API}/responses", json=body, timeout=timeout or TIMEOUT,
                       headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    if r.status_code >= 400:
        raise RuntimeError(f"xAI API {r.status_code}: {r.text[:200]}")
    return _output_text(r.json())


def generate_text(prompt: str, max_tokens: int = 400) -> str:
    return respond([{"type": "input_text", "text": prompt}], text_model(), max_tokens)


def _load():
    global _cache
    if not _cache and CACHE_PATH.exists():
        try:
            _cache = json.loads(CACHE_PATH.read_text())
        except Exception:
            _cache = {}


def _save():
    """Persist the vision cache; a read-only disk (e.g. a container's root-owned /app) must never break a refresh."""
    global _save_warned
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(_cache))
    except OSError as e:
        if not _save_warned:
            log.warning("vision cache not written (%s); keeping it in memory only", e)
            _save_warned = True


def classify_image(image: bytes, mime: str = "image/jpeg") -> dict:
    digest = hashlib.sha256(image).hexdigest()
    with _lock:
        _load()
        if digest in _cache:
            return {**_cache[digest], "cached": True, "image_sha256": digest}
    if not available():
        return {"water_on_road": None, "confidence": None, "note": "no XAI_API_KEY", "model": None,
                "image_sha256": digest}
    if mime not in ("image/jpeg", "image/jpg", "image/png"):
        mime = "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
    try:
        text = respond([{"type": "input_image", "image_url": data_url, "detail": os.getenv("XAI_IMAGE_DETAIL", "high")},
                        {"type": "input_text", "text": PROMPT}], vision_model(), max_tokens=300)
        j = parse_json(text) or {}
        result = {"water_on_road": bool(j["water_on_road"]) if "water_on_road" in j else None,
                  "confidence": float(j["confidence"]) if j.get("confidence") is not None else None,
                  "note": str(j.get("note", text[:80]))[:160], "model": vision_model()}
    except Exception as e:
        log.warning("grok classify failed: %s", e)
        return {"water_on_road": None, "confidence": None, "note": f"error: {str(e)[:120]}",
                "model": vision_model(), "image_sha256": digest}
    if result["water_on_road"] is not None:
        with _lock:
            _cache[digest] = result
            _save()
    return {**result, "cached": False, "image_sha256": digest}


def status_from(result: dict) -> str:
    w, conf = result.get("water_on_road"), result.get("confidence") or 0
    if w is None:
        return "unknown"
    return ("alert" if conf >= 0.6 else "watch") if w else "ok"
