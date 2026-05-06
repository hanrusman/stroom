from typing import List

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
