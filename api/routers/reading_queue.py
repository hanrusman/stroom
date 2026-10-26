"""Personal FIFO queue. PUT is idempotent and preserves the original position."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from core.auth import require_user
from core.db import get_async_session

router = APIRouter(prefix="/reading-queue", tags=["reading-queue"])

@router.get("/ids")
async def queue_ids(session=Depends(get_async_session), user=Depends(require_user)):
    rows = await session.execute(text("SELECT item_id::text FROM reading_queue WHERE user_id=CAST(:u AS uuid) ORDER BY position"), {"u": str(user["id"])})
    return list(rows.scalars())

@router.get("")
async def list_queue(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                     session=Depends(get_async_session), user=Depends(require_user)):
    rows = await session.execute(text("""
        SELECT i.id::text AS id, i.title, i.description, i.author,
               i.thumbnail_url, i.media_url, s.id::text AS source_id,
               s.name AS source_name, s.image_url AS source_image_url,
               i.published_at::text AS published_at, i.format::text AS format,
               i.status::text AS status, i.processing_status::text AS processing_status,
               i.quality_score, i.scheduled_for::text AS scheduled_for,
               (COALESCE(i.summary, '') <> '') AS has_summary,
               (COALESCE(i.transcript, '') <> '') AS has_transcript,
               q.added_at::text AS added_at
        FROM reading_queue q JOIN items i ON i.id=q.item_id
        JOIN sources s ON s.id=i.source_id
        WHERE q.user_id=CAST(:u AS uuid)
        ORDER BY q.position LIMIT :lim OFFSET :off
    """), {"u": str(user["id"]), "lim": limit, "off": offset})
    return [dict(row) for row in rows.mappings()]

@router.put("/{item_id}")
async def enqueue(item_id: UUID, session=Depends(get_async_session), user=Depends(require_user)):
    # Serializes with archive UPDATE, so an archive can never leave a stale entry.
    row = (await session.execute(text("SELECT status::text FROM items WHERE id=:i FOR UPDATE"), {"i": item_id})).first()
    if row is None:
        raise HTTPException(404, "Item niet gevonden.")
    if row[0] == "archived":
        raise HTTPException(409, "Haal dit item eerst uit het archief.")
    await session.execute(text("""
        INSERT INTO reading_queue (user_id, item_id) VALUES (CAST(:u AS uuid), :i)
        ON CONFLICT (user_id, item_id) DO NOTHING
    """), {"u": str(user["id"]), "i": item_id})
    await session.commit()
    return {"ok": True}

@router.delete("/{item_id}")
async def dequeue(item_id: UUID, session=Depends(get_async_session), user=Depends(require_user)):
    await session.execute(text("DELETE FROM reading_queue WHERE user_id=CAST(:u AS uuid) AND item_id=:i"), {"u": str(user["id"]), "i": item_id})
    await session.commit()
    return {"ok": True}
