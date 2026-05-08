"""Inbox router - handmatig content insturen voor verwerking."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.auth import require_user
from core.db import get_async_session, async_session_maker

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


class InboxFetchRequest(BaseModel):
    url: str


class InboxFetchResponse(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    format: InboxFormat
    thumbnail_url: Optional[str] = None


# Inbox source ID (created manually in DB)
INBOX_SOURCE_NAME = "Inbox (handmatig)"


async def _extract_article_body(client, url: str) -> Optional[str]:
    """Best-effort full-article extractie via trafilatura."""
    try:
        import trafilatura
        r = await client.get(
            url,
            headers={"User-Agent": "StroomBot/1.0 (+article-ingest)"},
            timeout=12.0, follow_redirects=True,
        )
        if r.status_code != 200:
            return None
        ct = r.headers.get("content-type", "").lower()
        if "html" not in ct and "xml" not in ct:
            return None

        text = trafilatura.extract(
            r.text,
            include_comments=False, include_tables=False,
            include_links=True, include_formatting=True, include_images=True,
            output_format="markdown",
        )
        if not text or len(text.split()) < 100:
            return None
        return text
    except Exception:
        return None


@router.post("/inbox/submit", response_model=InboxSubmitResponse)
async def inbox_submit(
    body: InboxSubmitRequest,
    request: Request,
    session=Depends(get_async_session),
    user=Depends(require_user),
):
    """Submit a new item to the inbox for processing.

    The item will be:
    - Created with processing_status='pending' (articles) or 'queued' (audio/video)
    - Linked to the selected topic
    - Processed by the normal pipeline (summarize/transcribe → distill lessons)
    - For articles: full content extracted via trafilatura and stored in transcript
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

    # Determine initial processing status based on format
    # Articles: pending (will be picked up by article summarizer)
    # Podcast/Video: queued (will be transcribed automatically)
    if body.format == "article":
        processing_status = "pending"
    else:
        processing_status = "queued"

    # For articles: extract full content via trafilatura
    article_body: Optional[str] = None
    if body.format == "article":
        article_body = await _extract_article_body(request.app.state.http_client, url)

    # Insert item
    r = await session.exec(sa_text(
        """
        INSERT INTO items
            (source_id, external_id, type, format, title, description,
             author, media_url, published_at,
             processing_status, status, transcript)
        VALUES (CAST(:sid AS uuid), :eid, CAST(:kind AS content_kind), CAST(:fmt AS item_format),
                :title, :desc, :author, :url, :pub,
                CAST(:pstatus AS processing_status), 'new', :transcript)
        ON CONFLICT (source_id, external_id) DO UPDATE
            SET title = EXCLUDED.title,
                description = EXCLUDED.description,
                author = EXCLUDED.author,
                format = EXCLUDED.format,
                transcript = EXCLUDED.transcript
        RETURNING id::text
        """
    ).bindparams(
        sid=source_id, eid=ext_id, kind=content_kind, fmt=body.format,
        title=title, desc=body.description or None, author=body.author or None,
        url=url, pub=datetime.now(timezone.utc),
        pstatus=processing_status,
        transcript=article_body
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

    # After commit, trigger summarize for articles with transcript
    if body.format == "article" and article_body:
        try:
            from services.llm_service import LLMService
            llm = LLMService(request.app.state.http_client)
            asyncio.create_task(_summarize_inbox_article(item_id, article_body, llm))
        except Exception as e:
            print(f"[inbox] Failed to trigger summarize: {e}", flush=True)

    return InboxSubmitResponse(
        id=item_id,
        title=title,
        message=f"Item aangemaakt en gekoppeld aan topic '{body.topic_slug}'"
    )


async def _summarize_inbox_article(item_id: str, article_body: str, llm_service):
    """Background task to summarize an inbox article and distill lessons."""
    try:
        # Truncate if too long
        cleaned = re.sub(r"\s+", " ", article_body)[:12000]

        response = await llm_service.call_llm("stroom-bulk", [
            {"role": "system", "content": (
                "Je bent een curator van hoogwaardige content. Vat het artikel samen in het "
                "Nederlands, zakelijk maar warm, max 3 zinnen.\n\n"
                "Beoordeel daarna de kwaliteit (1-10) op:\n"
                "- Nieuwswaarde: is dit echt nieuw of oud nieuws?\n"
                "- Diepgang: gaat het verder dan het oppervlakte?\n"
                "- Originaliteit: uniek perspectief of standaard bericht?\n\n"
                "VERPLICHT: geef ALTIJD een quality_score terug als integer 1-10. "
                "Als je echt niet kunt beoordelen, gebruik dan null.\n\n"
                "Output strikt als JSON: {\"summary\": \"...\", \"quality_score\": 7}"
            )},
            {"role": "user", "content": f"Tekst: {cleaned}"},
        ], temperature=0.3, response_format="json_object")

        import json as _json
        try:
            data = _json.loads(response)
            summary = data.get("summary", "").strip()
            # Only set quality_score if LLM actually provides one; otherwise None (neutral)
            raw_score = data.get("quality_score")
            if raw_score is not None:
                try:
                    quality_score = max(1, min(10, int(raw_score)))
                except (TypeError, ValueError):
                    quality_score = None
            else:
                quality_score = None
        except Exception:
            summary = response.strip() if response else ""
            quality_score = None

        # Update item in database
        async with async_session_maker() as bg:
            await bg.exec(sa_text(
                "UPDATE items SET summary=:s, summary_model='stroom-bulk', "
                "summary_generated_at=now(), processing_status='ready'::processing_status, "
                "quality_score=:q WHERE id = CAST(:i AS uuid)"
            ).bindparams(s=summary, i=item_id, q=quality_score))
            await bg.commit()

        print(f"[inbox] Article {item_id} summarized", flush=True)

        # Now distill lessons from the summary
        await _distill_inbox_lessons(item_id, summary, article_body, llm_service)
    except Exception as exc:
        print(f"[inbox] Summarize failed for {item_id}: {exc}", flush=True)


async def _distill_inbox_lessons(item_id: str, summary: str, article_body: str, llm_service):
    """Distill lessons from article summary."""
    try:
        body_text = article_body.strip()[:18000]
        if not body_text:
            return

        system = (
            "Je destilleert kernlessen uit een bron (artikel). "
            "Lever concrete, bruikbare lessen die de kern van het artikel vangen.\n\n"
            "Output: strikt JSON, vorm: {\"lessons\": [{\"title\": \"…\", \"body\": \"…\"}]}\n"
            "- title: korte kop (4-8 woorden)\n"
            "- body: 1-3 zinnen, concreet en bruikbaar\n"
            "Maximaal 5 lessen. Liever 0 dan oppervlakkig."
        )
        user_prompt = f"Samenvatting: {summary}\n\nArtikel tekst:\n{body_text}"

        raw = await llm_service.call_llm(
            "stroom-bulk",
            [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
            temperature=0.4, response_format="json_object", timeout=240.0,
        )

        import json
        try:
            data = json.loads(raw)
            new_lessons = data.get("lessons", []) or []
        except json.JSONDecodeError:
            print(f"[inbox] Invalid JSON for lessons {item_id}", flush=True)
            return

        async with async_session_maker() as bg:
            inserted = 0
            for idx, entry in enumerate(new_lessons, start=1):
                t = (entry.get("title") or "").strip()
                b = (entry.get("body") or "").strip()
                if not t or not b:
                    continue
                await bg.exec(sa_text(
                    "INSERT INTO lessons (item_id, idx, title, body) "
                    "VALUES (CAST(:i AS uuid), :idx, :t, :b)"
                ).bindparams(i=item_id, idx=idx, t=t, b=b))
                inserted += 1
            if inserted:
                await bg.commit()
                print(f"[inbox] Article {item_id} distilled {inserted} lessons", flush=True)
    except Exception as exc:
        print(f"[inbox] Distill lessons failed for {item_id}: {exc}", flush=True)


def _detect_format_from_url(url: str) -> InboxFormat:
    """Detect format based on URL patterns."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    path = parsed.path or ""

    # YouTube
    if "youtube.com" in hostname or "youtu.be" in hostname:
        return "video"
    # Spotify, Apple Podcasts
    if "spotify.com" in hostname or "podcasts.apple.com" in hostname:
        return "podcast"
    # SoundCloud (often podcasts)
    if "soundcloud.com" in hostname:
        return "podcast"
    # Vimeo
    if "vimeo.com" in hostname:
        return "video"
    # Default to article
    return "article"


async def _fetch_url_metadata(client, url: str) -> InboxFetchResponse:
    """Fetch metadata from URL using trafilatura for articles or page scraping."""
    fmt = _detect_format_from_url(url)

    # For YouTube videos, extract info from URL/oEmbed
    if fmt == "video" and ("youtube.com" in url or "youtu.be" in url):
        return await _fetch_youtube_metadata(client, url)

    # For articles and other content, use trafilatura
    try:
        r = await client.get(
            url,
            headers={"User-Agent": "StroomBot/1.0 (+inbox-fetch)"},
            timeout=10.0, follow_redirects=True,
        )
        if r.status_code != 200:
            return InboxFetchResponse(url=url, format=fmt)

        html = r.text

        # Extract title from various sources
        title = None
        # Try og:title first
        og_title_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.I)
        if og_title_match:
            title = og_title_match.group(1).strip()
        # Try twitter:title
        if not title:
            tw_title_match = re.search(r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)', html, re.I)
            if tw_title_match:
                title = tw_title_match.group(1).strip()
        # Fallback to title tag
        if not title:
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
            if title_match:
                title = title_match.group(1).strip()

        # Extract description
        desc = None
        og_desc_match = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)', html, re.I)
        if og_desc_match:
            desc = og_desc_match.group(1).strip()
        if not desc:
            meta_desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html, re.I)
            if meta_desc_match:
                desc = meta_desc_match.group(1).strip()

        # Extract author
        author = None
        og_author_match = re.search(r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)', html, re.I)
        if og_author_match:
            author = og_author_match.group(1).strip()

        # Extract thumbnail
        thumb = None
        og_image_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
        if og_image_match:
            thumb = og_image_match.group(1).strip()

        # For articles, try trafilatura for better content
        if fmt == "article":
            try:
                import trafilatura
                extracted = trafilatura.extract(
                    html,
                    include_comments=False, include_tables=False,
                    include_links=False, include_formatting=False,
                    target_language="nl",
                )
                if extracted and not desc:
                    # Use first paragraph as description
                    first_para = extracted.strip().split('\n')[0][:500]
                    if first_para:
                        desc = first_para
            except Exception:
                pass

        return InboxFetchResponse(
            url=url,
            title=title,
            description=desc,
            author=author,
            format=fmt,
            thumbnail_url=thumb,
        )
    except Exception:
        return InboxFetchResponse(url=url, format=fmt)


async def _fetch_youtube_metadata(client, url: str) -> InboxFetchResponse:
    """Extract metadata from YouTube page."""
    try:
        # Try to get video ID from URL
        video_id = None
        if "youtu.be" in url:
            video_id = url.split('/')[-1].split('?')[0]
        else:
            match = re.search(r'[?&]v=([^&]+)', url)
            if match:
                video_id = match.group(1)

        r = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; StroomBot/1.0)"},
            timeout=10.0, follow_redirects=True,
        )
        if r.status_code != 200:
            return InboxFetchResponse(url=url, format="video")

        html = r.text

        # Extract title
        title = None
        og_title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.I)
        if og_title:
            title = og_title.group(1).strip()

        # Extract description
        desc = None
        og_desc = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)', html, re.I)
        if og_desc:
            desc = og_desc.group(1).strip()

        # Extract author/channel
        author = None
        # Try to find channel name
        channel_match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'][^"\']*channel/([^"\'\']+)', html, re.I)
        if channel_match:
            author = channel_match.group(1)

        # Extract thumbnail
        thumb = None
        if video_id:
            thumb = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
        og_image = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
        if og_image:
            thumb = og_image.group(1).strip()

        return InboxFetchResponse(
            url=url,
            title=title,
            description=desc,
            author=author,
            format="video",
            thumbnail_url=thumb,
        )
    except Exception:
        return InboxFetchResponse(url=url, format="video")


@router.post("/inbox/fetch", response_model=InboxFetchResponse)
async def inbox_fetch(
    body: InboxFetchRequest,
    request: Request,
    user=Depends(require_user),
):
    """Fetch metadata from a URL to pre-fill inbox form.

    Returns title, description, author, detected format, and thumbnail.
    """
    url = (body.url or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Ongeldige URL (moet http:// of https:// zijn)")

    http_client = request.app.state.http_client
    return await _fetch_url_metadata(http_client, url)


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
