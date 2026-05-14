from typing import List, Dict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.auth import require_user
from core.db import get_async_session

router = APIRouter()


class AdminTopic(BaseModel):
    slug: str
    name: str
    sort_order: int
    item_count: int
    source_count: int


class TopicOrderUpdate(BaseModel):
    slugs: List[str]


class TopicDeleteBody(BaseModel):
    reassign_to: str


class TimeSeriesStats(BaseModel):
    hours_24: int
    days_7: int


class AdminStats(BaseModel):
    total_items: int
    total_sources: int
    status_breakdown: Dict[str, int]
    type_breakdown: Dict[str, int]
    type_breakdown_24h: Dict[str, int]
    queue: Dict[str, int]
    recent_items: TimeSeriesStats


@router.get("/admin/topics", response_model=List[AdminTopic])
async def list_admin_topics(session=Depends(get_async_session), user=Depends(require_user)):
    rows = (await session.execute(sa_text("""
        SELECT t.slug, t.name, t.sort_order,
               COUNT(DISTINCT it.item_id) AS item_count,
               COUNT(DISTINCT st.source_id) AS source_count
        FROM topics t
        LEFT JOIN item_topics it ON it.topic_id = t.id
        LEFT JOIN source_topics st ON st.topic_id = t.id
        GROUP BY t.id, t.slug, t.name, t.sort_order
        ORDER BY t.sort_order, t.name
    """))).all()
    return [AdminTopic(slug=r[0], name=r[1], sort_order=r[2], item_count=r[3], source_count=r[4]) for r in rows]


@router.put("/admin/topics/order")
async def update_topic_order(body: TopicOrderUpdate,
                             session=Depends(get_async_session), user=Depends(require_user)):
    for idx, slug in enumerate(body.slugs):
        await session.execute(sa_text(
            "UPDATE topics SET sort_order = :p WHERE slug = :s"
        ), {"p": (idx + 1) * 10, "s": slug})
    await session.commit()
    return {"ok": True, "count": len(body.slugs)}


@router.delete("/admin/topics/{slug}")
async def delete_topic(slug: str, body: TopicDeleteBody,
                       session=Depends(get_async_session), user=Depends(require_user)):
    if slug == body.reassign_to:
        raise HTTPException(status_code=400, detail="Cannot reassign to the same topic")

    src = (await session.execute(sa_text("SELECT id FROM topics WHERE slug = :s"), {"s": slug})).first()
    dst = (await session.execute(sa_text("SELECT id FROM topics WHERE slug = :s"), {"s": body.reassign_to})).first()
    if not src:
        raise HTTPException(status_code=404, detail="Topic not found")
    if not dst:
        raise HTTPException(status_code=400, detail="Reassign target not found")

    src_id, dst_id = src[0], dst[0]

    # Reassign source_topics; ON CONFLICT keeps existing pairs.
    await session.execute(sa_text("""
        INSERT INTO source_topics (source_id, topic_id)
        SELECT source_id, :dst FROM source_topics WHERE topic_id = :src
        ON CONFLICT DO NOTHING
    """), {"src": src_id, "dst": dst_id})

    await session.execute(sa_text("""
        INSERT INTO item_topics (item_id, topic_id)
        SELECT item_id, :dst FROM item_topics WHERE topic_id = :src
        ON CONFLICT DO NOTHING
    """), {"src": src_id, "dst": dst_id})

    # Delete source rows + topic itself; topic_digests cascade.
    await session.execute(sa_text("DELETE FROM source_topics WHERE topic_id = :src"), {"src": src_id})
    await session.execute(sa_text("DELETE FROM item_topics WHERE topic_id = :src"), {"src": src_id})
    await session.execute(sa_text("DELETE FROM topics WHERE id = :src"), {"src": src_id})
    await session.commit()
    return {"ok": True, "deleted": slug, "reassigned_to": body.reassign_to}


@router.get("/admin/stats", response_model=AdminStats)
async def get_admin_stats(session=Depends(get_async_session), user=Depends(require_user)):
    """Get system statistics for admin dashboard with time-based breakdowns."""

    # Totals
    total_items = (await session.execute(sa_text("SELECT COUNT(*) FROM items"))).scalar()
    total_sources = (await session.execute(sa_text("SELECT COUNT(*) FROM sources"))).scalar()

    # Status breakdown
    status_rows = await session.execute(sa_text("""
        SELECT processing_status::text, COUNT(*)
        FROM items
        GROUP BY processing_status
    """))
    status_breakdown = {row[0]: row[1] for row in status_rows}

    # Type breakdown
    type_rows = await session.execute(sa_text("""
        SELECT type::text, COUNT(*)
        FROM items
        GROUP BY type
    """))
    type_breakdown = {row[0]: row[1] for row in type_rows}

    # Type breakdown (last 24 hours)
    type_24h_rows = await session.execute(sa_text("""
        SELECT type::text, COUNT(*)
        FROM items
        WHERE created_at > NOW() - INTERVAL '24 hours'
        GROUP BY type
    """))
    type_breakdown_24h = {row[0]: row[1] for row in type_24h_rows}

    # Queue depth
    queue_rows = await session.execute(sa_text("""
        SELECT
            COUNT(*) FILTER (WHERE processing_status = 'summarize_queued'),
            COUNT(*) FILTER (WHERE processing_status = 'summarizing'),
            COUNT(*) FILTER (WHERE processing_status = 'transcribe_queued'),
            COUNT(*) FILTER (WHERE processing_status = 'transcribing')
        FROM items
    """))
    summarize_queued, summarizing, transcribe_queued, transcribing = queue_rows.first()

    # Recent items (24 hours)
    recent_24h = (await session.execute(sa_text("""
        SELECT COUNT(*)
        FROM items
        WHERE created_at > NOW() - INTERVAL '24 hours'
    """))).scalar()

    # Recent items (7 days)
    recent_7d = (await session.execute(sa_text("""
        SELECT COUNT(*)
        FROM items
        WHERE created_at > NOW() - INTERVAL '7 days'
    """))).scalar()

    return AdminStats(
        total_items=total_items,
        total_sources=total_sources,
        status_breakdown=status_breakdown,
        type_breakdown=type_breakdown,
        type_breakdown_24h=type_breakdown_24h,
        queue={
            "summarize_queued": summarize_queued,
            "summarizing": summarizing,
            "transcribe_queued": transcribe_queued,
            "transcribing": transcribing
        },
        recent_items=TimeSeriesStats(
            hours_24=recent_24h,
            days_7=recent_7d
        )
    )
