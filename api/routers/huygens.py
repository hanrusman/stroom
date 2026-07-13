"""Huygens: topic-aggregation viewer — items, rails, status, triggers.

Endpoints voorheen in main.py; logica ongewijzigd verplaatst.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text as sa_text
from sqlmodel import select

from core.auth import require_user
from core.db import get_async_session
from models.base import ItemFormat, ItemStatus, ProcessingStatus, ScoreChangeReason, Topic
from schemas.huygens import (
    AddItemTopicRequest,
    HuygensItem,
    HuygensItemDetail,
    HuygensRail,
    HuygensTopic,
    QualityScoreUpdate,
    ScheduleUpdate,
    SourceDetail,
    StatusUpdate,
    TopicRead,
    TranscribeCallback,
)
from services.lessons import ARTICLE_MIN_BODY_FOR_LESSONS, distill_lessons_for_item, replace_lessons
from services.llm_service import LLMService
from services.scoring import QUALITY_BOOST_SECONDS
from workers.summarize import (
    ARTICLE_SUMMARY_SYSTEM,
    SHORT_SUMMARY_SYSTEM,
    pick_summary_route,
    summarize_with_retry,
)

log = logging.getLogger("stroom.huygens")

router = APIRouter(tags=["huygens"])

# In-memory per-user transcribe rate-limit.
_TRANSCRIBE_LOG: dict[str, list[float]] = {}
TRANSCRIBE_WINDOW_S = 3600
TRANSCRIBE_MAX_PER_HOUR = 50


def _check_transcribe_quota(user_id: str) -> bool:
    now = time.time()
    recent = [t for t in _TRANSCRIBE_LOG.get(user_id, []) if now - t < TRANSCRIBE_WINDOW_S]
    if len(recent) >= TRANSCRIBE_MAX_PER_HOUR:
        _TRANSCRIBE_LOG[user_id] = recent
        return False
    recent.append(now)
    _TRANSCRIBE_LOG[user_id] = recent
    return True


async def fetch_item_row(session, item_id: str):
    r = await session.exec(sa_text(
        "SELECT title, type::text, transcript, description, media_url, "
        "       processing_status::text, duration_seconds "
        "FROM items WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    row = r.first()
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"title": row[0], "type": row[1], "transcript": row[2], "description": row[3],
            "media_url": row[4], "processing_status": row[5], "duration_seconds": row[6]}


@router.get("/huygens/items/{item_id}", response_model=HuygensItemDetail)
async def huygens_item(item_id: str, session=Depends(get_async_session)):
    result = await session.exec(
        sa_text(
            """
            SELECT i.id::text, i.format::text, i.title, i.description, i.summary,
                   i.summary_model,
                   i.transcript, i.author, i.media_url, i.thumbnail_url,
                   s.id::text, s.name, s.url, s.image_url, i.published_at,
                   COALESCE(array_agg(t.name) FILTER (WHERE t.id IS NOT NULL), '{}') AS topic_names,
                   i.status::text, i.processing_status::text, i.scheduled_for,
                   i.transcript_segments,
                   i.quality_score
            FROM items i
            JOIN sources s ON s.id = i.source_id
            LEFT JOIN item_topics it ON it.item_id = i.id
            LEFT JOIN topics t ON t.id = it.topic_id
            WHERE i.id = CAST(:iid AS uuid)
            GROUP BY i.id, s.id, s.name, s.url, s.image_url
            """
        ).bindparams(iid=item_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    if not row[1]:
        raise HTTPException(status_code=400, detail="Item has no format")
    queue_pos: Optional[int] = None
    if row[17] == "queued":
        qr = await session.exec(sa_text(
            """
            SELECT COUNT(*) + 1 FROM items
            WHERE processing_status = 'queued'::processing_status
              AND queued_at < (SELECT queued_at FROM items WHERE id = CAST(:i AS uuid))
            """
        ).bindparams(i=item_id))
        queue_pos = qr.first()[0]

    return HuygensItemDetail(
        id=row[0], format=ItemFormat(row[1]), title=row[2],
        description=row[3], summary=row[4], summary_model=row[5],
        transcript=row[6], transcript_segments=row[19],
        author=row[7],
        media_url=row[8], thumbnail_url=row[9],
        source_id=row[10], source_name=row[11], source_url=row[12], source_image_url=row[13],
        published_at=str(row[14]) if row[14] else None,
        topics=list(row[15]),
        status=ItemStatus(row[16]),
        processing_status=ProcessingStatus(row[17]),
        queue_position=queue_pos,
        scheduled_for=str(row[18]) if row[18] else None,
        quality_score=row[20],
    )


@router.post("/huygens/items/{item_id}/status", response_model=HuygensItemDetail)
async def set_item_status(item_id: str, body: StatusUpdate, session=Depends(get_async_session)):
    await fetch_item_row(session, item_id)
    await session.exec(sa_text(
        "UPDATE items SET status = CAST(:s AS item_status) WHERE id = CAST(:i AS uuid)"
    ).bindparams(s=body.status.value, i=item_id))
    await session.exec(sa_text(
        "INSERT INTO feed_events (item_id, event_type) "
        "VALUES (CAST(:i AS uuid), CAST(:e AS feed_event_type))"
    ).bindparams(i=item_id, e=body.status.value))
    await session.commit()
    return await huygens_item(item_id, session)


@router.post("/huygens/items/{item_id}/schedule", response_model=HuygensItemDetail)
async def schedule_item(item_id: str, body: ScheduleUpdate, session=Depends(get_async_session)):
    """Set or clear scheduled_for. Setting a date also flips status to 'later'."""
    await fetch_item_row(session, item_id)
    if body.scheduled_for is None:
        await session.exec(sa_text(
            "UPDATE items SET scheduled_for = NULL WHERE id = CAST(:i AS uuid)"
        ).bindparams(i=item_id))
    else:
        await session.exec(sa_text(
            "UPDATE items SET scheduled_for = :w, status = 'later'::item_status "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(w=body.scheduled_for, i=item_id))
        await session.exec(sa_text(
            "INSERT INTO feed_events (item_id, event_type) "
            "VALUES (CAST(:i AS uuid), 'later'::feed_event_type)"
        ).bindparams(i=item_id))
    await session.commit()
    return await huygens_item(item_id, session)


# --- Filtered list (saved / summarized / scheduled) ---


HuygensFilter = Literal["all", "saved", "summarized", "scheduled", "archived", "inbox"]
HuygensWindow = Literal["all", "24h", "7d", "30d"]

_WINDOW_INTERVAL: dict[str, str] = {
    "24h": "24 hours",
    "7d":  "7 days",
    "30d": "30 days",
}


@router.get("/huygens/items", response_model=List[HuygensItem])
async def list_filtered_items(
    filter: HuygensFilter = Query("all"),
    window: HuygensWindow = Query("all"),
    topic: Optional[str] = Query(None, description="Topic slug to constrain to"),
    source_id: Optional[UUID] = Query(None, description="Source UUID to constrain to"),
    include_archived: bool = Query(False, description="Include archived items"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session=Depends(get_async_session),
):
    if filter == "all" and window == "all" and not topic and not source_id:
        raise HTTPException(status_code=400, detail="At least one filter required")

    clauses: list[str] = ["s.active = true"]
    params: dict = {"lim": limit, "off": offset}

    if filter == "saved":
        clauses.append("i.status = 'pinned'::item_status")
    elif filter == "archived":
        clauses.append("i.status = 'archived'::item_status")
    elif filter == "summarized":
        clauses.append("i.summary IS NOT NULL AND i.summary <> ''")
        clauses.append("i.status <> 'archived'::item_status")
    elif filter == "scheduled":
        clauses.append("i.scheduled_for IS NOT NULL")
        clauses.append("i.status <> 'archived'::item_status")
    elif filter == "inbox":
        clauses.append("s.name = 'Inbox (handmatig)'")
        clauses.append("i.status <> 'archived'::item_status")
    elif not include_archived:
        clauses.append("i.status <> 'archived'::item_status")

    if window != "all":
        clauses.append(f"i.published_at >= now() - INTERVAL '{_WINDOW_INTERVAL[window]}'")

    join_topic = ""
    if topic:
        topic_row = (await session.exec(select(Topic).where(Topic.slug == topic))).first()
        if not topic_row:
            raise HTTPException(status_code=404, detail="Topic not found")
        join_topic = "JOIN item_topics it ON it.item_id = i.id"
        clauses.append("it.topic_id = :tid")
        params["tid"] = topic_row.id

    if source_id:
        clauses.append("i.source_id = :sid")
        params["sid"] = source_id

    order = "i.scheduled_for ASC" if filter == "scheduled" else "COALESCE(i.published_at, i.created_at) DESC"
    sql = f"""
        SELECT i.id::text, i.title, i.description, i.author,
               i.thumbnail_url, i.media_url,
               s.id::text, s.name, s.image_url, i.published_at, i.scheduled_for,
               i.format::text, i.status::text, i.processing_status::text,
               (i.summary IS NOT NULL AND i.summary <> '') AS has_summary,
               (i.transcript IS NOT NULL AND i.transcript <> '') AS has_transcript,
               i.quality_score
        FROM items i
        JOIN sources s ON s.id = i.source_id
        {join_topic}
        WHERE {" AND ".join(clauses)}
        GROUP BY i.id, s.id, s.name, s.image_url
        ORDER BY {order}
        LIMIT :lim OFFSET :off
    """
    result = await session.exec(sa_text(sql).bindparams(**params))
    rows = result.all()
    return [
        HuygensItem(
            id=r[0], title=r[1], description=r[2], author=r[3],
            thumbnail_url=r[4], media_url=r[5],
            source_id=r[6], source_name=r[7], source_image_url=r[8],
            published_at=str(r[9]) if r[9] else None,
            scheduled_for=str(r[10]) if r[10] else None,
            format=r[11], status=r[12], processing_status=r[13],
            has_summary=bool(r[14]), has_transcript=bool(r[15]),
            quality_score=r[16],
        )
        for r in rows
    ]


@router.get("/sources/{source_id}", response_model=SourceDetail)
async def get_source_detail(source_id: UUID, session=Depends(get_async_session)):
    r = await session.exec(sa_text(
        """
        SELECT s.id::text, s.name, s.url, s.kind::text, s.image_url,
               (SELECT COUNT(*) FROM items WHERE source_id = s.id) AS item_count
        FROM sources s
        WHERE s.id = :sid
        """
    ).bindparams(sid=source_id))
    row = r.first()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")
    return SourceDetail(
        id=row[0], name=row[1], url=row[2], kind=row[3],
        image_url=row[4], item_count=int(row[5]),
    )


@router.post("/huygens/items/{item_id}/summarize", response_model=HuygensItemDetail)
async def summarize_item(item_id: str, request: Request,
                         session=Depends(get_async_session),
                         user=Depends(require_user)):
    item = await fetch_item_row(session, item_id)
    transcript = (item["transcript"] or "").strip()

    # Geen transcript maar wel media_url én een audio/video item → eerst transcriberen.
    # Samenvat-agent levert via callback zowel transcript als summary.
    # Voor articles is media_url de artikel-URL zelf, dus skip die path.
    if not transcript and item["media_url"] and item["type"] in ("podcast", "youtube"):
        cur_status = item["processing_status"]
        if cur_status in ("queued", "transcribe_queued", "transcribing", "summarizing"):
            return await huygens_item(item_id, session)

        if not _check_transcribe_quota(user["id"]):
            raise HTTPException(status_code=429,
                                detail=f"Max {TRANSCRIBE_MAX_PER_HOUR} transcribes per uur bereikt.")

        # Altijd queueen; worker pakt op binnen WORKER_IDLE_POLL_SEC.
        # Voorkomt race tussen user-trigger en background worker.
        await session.exec(sa_text(
            "UPDATE items SET processing_status='transcribe_queued'::processing_status, "
            "queued_at=now(), processing_error=NULL "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(i=item_id))
        await session.commit()
        return await huygens_item(item_id, session)

    # Transcript bestaat (of geen media_url) → direct samenvatten van beschikbare tekst.
    text = transcript or (item["description"] or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Geen transcript, media_url of beschrijving om te samenvatten")

    raw_text = re.sub(r"<[^>]+>", " ", text)
    is_article = item["type"] == "rss"
    route = pick_summary_route(raw_text, item.get("duration_seconds"), is_article=is_article)
    actual_model = route["model"]

    await session.exec(sa_text(
        "UPDATE items SET processing_status='summarizing'::processing_status, queued_at=now(), processing_error=NULL "
        "WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    await session.commit()

    try:
        llm = LLMService(request.app.state.http_client)
        try:
            summary = await summarize_with_retry(llm, route["model"], [
                {"role": "system", "content": route["system_prompt"]},
                {"role": "user", "content": f"Titel: {item['title']}\n\nTekst: {route['cleaned']}"},
            ], temperature=0.3, timeout=route["timeout"])
        except Exception as inner:
            if not route["is_long"]:
                raise
            log.warning("long-context model %s faalde voor %s: %s — "
                        "fallback naar stroom-bulk truncated", route["model"], item_id, inner)
            fallback_cleaned = re.sub(r"\s+", " ", raw_text).strip()[:12000]
            summary = await summarize_with_retry(llm, "stroom-bulk", [
                {"role": "system",
                 "content": ARTICLE_SUMMARY_SYSTEM if is_article else SHORT_SUMMARY_SYSTEM},
                {"role": "user", "content": f"Titel: {item['title']}\n\nTekst: {fallback_cleaned}"},
            ], temperature=0.3, timeout=180.0)
            actual_model = f"{route['model']}-fallback-bulk"
        await session.exec(sa_text(
            "UPDATE items SET summary=:s, summary_model=:m, summary_generated_at=now(), "
            "processing_status='ready'::processing_status WHERE id = CAST(:i AS uuid)"
        ).bindparams(s=summary.strip(), m=actual_model, i=item_id))
        await session.commit()

        # Tekstartikelen krijgen ook lesson-distill (idempotent — slaat over als er
        # al lessen zijn). Alleen bij voldoende geëxtraheerde full-text, niet op een
        # RSS-teaser. Best-effort: distill-fout laat de summary intact.
        article_body = (item["transcript"] or "").strip()
        if is_article and len(article_body) >= ARTICLE_MIN_BODY_FOR_LESSONS:
            from core.db import async_session_maker
            try:
                await distill_lessons_for_item(item_id, summary.strip(), article_body,
                                               llm, async_session_maker)
            except Exception as exc:
                log.warning("distill faalde voor %s: %s", item_id, exc)
    except Exception as exc:
        await session.exec(sa_text(
            "UPDATE items SET processing_status='failed'::processing_status, processing_error=:e "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(e=str(exc)[:500], i=item_id))
        await session.commit()
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}")
    return await huygens_item(item_id, session)


@router.post("/huygens/items/{item_id}/transcribe", response_model=HuygensItemDetail)
async def transcribe_item(item_id: str, session=Depends(get_async_session),
                          user=Depends(require_user)):
    item = await fetch_item_row(session, item_id)
    if not item["media_url"]:
        raise HTTPException(status_code=400, detail="No media_url to transcribe")
    if (item["transcript"] or "").strip():
        raise HTTPException(status_code=409, detail="Item heeft al een transcript")

    r = await session.exec(sa_text(
        "SELECT processing_status::text FROM items WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    cur = r.first()
    if cur and cur[0] in ("queued", "transcribe_queued", "transcribing"):
        raise HTTPException(status_code=409, detail=f"Dit item staat al in de queue ({cur[0]})")

    if not _check_transcribe_quota(user["id"]):
        raise HTTPException(status_code=429,
                            detail=f"Max {TRANSCRIBE_MAX_PER_HOUR} transcribes per uur bereikt.")

    # Altijd queueen; transcribe-worker pakt op binnen WORKER_IDLE_POLL_SEC.
    await session.exec(sa_text(
        "UPDATE items SET processing_status='transcribe_queued'::processing_status, "
        "queued_at=now(), processing_error=NULL "
        "WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    await session.commit()
    return await huygens_item(item_id, session)


@router.post("/huygens/items/{item_id}/transcribe-callback", response_model=HuygensItemDetail)
async def transcribe_callback(item_id: str, body: TranscribeCallback,
                              session=Depends(get_async_session)):
    await fetch_item_row(session, item_id)

    if body.error:
        await session.exec(sa_text(
            "UPDATE items SET processing_status='failed'::processing_status, "
            "processing_error=:e WHERE id = CAST(:i AS uuid)"
        ).bindparams(e=body.error[:500], i=item_id))
        await session.commit()
        # Worker pakt de volgende vanzelf op binnen WORKER_IDLE_POLL_SEC.
        return await huygens_item(item_id, session)

    transcript = (body.transcript or "").strip()
    summary = (body.summary or "").strip()
    if not transcript and not summary:
        raise HTTPException(status_code=400, detail="empty callback payload")

    segments_json: Optional[str] = None
    if body.transcript_segments:
        segments_json = json.dumps(body.transcript_segments)

    # Determine next status: ready if summary present, else queue for summarization
    next_status = 'ready' if summary else 'summarize_queued'

    await session.exec(sa_text(
        """
        UPDATE items SET
          transcript = COALESCE(NULLIF(:t, ''), transcript),
          transcript_segments = COALESCE(CAST(:segs AS jsonb), transcript_segments),
          summary = COALESCE(NULLIF(:s, ''), summary),
          summary_model = CASE WHEN NULLIF(:s, '') IS NOT NULL THEN 'transcribe-agent' ELSE summary_model END,
          summary_generated_at = CASE WHEN NULLIF(:s, '') IS NOT NULL THEN now() ELSE summary_generated_at END,
          processing_status = CAST(:ns AS processing_status),
          processing_error = NULL
        WHERE id = CAST(:i AS uuid)
        """
    ).bindparams(t=transcript, segs=segments_json, s=summary, ns=next_status, i=item_id))
    await session.commit()

    if summary:
        try:
            await replace_lessons(session, item_id, summary)
            await session.commit()
        except Exception as exc:
            log.warning("[lessons] parse/store faalde voor %s: %s", item_id, exc)

    # Workers (transcribe + summarize) pakken vanzelf de volgende items.
    return await huygens_item(item_id, session)


@router.post("/huygens/items/{item_id}/heartbeat")
async def heartbeat(item_id: str, session=Depends(get_async_session)):
    """Liveness-ping van samenvat-agent tijdens lange transcribes.
    Update last_progress_at zodat cron-unstuck dit item NIET reset
    zolang er progress is. Geen logging — komt elke 30s per actief item."""
    await session.exec(sa_text(
        "UPDATE items SET last_progress_at = now() WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    await session.commit()
    return {"ok": True}


@router.post("/huygens/items/{item_id}/topics", response_model=HuygensItemDetail)
async def add_item_topic(item_id: str, body: AddItemTopicRequest,
                         session=Depends(get_async_session),
                         user=Depends(require_user)):
    """Add an item to a topic."""
    await fetch_item_row(session, item_id)

    topic_row = (await session.exec(sa_text(
        "SELECT id FROM topics WHERE slug = :slug"
    ).bindparams(slug=body.topic_slug))).first()
    if not topic_row:
        raise HTTPException(status_code=404, detail=f"Topic '{body.topic_slug}' not found")
    topic_id = topic_row[0]

    # Add to topic (ignore if already exists)
    await session.exec(sa_text(
        "INSERT INTO item_topics (item_id, topic_id) VALUES (CAST(:iid AS uuid), :tid) ON CONFLICT DO NOTHING"
    ).bindparams(iid=item_id, tid=topic_id))
    await session.commit()

    return await huygens_item(item_id, session)


@router.delete("/huygens/items/{item_id}/topics/{topic_slug}", response_model=HuygensItemDetail)
async def remove_item_topic(item_id: str, topic_slug: str,
                            session=Depends(get_async_session),
                            user=Depends(require_user)):
    """Remove an item from a topic."""
    await fetch_item_row(session, item_id)

    topic_row = (await session.exec(sa_text(
        "SELECT id FROM topics WHERE slug = :slug"
    ).bindparams(slug=topic_slug))).first()
    if not topic_row:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_slug}' not found")
    topic_id = topic_row[0]

    await session.exec(sa_text(
        "DELETE FROM item_topics WHERE item_id = CAST(:iid AS uuid) AND topic_id = :tid"
    ).bindparams(iid=item_id, tid=topic_id))
    await session.commit()

    return await huygens_item(item_id, session)


@router.patch("/huygens/items/{item_id}/quality-score", response_model=HuygensItemDetail)
async def update_item_quality_score(
    item_id: str,
    update: QualityScoreUpdate,
    session=Depends(get_async_session),
    user=Depends(require_user),
):
    """Update the quality score of an item (user feedback).

    Allows users to correct the auto-generated quality score.
    Set to null to remove the score (neutral).
    """
    await fetch_item_row(session, item_id)

    if update.quality_score is not None:
        if not (1 <= update.quality_score <= 10):
            raise HTTPException(status_code=400, detail="Quality score must be between 1 and 10")

    reason_value = None
    if update.reason:
        try:
            reason_enum = ScoreChangeReason(update.reason)
            reason_value = reason_enum.value
        except ValueError:
            valid_reasons = [r.value for r in ScoreChangeReason]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid reason. Valid options: {', '.join(valid_reasons)}"
            )

    await session.exec(sa_text("""
        UPDATE items
        SET quality_score = :score,
            quality_score_updated_at = NOW(),
            quality_score_reason = :reason,
            quality_score_note = :note
        WHERE id = CAST(:id AS uuid)
    """).bindparams(
        score=update.quality_score,
        id=item_id,
        reason=reason_value,
        note=update.note
    ))
    await session.commit()

    return await huygens_item(item_id, session)


@router.get("/topics", response_model=List[TopicRead])
async def list_topics(session=Depends(get_async_session)):
    result = await session.exec(
        sa_text(
            """
            SELECT t.slug, t.name, COUNT(it.item_id) AS item_count
            FROM topics t
            LEFT JOIN item_topics it ON it.topic_id = t.id
            GROUP BY t.id, t.slug, t.name, t.sort_order
            ORDER BY t.sort_order, t.name
            """
        )
    )
    return [TopicRead(slug=r[0], name=r[1], item_count=r[2]) for r in result.all()]


@router.get("/huygens/{slug}", response_model=HuygensTopic)
async def huygens_topic(slug: str, per_rail: int = Query(20, le=50),
                        session=Depends(get_async_session)):
    topic = (await session.exec(select(Topic).where(Topic.slug == slug))).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Ranking: score = epoch(published_at) + weight * 7d + quality_boost
    # → weight=10 boost ~70 dagen, weight=1 ~7 dagen. Quality boost: +2d per punt boven 6.
    # Per-source cap via ROW_NUMBER() per source × format.
    result = await session.exec(
        sa_text(
            """
            WITH ranked AS (
              SELECT i.format::text AS fmt, i.id::text AS id, i.title, i.description, i.author,
                     i.thumbnail_url, i.media_url, s.id::text AS sid, s.name AS sname, s.image_url AS simg,
                     i.published_at, i.scheduled_for,
                     i.status::text AS istatus, i.processing_status::text AS pstatus,
                     (i.summary IS NOT NULL AND i.summary <> '') AS has_summary,
                     (i.transcript IS NOT NULL AND i.transcript <> '') AS has_transcript,
                     i.quality_score,
                     s.max_per_rail,
                     ROW_NUMBER() OVER (
                       PARTITION BY i.source_id, i.format
                       ORDER BY (
                         EXTRACT(EPOCH FROM i.published_at)
                         + s.weight * 172800
                         + GREATEST(0, COALESCE(i.quality_score, 5) - 6) * :qboost
                       ) DESC NULLS LAST
                     ) AS rn,
                     (
                       EXTRACT(EPOCH FROM i.published_at)
                       + s.weight * 172800
                       + GREATEST(0, COALESCE(i.quality_score, 5) - 6) * :qboost
                     ) AS score
              FROM items i
              JOIN item_topics it ON it.item_id = i.id
              JOIN sources s ON s.id = i.source_id
              WHERE it.topic_id = :tid
                AND i.format IS NOT NULL
                AND s.active = true
                AND i.status <> 'archived'::item_status
            )
            SELECT fmt, id, title, description, author, thumbnail_url, media_url,
                   sid, sname, simg, published_at, scheduled_for,
                   istatus, pstatus, has_summary, has_transcript, quality_score
            FROM ranked
            WHERE max_per_rail IS NULL OR rn <= max_per_rail
            ORDER BY score DESC NULLS LAST
"""
        ).bindparams(tid=topic.id, qboost=QUALITY_BOOST_SECONDS)
    )
    rows = result.all()

    rails: dict[str, List[HuygensItem]] = {f.value: [] for f in ItemFormat}
    for (fmt, iid, title, desc, author, thumb, media, sid, sname, simg, pub, sched,
         istatus, pstatus, has_summary, has_transcript, quality_score) in rows:
        if len(rails[fmt]) >= per_rail:
            continue
        rails[fmt].append(HuygensItem(
            id=iid, title=title, description=desc, author=author,
            thumbnail_url=thumb, media_url=media,
            source_id=sid, source_name=sname,
            source_image_url=simg,
            published_at=str(pub) if pub else None,
            scheduled_for=str(sched) if sched else None,
            format=fmt, status=istatus, processing_status=pstatus,
            has_summary=bool(has_summary), has_transcript=bool(has_transcript),
            quality_score=quality_score,
        ))

    return HuygensTopic(
        slug=topic.slug,
        name=topic.name,
        rails=[HuygensRail(format=ItemFormat(f), items=items) for f, items in rails.items()],
    )
