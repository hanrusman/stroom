"""Dossiers: brede onderzoeksvragen over het hele archief.

Web (sessie): /research...
Machine-to-machine (Okavango, internal token): /internal/research...
De pijplijn zelf staat in services/research_service.py.
"""
import json
import os
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import text as sa_text

from core.auth import require_user
from core.config import settings
from core.db import async_session_maker, get_async_session
from services import research_service as rs
from services.llm_service import LLMService

router = APIRouter()

WEB_BASE = os.environ.get("STROOM_WEB_BASE_URL", "").rstrip("/")


class NewRun(BaseModel):
    question: str = Field(min_length=10, max_length=1500)


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=800)


_LIST_SQL = """
    SELECT r.id::text, r.title, r.question, r.status, r.progress, r.parent_id::text,
           r.created_at, r.updated_at, r.finished_at, r.error,
           coalesce(jsonb_array_length(r.sources), 0) AS n_sources,
           (SELECT count(*) FROM research_runs c WHERE c.parent_id = r.id) AS n_children
    FROM research_runs r
"""


def _iso(v) -> Optional[str]:
    return v.isoformat() if isinstance(v, datetime) else v


def _list_row(r) -> dict:
    return {"id": r[0], "title": r[1], "question": r[2], "status": r[3],
            "progress": r[4] or {}, "parent_id": r[5], "created_at": _iso(r[6]),
            "updated_at": _iso(r[7]), "finished_at": _iso(r[8]), "error": r[9],
            "n_sources": r[10], "superseded": r[11] > 0}


def _public_run(run: dict, *, full: bool = True) -> dict:
    out = {k: (_iso(v) if isinstance(v, datetime) else v) for k, v in run.items()
           if k not in ("draft", "user_id")}
    if not full:
        out.pop("sources", None)
        out.pop("critique", None)
    return out


def _llm(request: Request) -> LLMService:
    return LLMService(rs.http_client())


def _start(request: Request, run_id: str) -> None:
    rs.spawn(async_session_maker, _llm(request), request.app.state.http_client, run_id)


async def _create(session, question: str, user_id: Optional[str],
                  parent_id: Optional[str] = None) -> str:
    row = (await session.exec(sa_text("""
        INSERT INTO research_runs (question, user_id, parent_id, status, progress)
        VALUES (:q, CAST(:u AS uuid), CAST(:p AS uuid), 'queued', '{"stage": "queued"}')
        RETURNING id::text
    """).bindparams(q=question.strip(), u=user_id, p=parent_id))).first()
    await session.commit()
    return row[0]


# Wie mag een dossier zien: de eigenaar, en iedereen bij dossiers zonder
# eigenaar (gestart via Okavango met het internal token). Een dossier van een
# ander geeft 404, net als een onbekend id.
_OWNED = "(r.user_id = CAST(:u AS uuid) OR r.user_id IS NULL)"


async def _get(run_id: str, user: Optional[dict] = None) -> dict:
    """Run ophalen. Met `user` (web-routes) alleen als die hem mag zien;
    zonder `user` (internal-routes, al door het token afgeschermd) altijd."""
    try:
        run = await rs.DbStore(async_session_maker).get_run(run_id)
    except (KeyError, Exception) as e:
        if isinstance(e, KeyError) or "invalid input syntax for type uuid" in str(e):
            raise HTTPException(status_code=404, detail="Dossier niet gevonden")
        raise
    if user is not None and not rs.can_access(run.get("user_id"), user.get("id")):
        raise HTTPException(status_code=404, detail="Dossier niet gevonden")
    return run


async def _ask(request: Request, run_id: str, question: str,
               user: Optional[dict] = None) -> dict:
    run = await _get(run_id, user)
    try:
        answer, model = await rs.ask(_llm(request), run, question.strip())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)[:400])
    entry = {"question": question.strip(), "answer": answer, "model": model,
             "at": datetime.now(timezone.utc).isoformat()}
    async with async_session_maker() as s:
        await s.exec(sa_text("""
            UPDATE research_runs SET followups = coalesce(followups, '[]'::jsonb) || CAST(:e AS jsonb)
            WHERE id = CAST(:i AS uuid)
        """).bindparams(e=json.dumps([entry], ensure_ascii=False), i=run_id))
        await s.commit()
    return entry


