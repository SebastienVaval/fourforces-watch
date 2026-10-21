"""Pytest-only dashboard credentials.

The application has no default password. These values are filled in only when the
variables are absent, so the existing HTTP tests can sign in. They are not read by
the app unless the environment actually contains them.
"""
import os

import pytest
from fastapi.testclient import TestClient

_TEST_USER = "ff-test-user"
_TEST_PASSWORD = "ff-test-password"
_TEST_SECRET = "ff-test-session-secret"


def _fill(name: str, value: str) -> None:
    if not os.environ.get(name):
        os.environ[name] = value


_fill("DASHBOARD_USERNAME", _TEST_USER)
_fill("DASHBOARD_PASSWORD", _TEST_PASSWORD)
_fill("DASHBOARD_SESSION_SECRET", _TEST_SECRET)


@pytest.fixture
def signed_in():
    import app

    client = TestClient(app.app)
    response = client.post(
        "/login",
        data={
            "username": os.environ["DASHBOARD_USERNAME"],
            "password": os.environ["DASHBOARD_PASSWORD"],
            "next": "/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return client


@pytest.fixture
def unconfigured(monkeypatch):
    for key in ("DASHBOARD_USERNAME", "DASHBOARD_PASSWORD", "DASHBOARD_SESSION_SECRET"):
        monkeypatch.delenv(key, raising=False)
