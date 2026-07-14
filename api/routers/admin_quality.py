"""Admin: quality-score backfill, status en scorer-config (voorheen in main.py)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import text as sa_text
from sqlmodel import select

from core.auth import require_user
from core.db import get_async_session
from models.base import Topic
from schemas.admin import (
    ExtractKeywordsRequest,
    QualityBackfillRequest,
    QualityBackfillResponse,
    QualityBoostTestResponse,
    QualityScorerPerson,
    QualityScorerTopic,
)
from services.scoring import score_batch_with_quality_scorer

log = logging.getLogger("stroom.admin.quality")

router = APIRouter(tags=["admin-quality"])


async def _run_quality_backfill(app, items_for_scoring: list[dict]) -> None:
    """Background worker: score items en sla op. Eigen session per run."""
    from core.db import async_session_maker
    scores_by_id = await score_batch_with_quality_scorer(app, items_for_scoring)
    if not scores_by_id:
        log.info("[quality-backfill] scorer gaf geen resultaten terug")
        return
    async with async_session_maker() as session:
        for item_id, score in scores_by_id.items():
            await session.exec(sa_text("""
                UPDATE items
                SET quality_score = :score,
                    quality_score_reason = 'auto',
                    quality_score_updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
            """).bindparams(score=score, id=item_id))
        await session.commit()
    log.info("[quality-backfill] klaar: %d/%d gescored",
             len(scores_by_id), len(items_for_scoring))


@router.post("/admin/quality-backfill", response_model=QualityBackfillResponse)
async def admin_quality_backfill(
    request: Request,
    body: QualityBackfillRequest,
    background_tasks: BackgroundTasks,
    session=Depends(get_async_session)
):
    """Batch score items using quality-scorer service. Retourneert direct;
    scoring en DB-updates lopen als background task."""
    if not (1 <= body.limit <= 10000):
        raise HTTPException(status_code=400, detail="limit moet 1-10000 zijn")
    where_clause = "i.quality_score IS NULL" if body.only_null else "TRUE"
    r = await session.exec(sa_text(f"""
        SELECT i.id::text, i.title, i.summary, i.transcript, i.description
        FROM items i
        WHERE {where_clause}
        AND (i.summary IS NOT NULL OR i.transcript IS NOT NULL)
        AND i.summary <> ''
        ORDER BY i.created_at DESC
        LIMIT :lim
    """).bindparams(lim=body.limit))
    items = r.all()

    if not items:
        return QualityBackfillResponse(processed=0, updated=0)

    items_for_scoring = []
    for row in items:
        item_id, title, summary, transcript, description = row
        text = summary or transcript or description or ""
        if text:
            items_for_scoring.append({"id": item_id, "text": text[:8000], "title": title})

    if not items_for_scoring:
        return QualityBackfillResponse(processed=len(items), updated=0)

    background_tasks.add_task(_run_quality_backfill, request.app, items_for_scoring)
    log.info("[quality-backfill] gestart voor %d items", len(items_for_scoring))

    return QualityBackfillResponse(
        processed=len(items),
        updated=0,
        avg_score=None
    )


@router.get("/admin/quality-status")
async def admin_quality_status(
    session=Depends(get_async_session),
    user=Depends(require_user)
):
    """Get quality score statistics."""
    r = await session.exec(sa_text("""
        SELECT
            COUNT(*) FILTER (WHERE quality_score IS NOT NULL) as has_score,
            COUNT(*) FILTER (WHERE quality_score IS NULL) as no_score,
            AVG(quality_score) as avg_score,
            quality_score as score,
            COUNT(*) as count
        FROM items
        GROUP BY quality_score
        ORDER BY quality_score
    """))
    rows = r.all()

    distribution = {}
    for row in rows:
        if row[3] is not None:
            distribution[row[3]] = row[4]

    return {
        "has_score": sum(r[0] for r in rows) if rows else 0,
        "no_score": sum(r[1] for r in rows) if rows else 0,
        "avg_score": round(rows[0][2], 2) if rows and rows[0][2] else None,
        "distribution": distribution
    }


# --- Quality Scorer config (lokaal via topics_service, geen externe container) ---


@router.get("/admin/quality-scorer/topics")
async def admin_quality_scorer_topics(request: Request, user=Depends(require_user)):
    return {"topics": await request.app.state.topics_service.list_topics()}


@router.get("/admin/quality-scorer/persons")
async def admin_quality_scorer_persons(request: Request, user=Depends(require_user)):
    return {"persons": await request.app.state.topics_service.list_persons()}


@router.post("/admin/quality-scorer/topics")
async def admin_quality_scorer_topics_create(topic: QualityScorerTopic, request: Request, user=Depends(require_user)):
    return await request.app.state.topics_service.create_topic(topic.name, topic.keywords)


@router.put("/admin/quality-scorer/topics/{topic_name}")
async def admin_quality_scorer_topics_update(topic_name: str, update: dict, request: Request, user=Depends(require_user)):
    keywords = update.get("keywords", [])
    return await request.app.state.topics_service.update_topic(topic_name, keywords)


@router.delete("/admin/quality-scorer/topics/{topic_name}")
async def admin_quality_scorer_topics_delete(topic_name: str, request: Request, user=Depends(require_user)):
    return await request.app.state.topics_service.delete_topic(topic_name)


@router.post("/admin/quality-scorer/persons")
async def admin_quality_scorer_persons_create(person: QualityScorerPerson, request: Request, user=Depends(require_user)):
    return await request.app.state.topics_service.create_person(person.name, person.keywords)


@router.put("/admin/quality-scorer/persons/{person_name}")
async def admin_quality_scorer_persons_update(person_name: str, update: dict, request: Request, user=Depends(require_user)):
    keywords = update.get("keywords", [])
    return await request.app.state.topics_service.update_person(person_name, keywords)


@router.delete("/admin/quality-scorer/persons/{person_name}")
async def admin_quality_scorer_persons_delete(person_name: str, request: Request, user=Depends(require_user)):
    return await request.app.state.topics_service.delete_person(person_name)


@router.post("/admin/quality-scorer/reload")
async def admin_quality_scorer_reload(request: Request, user=Depends(require_user)):
    """Herlaad de centroid uit /data/centroid.npz (na rebuild_centroid.py)."""
    request.app.state.quality_service.reload_centroid()
    return {"status": "reloaded"}


@router.post("/admin/quality-scorer/extract-keywords")
async def admin_quality_scorer_extract_keywords(
    req: ExtractKeywordsRequest,
    request: Request,
    user=Depends(require_user)
):
    """Extract keywords from text (eenvoudige TF-fallback na quality-scorer-eliminatie).

    Quality-scorer had een TF-IDF + stopwords keyword-extractor. Voor nu een
    light versie: meest-frequente lowercase woorden, exclusief korte/cijfers.
    Voldoende voor admin-UI hint-doeleinden; kan later verfijnd worden.
    """
    import re as _re
    from collections import Counter as _Counter
    blob = f"{req.title or ''} {req.text}".lower()
    tokens = _re.findall(r"[a-zàâäãåèéêëìíîïòóôöùúûüñç]{4,}", blob)
    stop = {"deze", "voor", "naar", "over", "maar", "door", "ook", "wel", "kan",
            "het", "een", "van", "met", "dat", "die", "als", "zijn", "worden",
            "this", "that", "with", "from", "have", "been", "they", "their",
            "the", "and", "for", "are", "but", "not", "you", "all", "can",
            "will", "your", "more", "than", "into", "what", "when", "which"}
    tokens = [t for t in tokens if t not in stop]
    top = _Counter(tokens).most_common(req.max_keywords)
    return {"keywords": [{"keyword": k, "score": float(c)} for k, c in top]}


@router.get("/admin/test/quality-boost-scoring", response_model=QualityBoostTestResponse)
async def test_quality_boost_scoring(
    topic_slug: str = Query(..., description="Topic slug om te testen"),
    quality_boost_factor: float = Query(2.0, description="Dagen boost per quality punt boven 6"),
    per_rail: int = Query(20, le=50),
    session=Depends(get_async_session),
    user=Depends(require_user)
):
    """Vergelijk oude vs nieuwe scoring formule.

    Oude formule: epoch(published_at) + weight * 172800
    Nieuwe formule: epoch(published_at) + weight * 172800 + max(0, quality-6) * 86400 * boost_factor

    quality_boost_factor bepaalt hoeveel dagen er bij komt per quality punt boven 6.
    Bij factor=2.0: quality 7 = +2 dagen, quality 8 = +4 dagen, etc.
    """
    topic = (await session.exec(select(Topic).where(Topic.slug == topic_slug))).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    seconds_per_quality_point = 86400 * quality_boost_factor  # dagen -> seconden

    # OUDE SCORING (huidige)
    old_result = await session.exec(
        sa_text("""
            WITH ranked AS (
              SELECT i.id::text AS id, i.title, s.name AS sname, i.quality_score,
                     i.published_at, s.weight,
                     (EXTRACT(EPOCH FROM i.published_at) + s.weight * 172800) AS score
              FROM items i
              JOIN item_topics it ON it.item_id = i.id
              JOIN sources s ON s.id = i.source_id
              WHERE it.topic_id = :tid
                AND i.format IS NOT NULL
                AND s.active = true
                AND i.status <> 'archived'::item_status
            )
            SELECT id, title, sname, quality_score, weight, score, published_at
            FROM ranked
            ORDER BY score DESC NULLS LAST
            LIMIT :limit
        """).bindparams(tid=topic.id, limit=per_rail * 3)
    )
    old_rows = old_result.all()

    # NIEUWE SCORING (met quality boost)
    new_result = await session.exec(
        sa_text("""
            WITH ranked AS (
              SELECT i.id::text AS id, i.title, s.name AS sname, i.quality_score,
                     i.published_at, s.weight,
                     (EXTRACT(EPOCH FROM i.published_at)
                      + s.weight * 172800
                      + GREATEST(0, COALESCE(i.quality_score, 5) - 6) * :boost) AS score
              FROM items i
              JOIN item_topics it ON it.item_id = i.id
              JOIN sources s ON s.id = i.source_id
              WHERE it.topic_id = :tid
                AND i.format IS NOT NULL
                AND s.active = true
                AND i.status <> 'archived'::item_status
            )
            SELECT id, title, sname, quality_score, weight, score, published_at
            FROM ranked
            ORDER BY score DESC NULLS LAST
            LIMIT :limit
        """).bindparams(tid=topic.id, boost=seconds_per_quality_point, limit=per_rail * 3)
    )
    new_rows = new_result.all()

    # Formatteer resultaten
    def format_rows(rows, top_n=per_rail):
        return [
            {
                "rank": idx + 1,
                "id": r[0],
                "title": r[1][:60] if r[1] else "",
                "source": r[2],
                "quality": r[3],
                "weight": r[4],
                "score": round(r[5], 0),
                "published": str(r[6])[:10] if r[6] else None
            }
            for idx, r in enumerate(rows[:top_n])
        ]

    def count_quality_distribution(rows, top_n=per_rail):
        dist = {"q5": 0, "q6": 0, "q7": 0, "q8": 0, "q9": 0, "q10": 0, "null": 0}
        for r in rows[:top_n]:
            q = r[3]
            if q is None:
                dist["null"] += 1
            elif q <= 5:
                dist["q5"] += 1
            elif q == 6:
                dist["q6"] += 1
            elif q == 7:
                dist["q7"] += 1
            elif q == 8:
                dist["q8"] += 1
            elif q == 9:
                dist["q9"] += 1
            elif q >= 10:
                dist["q10"] += 1
        return dist

    return QualityBoostTestResponse(
        topic_slug=topic_slug,
        quality_boost_factor=quality_boost_factor,
        per_rail=per_rail,
        old_top_items=format_rows(old_rows),
        new_top_items=format_rows(new_rows),
        quality_distribution=count_quality_distribution(old_rows),
        new_quality_distribution=count_quality_distribution(new_rows)
    )
