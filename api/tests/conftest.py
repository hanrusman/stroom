"""Pytest fixtures for stroom-api tests.

Tests run inside the live stroom-api container — no separate test DB.
The container provides STROOM_INTERNAL_TOKEN via env, and the API listens
on http://localhost:8000.

Run from the host:
    docker exec stroom-api pytest /app/tests
"""
import os
import pytest
import httpx


API_BASE = os.environ.get("STROOM_TEST_API_BASE", "http://localhost:8000")


@pytest.fixture(scope="session")
def internal_token() -> str:
    tok = os.environ.get("STROOM_INTERNAL_TOKEN", "")
    if not tok:
        pytest.skip("STROOM_INTERNAL_TOKEN not set in environment")
    return tok


@pytest.fixture
def http_client():
    # 5 min: refreshing 86 sources can take 2-3 minutes wall-clock.
    with httpx.Client(base_url=API_BASE, timeout=300.0) as c:
        yield c


@pytest.fixture
def auth_headers(internal_token):
    return {"x-stroom-internal-token": internal_token}