def _item_url(item_id: str) -> str:
    return f"{WEB_BASE}/?item={item_id}" if WEB_BASE else f"stroom://item/{item_id}"


# ---------------------------------------------------------------- web


@router.get("/research")
async def list_runs(limit: int = Query(50, ge=1, le=200),
                    session=Depends(get_async_session), user=Depends(require_user)):
    rows = (await session.exec(sa_text(
        _LIST_SQL + f" WHERE {_OWNED} ORDER BY r.created_at DESC LIMIT :n")
        .bindparams(n=limit, u=str(user["id"])))).all()
    return [_list_row(r) for r in rows]


@router.post("/research")
async def create_run(body: NewRun, request: Request,
                     session=Depends(get_async_session), user=Depends(require_user)):
    run_id = await _create(session, body.question, str(user["id"]))
    _start(request, run_id)
    return {"id": run_id}


@router.get("/research/{run_id}")
async def get_run(run_id: str, user=Depends(require_user)):
    return _public_run(await _get(run_id, user))


@router.get("/research/{run_id}/funnel")
async def funnel(run_id: str, session=Depends(get_async_session), user=Depends(require_user)):
    """Alle kandidaten met recall-score, screening en of er bevindingen uit kwamen:
    laat zien waarom een bron wel of niet in het dossier zit."""
    await _get(run_id, user)
    rows = (await session.exec(sa_text("""
        SELECT c.item_id::text, i.title, s.name, i.format::text, i.published_at,
               c.recall_score, c.queries, c.screen_score,
               f.relevance, coalesce(jsonb_array_length(f.findings), 0)
        FROM research_candidates c
        JOIN items i ON i.id = c.item_id JOIN sources s ON s.id = i.source_id
        LEFT JOIN research_findings f ON f.run_id = c.run_id AND f.item_id = c.item_id
        WHERE c.run_id = CAST(:r AS uuid)
        ORDER BY c.recall_score DESC LIMIT 600
    """).bindparams(r=run_id))).all()
    return [{"item_id": r[0], "title": r[1], "source": r[2], "format": r[3],
             "date": r[4].date().isoformat() if r[4] else None, "recall_score": r[5],
             "queries": list(r[6] or []), "screen_score": r[7], "relevance": r[8],
             "n_findings": r[9]} for r in rows]


@router.post("/research/{run_id}/refresh")
async def refresh_run(run_id: str, request: Request,
                      session=Depends(get_async_session), user=Depends(require_user)):
    """Nieuwe run met dezelfde vraag; hergebruikt plan, screening en extracties,
    doet alleen nieuwe items opnieuw en schrijft het dossier opnieuw."""
    parent = await _get(run_id, user)
    if parent["status"] not in rs.TERMINAL:
        raise HTTPException(status_code=409, detail="Dit dossier loopt nog")
    new_id = await _create(session, parent["question"], str(user["id"]), parent_id=run_id)
    _start(request, new_id)
    return {"id": new_id}


@router.post("/research/{run_id}/resume")
async def resume_run(run_id: str, request: Request, user=Depends(require_user)):
    """Mislukte/geannuleerde run verder laten lopen vanaf de laatste stap."""
    run = await _get(run_id, user)
    if run["status"] not in ("failed", "cancelled"):
        raise HTTPException(status_code=409, detail="Alleen een mislukte of gestopte run kan verder")
    await rs.DbStore(async_session_maker).update_run(run_id, status="queued", error=None,
                                                     finished_at=False)
    _start(request, run_id)
    return {"ok": True}


@router.post("/research/{run_id}/cancel")
async def cancel_run(run_id: str, user=Depends(require_user)):
    run = await _get(run_id, user)
    if run["status"] in rs.TERMINAL:
        return {"ok": True}
    rs.request_cancel(run_id)
    return {"ok": True}


@router.delete("/research/{run_id}")
async def delete_run(run_id: str, session=Depends(get_async_session), user=Depends(require_user)):
    run = await _get(run_id, user)
    if run["status"] not in rs.TERMINAL:
        raise HTTPException(status_code=409, detail="Stop het dossier eerst")
    await session.exec(sa_text(
        f"DELETE FROM research_runs r WHERE r.id = CAST(:i AS uuid) AND {_OWNED}")
        .bindparams(i=run_id, u=str(user["id"])))
    await session.commit()
    return {"ok": True}


