"""Feed-parsing en item-ingest: refresh, backfill, og:image-scraping.

Alle functies nemen een expliciete httpx.AsyncClient (geen module-global app)
zodat ze los testbaar zijn en de caller bepaalt welke pool wordt gebruikt.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx
from sqlalchemy import text as sa_text

from core.url_guard import UnsafeURLError, assert_public_url
from core.url_guard import safe_get as _safe_get
from pipeline.articles import extract_article_body

log = logging.getLogger("stroom.feeds")

KIND_TO_FORMAT = {"rss": "article", "podcast": "podcast", "youtube": "video"}

INBOX_SOURCE_NAME = "Inbox (handmatig)"


def feed_first_text(entry, *keys):
    for k in keys:
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list) and v and isinstance(v[0], dict) and v[0].get("value"):
            return v[0]["value"].strip()
    return None


def feed_media_url(entry):
    # Skip image-enclosures: veel RSS-feeds hangen featured images aan als enclosure.
    # Die horen in thumbnail_url, niet in media_url (die wordt als 'open original' link gebruikt).
    for enc in entry.get("enclosures") or []:
        if not enc.get("url"):
            continue
        t = (enc.get("type") or "").lower()
        if t.startswith("image/"):
            continue
        return enc["url"]
    if entry.get("media_content"):
        for mc in entry["media_content"]:
            if not mc.get("url"):
                continue
            t = (mc.get("type") or "").lower()
            if t.startswith("image/"):
                continue
            return mc["url"]
    return entry.get("link")


def feed_thumb_url(entry):
    if entry.get("media_thumbnail"):
        return entry["media_thumbnail"][0].get("url")
    # Per-episode itunes:image (podcasts) of generieke image-tag.
    v = entry.get("itunes_image") or entry.get("image")
    if isinstance(v, dict):
        return v.get("href") or v.get("url")
    if isinstance(v, str):
        return v
    return None


_OG_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']', re.I),
]


async def scrape_og_image(client: httpx.AsyncClient, url: str) -> Optional[str]:
    """Fetch URL, return og:image / twitter:image. Best-effort: returns None on any failure."""
    if not url:
        return None
    try:
        r = await _safe_get(
            client,
            url,
            headers={"User-Agent": "StroomBot/1.0 (+image-ingest)"},
            timeout=8.0,
        )
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return None
        head = r.text[:200_000]
        for pat in _OG_PATTERNS:
            m = pat.search(head)
            if m:
                img = m.group(1).strip()
                if img.startswith("//"):
                    return "https:" + img
                if img.startswith("/"):
                    from urllib.parse import urljoin
                    return urljoin(url, img)
                return img
    except Exception:
        return None
    return None


async def refresh_one(http_client: httpx.AsyncClient, session, src) -> dict:
    """Fetch src's feed, upsert items, return {inserted, checked, error?}."""
    from datetime import datetime, timezone

    import feedparser

    # SSRF-guard: safe_get hieronder valideert de URL én elke redirect-hop
    # tegen intern-adres-misbruik. De upfront assert_public_url is een vroege
    # short-circuit voordat we een connectie openen.
    try:
        await assert_public_url(src.url)
    except UnsafeURLError as exc:
        await session.exec(sa_text(
            "UPDATE sources SET last_polled_at = now(), last_poll_status = :st "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(st=f"error: {str(exc)[:120]}", i=str(src.id)))
        return {"inserted": 0, "checked": 0, "error": str(exc)}

    # Fetch via httpx met harde timeout (30s). feedparser.parse(url) doet zelf
    # een synchrone urllib-fetch zonder timeout in de gedeelde default
    # ThreadPoolExecutor; een host die de connectie accepteert maar nooit
    # antwoordt wedged die thread permanent — asyncio.wait_for(90s) cancelt de
    # coroutine maar kan de OS-thread niet doden. Zodra de ~12 executor-threads
    # vol zitten met gewedgede fetches, blokkeert élke volgende refresh (ook
    # naar gezonde feeds) op een vrije thread → uniform 90s-stall. Bytes aan
    # feedparser.parse geven = geen ongetimede netwerk-call meer in de
    # executor; die parset enkel gedownloade bytes (snel, begrensd). Zelfde
    # patroon als backfill_one hieronder.
    try:
        resp = await _safe_get(
            http_client,
            src.url,
            headers={"User-Agent": "StroomBot/1.0 (+refresh)"},
            timeout=30.0,
        )
        resp.raise_for_status()
        feed_bytes = resp.content
    except Exception as e:
        # repr(e) maakt het exceptie-type zichtbaar — str(e) is vaak leeg
        # (bijv. ConnectError/ReadError), net als bij quality_service.score_quality.
        await session.exec(sa_text(
            "UPDATE sources SET last_polled_at = now(), last_poll_status = :st "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(st=f"error: fetch: {repr(e)[:200]}", i=str(src.id)))
        return {"inserted": 0, "checked": 0, "error": f"fetch: {repr(e)}"}

    feed = await asyncio.get_event_loop().run_in_executor(None, feedparser.parse, feed_bytes)
    if feed.bozo and not feed.entries:
        err = str(getattr(feed, "bozo_exception", "unknown"))
        await session.exec(sa_text(
            "UPDATE sources SET last_polled_at = now(), last_poll_status = :st "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(st=f"error: {err[:120]}", i=str(src.id)))
        return {"inserted": 0, "checked": 0, "error": err}

    fmt = KIND_TO_FORMAT.get(src.kind, "article")
    inserted = 0
    for entry in feed.entries[:20]:
        ext_id = entry.get("id") or entry.get("link")
        if not ext_id:
            continue
        title = feed_first_text(entry, "title") or "(untitled)"
        desc = feed_first_text(entry, "summary", "description")
        author = feed_first_text(entry, "author")
        published = None
        st = entry.get("published_parsed") or entry.get("updated_parsed")
        if st:
            published = datetime(*st[:6], tzinfo=timezone.utc)

        media = feed_media_url(entry)
        thumb = feed_thumb_url(entry)
        # Geen feed-thumbnail én een artikel-URL → og:image scrapen.
        # Skip podcasts (media_url is audio) en youtube (heeft eigen thumb pad).
        if not thumb and media and src.kind == "rss":
            thumb = await scrape_og_image(http_client, media)

        r = await session.exec(sa_text(
            """
            INSERT INTO items
                (source_id, external_id, type, format, title, description,
                 author, media_url, thumbnail_url, published_at,
                 processing_status, status)
            VALUES (CAST(:s AS uuid), :e, CAST(:k AS content_kind), CAST(:f AS item_format),
                    :t, :d, :a, :m, :th, :p, 'ready', 'new')
            ON CONFLICT (source_id, external_id) DO NOTHING
            RETURNING id::text
            """
        ).bindparams(s=str(src.id), e=ext_id, k=src.kind, f=fmt, t=title, d=desc,
                     a=author, m=media, th=thumb, p=published))
        row = r.first()
        if not row:
            continue
        new_item_id = row[0]
        await session.exec(sa_text(
            """
            INSERT INTO item_topics (item_id, topic_id)
            SELECT CAST(:i AS uuid), st.topic_id
            FROM source_topics st WHERE st.source_id = CAST(:s AS uuid)
            """
        ).bindparams(i=new_item_id, s=str(src.id)))
        inserted += 1

        # Voor articles: full body via trafilatura, opslaan in transcript.
        # Best-effort: bij failure blijft description de fallback.
        if fmt == "article" and media:
            body = await extract_article_body(http_client, media)
            if body:
                await session.exec(sa_text(
                    "UPDATE items SET transcript = :t WHERE id = CAST(:i AS uuid)"
                ).bindparams(t=body, i=new_item_id))

    await session.exec(sa_text(
        "UPDATE sources SET last_polled_at = now(), last_poll_status = :st "
        "WHERE id = CAST(:i AS uuid)"
    ).bindparams(st=f"refreshed: {inserted} new", i=str(src.id)))
    return {"inserted": inserted, "checked": len(feed.entries[:20])}


async def backfill_one(http_client: httpx.AsyncClient, session, src, target_new: int) -> dict:
    """Parse the full feed and insert up to `target_new` items not yet in DB.

    Unlike refresh_one which caps at the first 20 feed entries, this iterates
    every entry — so for feeds that ship the full archive (most podcasts) this
    pulls older episodes. Stops as soon as `target_new` new items have been
    inserted; relies on ON CONFLICT DO NOTHING to skip what's already stored.
    """
    from datetime import datetime, timezone

    import feedparser

    # Fetch via httpx so we get a hard timeout (feedparser's default urllib
    # call can hang on slow podcast hosts).
    try:
        resp = await _safe_get(
            http_client,
            src.url,
            headers={"User-Agent": "StroomBot/1.0 (+backfill)"},
            timeout=30.0,
        )
        resp.raise_for_status()
        feed_bytes = resp.content
    except Exception as e:
        return {"inserted": 0, "checked": 0, "feed_total": 0, "error": f"fetch: {e}"}

    feed = await asyncio.get_event_loop().run_in_executor(None, feedparser.parse, feed_bytes)
    if feed.bozo and not feed.entries:
        return {"inserted": 0, "checked": 0, "feed_total": 0,
                "error": str(getattr(feed, "bozo_exception", "unknown"))}

    fmt = KIND_TO_FORMAT.get(src.kind, "article")
    inserted = 0
    checked = 0
    for entry in feed.entries:
        if inserted >= target_new:
            break
        checked += 1
        ext_id = entry.get("id") or entry.get("link")
        if not ext_id:
            continue
        title = feed_first_text(entry, "title") or "(untitled)"
        desc = feed_first_text(entry, "summary", "description")
        author = feed_first_text(entry, "author")
        published = None
        st = entry.get("published_parsed") or entry.get("updated_parsed")
        if st:
            published = datetime(*st[:6], tzinfo=timezone.utc)

        media = feed_media_url(entry)
        thumb = feed_thumb_url(entry)
        # Skip og:image scrape during backfill — synchronous and slow.

        r = await session.exec(sa_text(
            """
            INSERT INTO items
                (source_id, external_id, type, format, title, description,
                 author, media_url, thumbnail_url, published_at,
                 processing_status, status)
            VALUES (CAST(:s AS uuid), :e, CAST(:k AS content_kind), CAST(:f AS item_format),
                    :t, :d, :a, :m, :th, :p, 'ready', 'new')
            ON CONFLICT (source_id, external_id) DO NOTHING
            RETURNING id::text
            """
        ).bindparams(s=str(src.id), e=ext_id, k=src.kind, f=fmt, t=title, d=desc,
                     a=author, m=media, th=thumb, p=published))
        row = r.first()
        if not row:
            continue
        new_item_id = row[0]
        await session.exec(sa_text(
            """
            INSERT INTO item_topics (item_id, topic_id)
            SELECT CAST(:i AS uuid), st.topic_id
            FROM source_topics st WHERE st.source_id = CAST(:s AS uuid)
            """
        ).bindparams(i=new_item_id, s=str(src.id)))
        inserted += 1

    return {"inserted": inserted, "checked": checked, "feed_total": len(feed.entries)}


async def backfill_missing_thumbnails(http_client: httpx.AsyncClient, session, limit: int) -> int:
    """Scrape og:image voor RSS-items die nog geen thumbnail hebben. Returns count gevuld."""
    rows = (await session.exec(sa_text(
        """
        SELECT i.id::text, i.media_url
        FROM items i
        WHERE i.thumbnail_url IS NULL
          AND i.media_url IS NOT NULL
          AND i.type = 'rss'::content_kind
        ORDER BY i.published_at DESC NULLS LAST
        LIMIT :lim
        """
    ).bindparams(lim=limit))).all()
    filled = 0
    for iid, url in rows:
        img = await scrape_og_image(http_client, url)
        if img:
            await session.exec(sa_text(
                "UPDATE items SET thumbnail_url=:t WHERE id = CAST(:i AS uuid)"
            ).bindparams(t=img, i=iid))
            filled += 1
    if filled:
        await session.commit()
    return filled
