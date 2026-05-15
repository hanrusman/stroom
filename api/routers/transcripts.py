from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.db import get_async_session


router = APIRouter()


class TranscriptSummary(BaseModel):
    id: str
    title: str
    author: Optional[str]
    source_name: str
    duration_seconds: Optional[int]
    published_at: Optional[str]
    transcript_chars: int
    has_summary: bool


class TranscriptDetail(BaseModel):
    id: str
    title: str
    description: Optional[str]
    author: Optional[str]
    source_name: str
    media_url: Optional[str]
    thumbnail_url: Optional[str]
    duration_seconds: Optional[int]
    published_at: Optional[str]
    created_at: str
    transcript: str
    summary: Optional[str]
    summary_model: Optional[str]
    summary_generated_at: Optional[str]


# Raw SQL met expliciete kolommen + ::text casts. Stroom's Item-model heeft
# een bekende enum-deserialisatie-bug (ContentKind: DB-waarde 'rss', enum-
# member 'RSS') die `select(Item)` doet falen — daarom raw SQL net als
# main.py:list_filtered_items (huygens-route).


@router.get("/transcripts", response_model=List[TranscriptSummary])
async def list_transcripts(
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    include_archived: bool = Query(False),
    session=Depends(get_async_session),
):
    """List items met niet-lege transcript voor samenvat-lab."""
    clauses = ["i.transcript IS NOT NULL", "i.transcript <> ''"]
    params: dict = {"lim": limit, "off": offset}
    if search:
        clauses.append("i.title ILIKE :search")
        params["search"] = f"%{search}%"
    if not include_archived:
        clauses.append("i.status <> 'archived'::item_status")

    sql = f"""
        SELECT i.id::text AS id,
               i.title,
               i.author,
               s.name AS source_name,
               i.duration_seconds,
               i.published_at,
               LENGTH(i.transcript) AS transcript_chars,
               (i.summary IS NOT NULL AND i.summary <> '') AS has_summary
        FROM items i
        JOIN sources s ON s.id = i.source_id
        WHERE {" AND ".join(clauses)}
        ORDER BY COALESCE(i.published_at, i.created_at) DESC
        LIMIT :lim OFFSET :off
    """
    rows = (await session.exec(sa_text(sql).bindparams(**params))).all()
    return [
        TranscriptSummary(
            id=r[0],
            title=r[1],
            author=r[2],
            source_name=r[3],
            duration_seconds=r[4],
            published_at=r[5].isoformat() if r[5] else None,
            transcript_chars=int(r[6]),
            has_summary=bool(r[7]),
        )
        for r in rows
    ]


@router.get("/transcripts/{item_id}", response_model=TranscriptDetail)
async def get_transcript_detail(
    item_id: str,
    session=Depends(get_async_session),
):
    """Volledige transcript + metadata voor één item."""
    try:
        uid = UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item ID format")

    sql = sa_text("""
        SELECT i.id::text AS id,
               i.title,
               i.description,
               i.author,
               s.name AS source_name,
               i.media_url,
               i.thumbnail_url,
               i.duration_seconds,
               i.published_at,
               i.created_at,
               i.transcript,
               i.summary,
               i.summary_model,
               i.summary_generated_at
        FROM items i
        JOIN sources s ON s.id = i.source_id
        WHERE i.id = :uid
    """).bindparams(uid=uid)
    row = (await session.exec(sql)).first()

    if not row:
        raise HTTPException(status_code=404, detail="Item not found")

    transcript = row[10] or ""
    if not transcript.strip():
        raise HTTPException(status_code=404, detail="Transcript not available")

    return TranscriptDetail(
        id=row[0],
        title=row[1],
        description=row[2],
        author=row[3],
        source_name=row[4],
        media_url=row[5],
        thumbnail_url=row[6],
        duration_seconds=row[7],
        published_at=row[8].isoformat() if row[8] else None,
        created_at=row[9].isoformat(),
        transcript=transcript,
        summary=row[11],
        summary_model=row[12],
        summary_generated_at=row[13].isoformat() if row[13] else None,
    )
