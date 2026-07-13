"""Login/logout/me — sessie-cookie-auth (endpoints voorheen in main.py)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.auth import (
    SESSION_COOKIE,
    check_login_rate_limit,
    clear_session_cookie,
    create_session,
    delete_session,
    get_session_user,
    reset_login_rate_limit,
    set_session_cookie,
    verify_password_or_dummy,
)
from core.db import get_async_session

router = APIRouter(tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
async def auth_login(body: LoginBody, request: Request, response: Response,
                     session=Depends(get_async_session)):
    rate_key = request.client.host if request.client else "unknown"
    if not check_login_rate_limit(rate_key):
        raise HTTPException(status_code=429, detail="Te veel pogingen, probeer over 15 minuten opnieuw")

    email = (body.email or "").strip().lower()
    password = body.password or ""
    if not email or not password:
        raise HTTPException(status_code=400, detail="E-mail en wachtwoord vereist")

    r = await session.exec(sa_text(
        "SELECT id::text, email, password_hash FROM users WHERE email = :e"
    ).bindparams(e=email))
    row = r.first()
    stored_hash = row[2] if row else None
    if not verify_password_or_dummy(password, stored_hash) or not row:
        raise HTTPException(status_code=401, detail="Ongeldige inloggegevens")

    reset_login_rate_limit(rate_key)
    token, expires_at = await create_session(session, row[0])
    set_session_cookie(response, token, expires_at)
    return {"user": {"id": row[0], "email": row[1]}}


@router.post("/auth/logout")
async def auth_logout(request: Request, response: Response,
                      session=Depends(get_async_session)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await delete_session(session, token)
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/me")
async def auth_me(request: Request, session=Depends(get_async_session)):
    token = request.cookies.get(SESSION_COOKIE)
    user = await get_session_user(session, token)
    if not user:
        raise HTTPException(status_code=401, detail="Niet ingelogd")
    return {"user": user}
