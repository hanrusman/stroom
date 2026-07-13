"""App-level password auth, mirroring the weekmenu pattern.

Hashes with stdlib scrypt (`scrypt$<N>$<salt-b64>$<hash-b64>`), random session
tokens stored in `sessions` table, httpOnly cookie `stroom_session`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import text as sa_text

from core.config import settings
from core.db import get_async_session

log = logging.getLogger("stroom.auth")

SESSION_COOKIE = "stroom_session"
SESSION_TTL_DAYS = 30
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_KEYLEN = 64

# In-memory rate-limit on /auth/login: 5 attempts per 15 min per IP.
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
LOGIN_WINDOW_S = 15 * 60
LOGIN_MAX_ATTEMPTS = 5


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                       n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_KEYLEN)
    return f"scrypt${SCRYPT_N}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


# Pre-computed dummy hash so verify_password can be called against a constant
# cost even when the user doesn't exist. Prevents user-enumeration via timing.
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalization")


def verify_password_or_dummy(password: str, stored: Optional[str]) -> bool:
    """Like verify_password but always performs a scrypt hash to keep timing
    constant for missing users."""
    if not stored:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, stored)


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n_str, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    try:
        n = int(n_str)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except Exception:
        return False
    actual = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=n, r=SCRYPT_R, p=SCRYPT_P, dklen=len(expected))
    return hmac.compare_digest(actual, expected)


def check_login_rate_limit(key: str) -> bool:
    now = time.time()
    recent = [t for t in _LOGIN_ATTEMPTS.get(key, []) if now - t < LOGIN_WINDOW_S]
    if len(recent) >= LOGIN_MAX_ATTEMPTS:
        _LOGIN_ATTEMPTS[key] = recent
        return False
    recent.append(now)
    _LOGIN_ATTEMPTS[key] = recent
    return True


def reset_login_rate_limit(key: str) -> None:
    _LOGIN_ATTEMPTS.pop(key, None)


def _token_digest(token: str) -> str:
    """SHA-256-digest van het sessietoken. Alleen de digest gaat de database
    in: wie de sessions-tabel leest (backup-lek, dump) kan er geen sessie mee
    overnemen. Geen salt nodig — het token heeft al 256 bits entropie."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_session(session, user_id: str) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    await session.exec(sa_text(
        "INSERT INTO sessions (token, user_id, expires_at) "
        "VALUES (:t, CAST(:u AS uuid), :e)"
    ).bindparams(t=_token_digest(token), u=user_id, e=expires_at))
    await session.commit()
    return token, expires_at


async def delete_session(session, token: str) -> None:
    await session.exec(sa_text(
        "DELETE FROM sessions WHERE token = :t"
    ).bindparams(t=_token_digest(token)))
    await session.commit()


async def get_session_user(session, token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    r = await session.exec(sa_text(
        """
        SELECT u.id::text, u.email, s.expires_at
        FROM sessions s JOIN users u ON s.user_id = u.id
        WHERE s.token = :t
        """
    ).bindparams(t=_token_digest(token)))
    row = r.first()
    if not row:
        return None
    if row[2] and row[2] < datetime.now(timezone.utc):
        await delete_session(session, token)
        return None
    return {"id": row[0], "email": row[1]}


def set_session_cookie(response: Response, token: str, expires_at: datetime) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=not settings.STROOM_INSECURE_COOKIE,
        samesite="lax",
        path="/",
        expires=expires_at,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        samesite="lax",
        secure=not settings.STROOM_INSECURE_COOKIE,
        httponly=True,
    )


async def require_user(request: Request,
                        session=Depends(get_async_session)) -> dict:
    # AuthMiddleware heeft de sessie al gevalideerd en op request.state gezet;
    # hergebruik die zodat er niet per request een tweede sessions-query loopt.
    cached = getattr(request.state, "user", None)
    if cached:
        return cached
    token = request.cookies.get(SESSION_COOKIE)
    user = await get_session_user(session, token)
    if not user:
        log.info("401 path=%s cookie_present=%s ua=%s", request.url.path,
                 bool(token), request.headers.get("user-agent", "")[:60])
        raise HTTPException(status_code=401, detail="Niet ingelogd")
    return user


# Eigen, smal-gescopet token voor de inbox-router (iOS Shortcut e.d.). Bewust
# losgekoppeld van STROOM_INTERNAL_TOKEN: dit token kan alléén items insturen.
INBOX_TOKEN = settings.STROOM_INBOX_TOKEN
INBOX_TOKEN_HEADER = "x-stroom-inbox-token"


def valid_inbox_token(request: Request) -> bool:
    tok = request.headers.get(INBOX_TOKEN_HEADER, "")
    return bool(INBOX_TOKEN) and bool(tok) and hmac.compare_digest(tok, INBOX_TOKEN)


async def require_user_or_inbox_token(request: Request,
                                      session=Depends(get_async_session)) -> dict:
    """Auth voor de inbox-endpoints: accepteert de sessie-cookie (web-UI) OF
    een geldige X-Stroom-Inbox-Token header (clients zonder cookie, zoals een
    iOS Shortcut)."""
    if valid_inbox_token(request):
        log.info("inbox-token gebruikt path=%s ip=%s", request.url.path,
                 request.client.host if request.client else "?")
        return {"id": None, "email": "inbox-token"}
    return await require_user(request, session)

# NB: de vroegere csrf_guard()-functie is verwijderd — hij werd nergens
# aangeroepen. De echte CSRF-bescherming is de Origin-check in AuthMiddleware.
