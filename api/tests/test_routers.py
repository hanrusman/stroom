"""Router-tests zonder database (verbeterplan T1).

Endpoints worden door de hele ASGI-stack (incl. AuthMiddleware) aangeroepen
met een gemockte sessie: `dependency_overrides` vervangt get_async_session,
en de sessie-validatie in de middleware wordt via monkeypatch kortgesloten.
Token-scope-gedrag (S5) wordt op de echte middleware-logica getest.
"""
import sys

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "/app")

from core import middleware as mw  # noqa: E402
from core.auth import require_user  # noqa: E402
from core.db import get_async_session  # noqa: E402
from main import app  # noqa: E402

pytestmark = pytest.mark.unit


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else None

    @property
    def rowcount(self):
        return len(self._rows)


class FakeSession:
    """Geeft voor elke query dezelfde rijen terug — genoeg voor read-only routes."""

    def __init__(self, rows=None):
        self.rows = rows or []

    async def exec(self, *_a, **_k):
        return FakeResult(self.rows)

    async def execute(self, *_a, **_k):
        return FakeResult(self.rows)

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture
def client_factory(monkeypatch):
    def make(rows=None, *, authenticated=True):
        fake = FakeSession(rows)
        app.dependency_overrides[get_async_session] = lambda: fake
        app.dependency_overrides[require_user] = lambda: {"id": "t", "email": "t@t"}
        if authenticated:
            async def fake_session_user(_session, token):
                return {"id": "t", "email": "t@t"} if token else None
            monkeypatch.setattr(mw, "get_session_user", fake_session_user)
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test",
                           cookies={"stroom_session": "test-token"} if authenticated else None)
    yield make
    app.dependency_overrides.clear()


async def test_health_is_public(client_factory):
    async with client_factory(authenticated=False) as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_unauthenticated_request_gets_401(client_factory):
    async with client_factory(authenticated=False) as c:
        r = await c.get("/topics")
    assert r.status_code == 401


async def test_search_requires_min_length(client_factory):
    async with client_factory([]) as c:
        r = await c.get("/search", params={"q": "x"})
    assert r.status_code == 422


async def test_search_returns_hits(client_factory):
    rows = [("id-1", "Kimi bake-off", "article", "Stroom Blog",
             None, "snippet <mark>kimi</mark>", 0.42)]
    async with client_factory(rows) as c:
        r = await c.get("/search", params={"q": "kimi"})
    assert r.status_code == 200
    hits = r.json()
    assert hits[0]["title"] == "Kimi bake-off"
    assert hits[0]["rank"] == pytest.approx(0.42)


async def test_csrf_rejects_unknown_origin(client_factory):
    async with client_factory([]) as c:
        r = await c.post("/topics", headers={"origin": "https://evil.example"})
    assert r.status_code == 403


class TestTokenScopes:
    """S5: per-consumer tokens mogen alleen hun eigen scope bereiken."""

    @pytest.fixture(autouse=True)
    def scoped_tokens(self, monkeypatch):
        monkeypatch.setattr(mw, "_TOKEN_SCOPES", {
            "agent-tok": frozenset({"callback"}),
            "cron-tok": frozenset({"cron"}),
            "reader-tok": frozenset({"transcripts"}),
            "legacy-tok": frozenset({"callback", "cron", "transcripts"}),
        })

    def _client(self, rows=None):
        app.dependency_overrides[get_async_session] = lambda: FakeSession(rows or [])
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    async def test_cron_token_reaches_cron_endpoint(self):
        try:
            async with self._client() as c:
                r = await c.get("/admin/cron/last-result",
                                headers={"x-stroom-internal-token": "cron-tok"})
            assert r.status_code == 200
        finally:
            app.dependency_overrides.clear()

    async def test_agent_token_rejected_on_cron_endpoint(self):
        try:
            async with self._client() as c:
                r = await c.get("/admin/cron/last-result",
                                headers={"x-stroom-internal-token": "agent-tok"})
            assert r.status_code == 403
        finally:
            app.dependency_overrides.clear()

    async def test_agent_token_reaches_heartbeat(self):
        try:
            async with self._client() as c:
                r = await c.post("/huygens/items/00000000-0000-0000-0000-000000000000/heartbeat",
                                 headers={"x-stroom-internal-token": "agent-tok"})
            assert r.status_code == 200
        finally:
            app.dependency_overrides.clear()

    async def test_reader_token_rejected_on_callback(self):
        try:
            async with self._client() as c:
                r = await c.post("/huygens/items/00000000-0000-0000-0000-000000000000/heartbeat",
                                 headers={"x-stroom-internal-token": "reader-tok"})
            assert r.status_code == 403
        finally:
            app.dependency_overrides.clear()

    async def test_legacy_token_keeps_all_scopes(self):
        try:
            async with self._client() as c:
                r = await c.get("/admin/cron/last-result",
                                headers={"x-stroom-internal-token": "legacy-tok"})
            assert r.status_code == 200
        finally:
            app.dependency_overrides.clear()

    async def test_unknown_token_rejected(self):
        try:
            async with self._client() as c:
                r = await c.get("/admin/cron/last-result",
                                headers={"x-stroom-internal-token": "wrong"})
            assert r.status_code == 403
        finally:
            app.dependency_overrides.clear()
