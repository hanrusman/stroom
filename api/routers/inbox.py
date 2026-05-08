"""Inbox router - handmatig content insturen voor verwerking."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.auth import require_user
from core.db import get_async_session

router = APIRouter()

InboxFormat = Literal["article", "podcast", "video"]


class InboxSubmitRequest(BaseModel):
    url: str
    title: str
    format: InboxFormat
    topic_slug: str
    description: Optional[str] = None
    author: Optional[str] = None


class InboxSubmitResponse(BaseModel):
    id: str
    title: str
    message: str


# Inbox source ID (created manually in DB)
INBOX_SOURCE_NAME = "Inbox (handmatig)"


@router.post("/inbox/submit", response_model=InboxSubmitResponse)
async def inbox_submit(
    body: InboxSubmitRequest,
    session=Depends(get_async_session),
    user=Depends(require_user),
):
    """Submit a new item to the inbox for processing.

    The item will be:
    - Created with processing_status='pending' (articles) or 'queued' (audio/video)
    - Linked to the selected topic
    - Processed by the normal pipeline (summarize/transcribe → distill lessons)
    """
    # Validate URL
    url = (body.url or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Ongeldige URL (moet http:// of https:// zijn)")

    # Validate title
    title = (body.title or "").strip()
    if not title or len(title) < 3:
        raise HTTPException(status_code=400, detail="Titel is verplicht (minimaal 3 tekens)")

    # Get topic
    topic_row = (await session.exec(sa_text(
        "SELECT id::text FROM topics WHERE slug = :slug"
    ).bindparams(slug=body.topic_slug))).first()
    if not topic_row:
        raise HTTPException(status_code=404, detail=f"Topic '{body.topic_slug}' niet gevonden")
    topic_id = topic_row[0]

    # Get inbox source
    source_row = (await session.exec(sa_text(
        "SELECT id::text FROM sources WHERE name = :name"
    ).bindparams(name=INBOX_SOURCE_NAME))).first()
    if not source_row:
        raise HTTPException(status_code=500, detail="Inbox source niet gevonden in database")
    source_id = source_row[0]

    # Generate external_id from URL (hashed for uniqueness)
    import hashlib
    ext_id = f"inbox:{hashlib.sha256(url.encode()).hexdigest()[:32]}"

    # Map format to content_kind
    kind_map = {
        "article": "rss",
        "podcast": "podcast",
        "video": "youtube",
    }
    content_kind = kind_map.get(body.format, "rss")

    # Determine initial processing status
    # Articles: pending (for summarize)
    # Podcast/Video: pending (will be queued for transcribe)
    processing_status = "pending"

    # Insert item
    r = await session.exec(sa_text(
        """
        INSERT INTO items
            (source_id, external_id, type, format, title, description,
             author, media_url, published_at,
             processing_status, status)
        VALUES (CAST(:sid AS uuid), :eid, CAST(:kind AS content_kind), CAST(:fmt AS item_format),
                :title, :desc, :author, :url, :pub,
                CAST(:pstatus AS processing_status), 'new')
        ON CONFLICT (source_id, external_id) DO UPDATE
            SET title = EXCLUDED.title,
                description = EXCLUDED.description,
                author = EXCLUDED.author,
                format = EXCLUDED.format
        RETURNING id::text
        """
    ).bindparams(
        sid=source_id, eid=ext_id, kind=content_kind, fmt=body.format,
        title=title, desc=body.description or None, author=body.author or None,
        url=url, pub=datetime.now(timezone.utc),
        pstatus=processing_status
    ))
    row = r.first()
    if not row:
        raise HTTPException(status_code=500, detail="Item kon niet worden aangemaakt")
    item_id = row[0]

    # Link to topic
    await session.exec(sa_text(
        "INSERT INTO item_topics (item_id, topic_id) VALUES (CAST(:iid AS uuid), CAST(:tid AS uuid))"
    ).bindparams(iid=item_id, tid=topic_id))

    await session.commit()

    return InboxSubmitResponse(
        id=item_id,
        title=title,
        message=f"Item aangemaakt en gekoppeld aan topic '{body.topic_slug}'"
    )


@router.get("/inbox/topics")
async def inbox_topics(
    session=Depends(get_async_session),
    user=Depends(require_user),
):
    """Get list of topics for the inbox dropdown."""
    rows = (await session.exec(sa_text(
        "SELECT slug, name FROM topics ORDER BY sort_order, name"
    ))).all()
    return [{"slug": r[0], "name": r[1]} for r in rows]
