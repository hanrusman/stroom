"""Topic-digests: opvragen, historie, (re)genereren (voorheen in main.py)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import text as sa_text
from sqlmodel import select

from core.db import get_async_session
from models.base import Topic
from pipeline.digest import DIGEST_GENERATION_STALE_MIN
from pipeline.digest import run_digest_generation as _pipeline_run_digest_generation
from schemas.huygens import TopicDigest, TopicDigestRun
from services.llm_service import LLMService

router = APIRouter(tags=["digests"])

DigestWindow = Literal["daily", "weekly"]
DIGEST_WINDOWS: dict[str, int] = {"daily": 24, "weekly": 168}

# Nightly draait elke nacht; de weekdigest hoeft maar ~wekelijks. We regenereren
# 'm pas als de bestaande ouder is dan dit (6,5 dag) → zelfherstellend, geen
# 28-uurs backfill-cascade. Weekly componeert uit dag-digests, dus goedkoop.
WEEKLY_MIN_AGE_HOURS: float = 156.0

# Vrije Stroom-modelnaam. Niet langer een Literal: de geldige set is dynamisch
# en komt live uit LiteLLM (zie GET /admin/models). resolve_model() vertaalt naar
# de echte alias; onbekende namen vallen as-is terug.
DigestModel = str


async def run_digest_generation_bg(app, topic_id: str, topic_name: str, slug: str,
                                   model: DigestModel, window_hours: int):
    """Wrapper: pipeline-call met onze DB-session-maker en LLM-service."""
    from core.db import async_session_maker
    llm = LLMService(app.state.http_client)
    await _pipeline_run_digest_generation(topic_id, topic_name, slug, model, window_hours,
                                          async_session_maker, llm)


@router.get("/huygens/{slug}/digest", response_model=TopicDigest)
async def get_topic_digest(slug: str,
                           window: DigestWindow = Query("daily"),
                           session=Depends(get_async_session)):
    topic = (await session.exec(select(Topic).where(Topic.slug == slug))).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    window_hours = DIGEST_WINDOWS[window]
    row = (await session.exec(sa_text(
        "SELECT markdown, item_count, model, window_hours, generated_at, is_generating, error "
        "FROM topic_digests WHERE topic_id = :tid AND window_hours = :w"
    ).bindparams(tid=topic.id, w=window_hours))).first()
    if not row:
        raise HTTPException(status_code=404, detail="No digest yet")
    return TopicDigest(
        markdown=row[0], item_count=row[1], model=row[2],
        window_hours=row[3],
        generated_at=str(row[4]) if row[4] else None,
        is_generating=row[5], error=row[6],
    )


@router.get("/huygens/{slug}/digest/history", response_model=List[TopicDigestRun])
async def get_topic_digest_history(slug: str,
                                   window: DigestWindow = Query("daily"),
                                   limit: int = Query(7, ge=1, le=30),
                                   session=Depends(get_async_session)):
    topic = (await session.exec(select(Topic).where(Topic.slug == slug))).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    rows = (await session.execute(sa_text("""
        SELECT id::text, generated_at, model, item_count, markdown
        FROM topic_digest_runs
        WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w
        ORDER BY generated_at DESC
        LIMIT :lim
    """), {"tid": str(topic.id), "w": DIGEST_WINDOWS[window], "lim": limit})).all()
    return [TopicDigestRun(
        id=r[0], generated_at=str(r[1]), model=r[2], item_count=r[3], markdown=r[4]
    ) for r in rows]


@router.post("/huygens/{slug}/digest", response_model=TopicDigest)
async def regenerate_topic_digest(slug: str, background_tasks: BackgroundTasks,
                                  request: Request,
                                  model: DigestModel = Query("opus"),
                                  window: DigestWindow = Query("daily"),
                                  session=Depends(get_async_session)):
    topic = (await session.exec(select(Topic).where(Topic.slug == slug))).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    # Capture als plain values vóór commit/close — anders triggert lazy-load na sessie-sluit.
    topic_id = str(topic.id)
    topic_name = topic.name
    window_hours = DIGEST_WINDOWS[window]

    existing = (await session.exec(sa_text(
        "SELECT is_generating, generation_started_at FROM topic_digests "
        "WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w"
    ).bindparams(tid=topic_id, w=window_hours))).first()

    # Check of er een actieve generatie bezig is of in de wachtrij staat:
    # - is_generating=true EN generation_started_at=NULL → in wachtrij
    # - is_generating=true EN generation_started_at < 30 min geleden → actief bezig
    if existing and existing[0]:
        started = existing[1]
        if started is None:
            raise HTTPException(status_code=409, detail="Staat in de wachtrij — even wachten.")
        if (datetime.now(started.tzinfo) - started).total_seconds() < DIGEST_GENERATION_STALE_MIN * 60:
            raise HTTPException(status_code=409, detail="Genereren is al bezig — even wachten.")

    # generation_started_at wordt pas gezet wanneer de task daadwerkelijk begint (in de worker)
    if existing:
        await session.exec(sa_text(
            "UPDATE topic_digests SET is_generating=true, generation_started_at=NULL, "
            "queued_at=now(), error=NULL "
            "WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w"
        ).bindparams(tid=topic_id, w=window_hours))
    else:
        await session.exec(sa_text(
            "INSERT INTO topic_digests (topic_id, window_hours, is_generating, generation_started_at, queued_at) "
            "VALUES (CAST(:tid AS uuid), :w, true, NULL, now())"
        ).bindparams(tid=topic_id, w=window_hours))
    await session.commit()

    background_tasks.add_task(run_digest_generation_bg, request.app,
                              topic_id, topic_name, slug, model, window_hours)
    return await get_topic_digest(slug, window, session)