@router.post("/research/{run_id}/ask")
async def ask_run(run_id: str, body: AskBody, request: Request, user=Depends(require_user)):
    return await _ask(request, run_id, body.question, user)


@router.get("/research/{run_id}/markdown", response_class=PlainTextResponse)
async def markdown(run_id: str, user=Depends(require_user)):
    run = await _get(run_id, user)
    if not run.get("report"):
        raise HTTPException(status_code=409, detail="Dossier is nog niet af")
    return rs.to_markdown(run, _item_url)


@router.post("/research/{run_id}/obsidian")
async def to_obsidian(run_id: str, request: Request, user=Depends(require_user)):
    run = await _get(run_id, user)
    if not run.get("report"):
        raise HTTPException(status_code=409, detail="Dossier is nog niet af")
    if not settings.OBSIDIAN_API_KEY or not settings.OBSIDIAN_BASE_URL:
        raise HTTPException(status_code=503, detail="Obsidian is niet geconfigureerd")
    safe = re.sub(r"[^\w\s-]", "", run.get("title") or "Dossier").strip()[:80] or "Dossier"
    path = f"Dossiers/{safe}.md"
    resp = await request.app.state.http_client.put(
        f"{settings.OBSIDIAN_BASE_URL.rstrip('/')}/vault/{quote(path)}",
        headers={"Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}",
                 "Content-Type": "text/markdown"},
        content=rs.to_markdown(run, _item_url).encode("utf-8"), timeout=15.0)
    if resp.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"Obsidian gaf {resp.status_code}")
    return {"ok": True, "path": path}


# ---------------------------------------------------------------- Okavango


@router.get("/internal/research")
async def internal_list(q: str = Query("", max_length=200), limit: int = Query(20, ge=1, le=100),
                        session=Depends(get_async_session)):
    """Dossiers, nieuwste eerst; met q een simpele zoekactie op titel/vraag.
    Vervangen dossiers (er bestaat een vernieuwing van) vallen weg."""
    where = "WHERE NOT EXISTS (SELECT 1 FROM research_runs c WHERE c.parent_id = r.id AND c.status = 'done')"
    params: dict = {"n": limit}
    if q.strip():
        where += " AND (r.title ILIKE :p OR r.question ILIKE :p)"
        params["p"] = f"%{q.strip()}%"
    rows = (await session.exec(sa_text(
        _LIST_SQL + f" {where} ORDER BY r.created_at DESC LIMIT :n").bindparams(**params))).all()
    return [_list_row(r) for r in rows]


@router.post("/internal/research")
async def internal_create(body: NewRun, request: Request, session=Depends(get_async_session)):
    run_id = await _create(session, body.question, None)
    _start(request, run_id)
    return {"id": run_id, "status": "queued",
            "message": "Dossier gestart; klaar na ca. 10-20 minuten. Vraag de status op met get."}


@router.get("/internal/research/{run_id}")
async def internal_get(run_id: str, include_findings: bool = False,
                       source_ref: Optional[str] = Query(None, pattern=r"^S\d+$")):
    """Compact voor een chat-LLM: rapport + bronnenlijst. Bevindingen alleen op
    verzoek (alles, of van één bron via source_ref)."""
    run = await _get(run_id)
    out = {k: run.get(k) for k in ("id", "title", "question", "status", "progress", "error",
                                   "report", "followups")}
    out["finished_at"] = _iso(run.get("finished_at"))
    srcs = run.get("sources") or []
    if source_ref:
        srcs = [s for s in srcs if s["ref"] == source_ref]
        out["sources"] = srcs
        return out
    out["sources"] = [{k: s.get(k) for k in ("ref", "item_id", "title", "source", "date", "cited")}
                      | ({"findings": s.get("findings")} if include_findings else {})
                      for s in srcs]
    return out


@router.post("/internal/research/{run_id}/ask")
async def internal_ask(run_id: str, body: AskBody, request: Request):
    return await _ask(request, run_id, body.question)
