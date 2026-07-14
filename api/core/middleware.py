"""Auth-middleware: path-whitelist, CSRF-origin-check, internal tokens, sessies."""
from __future__ import annotations

import hmac
import logging

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.auth import SESSION_COOKIE, get_session_user, valid_inbox_token
from core.config import settings

log = logging.getLogger("stroom.middleware")

_ALLOWED_ORIGINS = settings.allowed_origins

_PUBLIC_PATHS = {"/", "/health",
                 "/auth/login", "/auth/me", "/auth/logout"}
if settings.STROOM_ENABLE_DOCS:
    _PUBLIC_PATHS |= {"/openapi.json", "/docs", "/redoc"}

_INTERNAL_TOKEN_PATH_SUFFIXES = (
    "/transcribe-callback",
    "/heartbeat",
    "/admin/cron/nightly",
    "/admin/cron/transcribe-podcasts",
    "/admin/cron/transcribe-videos",
    "/admin/cron/summarize-articles",
    "/admin/cron/digest-topics",
    "/admin/cron/last-result",
    "/admin/sources/backfill-stale",
    "/admin/quality-backfill",
)
# Paths that ALWAYS go through internal-token auth (no session-fallback).
# Used by sibling services that read transcripts / lessons machine-to-machine.
_INTERNAL_TOKEN_PATH_PREFIXES = (
    "/transcripts",
    "/internal/",
)

# --- Token-scopes (verbeterplan S5) ---
# Per-consumer tokens zodat een gelekt token maar één capability geeft en per
# consumer roteerbaar is. Het oude STROOM_INTERNAL_TOKEN heeft tijdens de
# overgangsperiode alle scopes; haal het uit de .env zodra de consumers
# (samenvat-agent, cron-script, m2m-readers) hun eigen token gebruiken.
_TOKEN_SCOPES: dict[str, frozenset[str]] = {}
for _tok, _scopes in (
    (settings.STROOM_AGENT_TOKEN, frozenset({"callback"})),
    (settings.STROOM_CRON_TOKEN, frozenset({"cron"})),
    (settings.STROOM_READER_TOKEN, frozenset({"transcripts"})),
    (settings.STROOM_INTERNAL_TOKEN, frozenset({"callback", "cron", "transcripts"})),
):
    if _tok:  # lege env-vars nooit als geldig token registreren
        _TOKEN_SCOPES[_tok] = _TOKEN_SCOPES.get(_tok, frozenset()) | _scopes

if not _TOKEN_SCOPES:
    log.warning("[SECURITY WARNING] geen interne tokens gezet - "
                "internal endpoints will only work with session auth")


def _scope_for_path(path: str) -> str | None:
    if path.endswith(("/transcribe-callback", "/heartbeat")):
        return "callback"
    if any(path.endswith(s) for s in _INTERNAL_TOKEN_PATH_SUFFIXES):
        return "cron"
    if any(path.startswith(p) for p in _INTERNAL_TOKEN_PATH_PREFIXES):
        return "transcripts"
    return None


def _token_allows(token: str, scope: str) -> bool:
    for known, scopes in _TOKEN_SCOPES.items():
        if hmac.compare_digest(token, known) and scope in scopes:
            return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        # 1. CSRF Origin guard: accept origins in the CORS allowlist.
        # SameSite=Lax already blocks cross-site cookies; this is belt-and-suspenders.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin not in _ALLOWED_ORIGINS:
                log.warning("[csrf] rejected origin=%r path=%s", origin, path)
                return JSONResponse({"detail": "Ongeldige origin"}, status_code=403)

        # 2. Path whitelist (public + auth endpoints + internal callbacks)
        if path in _PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)

        # 3. Internal-token paths (transcribe-agent callback, cron) — accept een
        # token met de juiste scope, OR fall through to session-cookie auth
        # (admin user kicking the cron from UI).
        if any(path.endswith(s) for s in _INTERNAL_TOKEN_PATH_SUFFIXES):
            tok = request.headers.get("x-stroom-internal-token", "")
            if _TOKEN_SCOPES and tok:
                scope = _scope_for_path(path)
                if scope and _token_allows(tok, scope):
                    return await call_next(request)
                # Invalid token / verkeerde scope - log for security monitoring
                log.warning("[SECURITY] Invalid internal token attempt from %s to %s",
                            request.client.host if request.client else "?", path)
                return JSONResponse({"detail": "Unauthorized"}, status_code=403)
            # No token provided → fall through to session-cookie auth

        # 3b. Token-only prefix paths (machine-to-machine) — no session-fallback.
        if any(path.startswith(p) for p in _INTERNAL_TOKEN_PATH_PREFIXES):
            tok = request.headers.get("x-stroom-internal-token", "")
            if not _TOKEN_SCOPES:
                return JSONResponse({"detail": "Internal endpoints disabled"}, status_code=503)
            if not tok or not _token_allows(tok, "transcripts"):
                log.warning("[SECURITY] Invalid/missing internal token for %s from %s",
                            path, request.client.host if request.client else "?")
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return await call_next(request)

        # 3c. Inbox-token: laat de inbox-endpoints door op een geldig
        # X-Stroom-Inbox-Token (iOS Shortcut e.d.). Anders valt het door naar
        # de sessie-cookie hieronder, zodat de web-UI gewoon blijft werken.
        if path.startswith("/inbox/") and valid_inbox_token(request):
            return await call_next(request)

        # 4. Everything else needs a session cookie
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return JSONResponse({"detail": "Niet ingelogd"}, status_code=401)
        # Session hier gevalideerd; require_user hergebruikt request.state.user.
        from core.db import async_session_maker
        async with async_session_maker() as session:
            user = await get_session_user(session, token)
        if not user:
            return JSONResponse({"detail": "Niet ingelogd"}, status_code=401)
        request.state.user = user
        return await call_next(request)
