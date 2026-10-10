"""Shared HTTP client with a polite User-Agent (api.weather.gov requires one)."""
from __future__ import annotations

import os

import httpx


def client(timeout: float = 20.0) -> httpx.Client:
    contact = os.getenv("CONTACT", "fourforces-watch@example.org")
    return httpx.Client(timeout=timeout, follow_redirects=True,
                        headers={"User-Agent": f"FourForcesWatch/0.1 ({contact})", "Accept": "application/json, */*"})
