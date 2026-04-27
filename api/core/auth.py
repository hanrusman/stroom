"""App-level password auth, mirroring the weekmenu pattern.

Hashes with stdlib scrypt (`scrypt$<N>$<salt-b64>$<hash-b64>`), random session
tokens stored in `sessions` table, httpOnly cookie `stroom_session`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import text as sa_text

from core.db import get_async_session

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


async def create_session(session, user_id: str) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    await session.exec(sa_text(
        "INSERT INTO sessions (token, user_id, expires_at) "
        "VALUES (:t, CAST(:u AS uuid), :e)"
    ).bindparams(t=token, u=user_id, e=expires_at))
    await session.commit()
    return token, expires_at


async def delete_session(session, token: str) -> None:
    await session.exec(sa_text(
        "DELETE FROM sessions WHERE token = :t"
    ).bindparams(t=token))
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
    ).bindparams(t=token))
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
        secure=os.environ.get("STROOM_INSECURE_COOKIE") != "1",
        samesite="lax",
        path="/",
        expires=expires_at,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        samesite="lax",
        secure=os.environ.get("STROOM_INSECURE_COOKIE") != "1",
        httponly=True,
    )


async def require_user(request: Request,
                        session=Depends(get_async_session)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    user = await get_session_user(session, token)
    if not user:
        print(f"[auth] 401 path={request.url.path} cookie_present={bool(token)} "
              f"all_cookies={list(request.cookies.keys())} ua={request.headers.get('user-agent','')[:60]}",
              flush=True)
        raise HTTPException(status_code=401, detail="Niet ingelogd")
    return user


def csrf_guard(request: Request) -> None:
    """Block cross-origin state-changing requests via Origin header check."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origin = request.headers.get("origin")
    if not origin:
        return
    host = request.headers.get("host", "")
    try:
        from urllib.parse import urlparse
        origin_host = urlparse(origin).netloc
    except Exception:
        raise HTTPException(status_code=403, detail="Ongeldige origin")
    if origin_host != host:
        raise HTTPException(status_code=403, detail="Ongeldige origin")
