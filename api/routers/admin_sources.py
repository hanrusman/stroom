"""Admin: bronnenbeheer, refresh, backfill, bulk-archive (voorheen in main.py)."""
from __future__ import annotations

import asyncio
import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import text as sa_text

from core.auth import require_user
from core.db import get_async_session
from pipeline.articles import backfill_articles as _pipeline_backfill_articles
from pipeline.feeds import backfill_missing_thumbnails, backfill_one, refresh_one
from schemas.admin import (
    AdminSource,
    AdminSourceCreate,
    AdminSourceUpdate,
    BackfillResult,
    BulkArchiveRequest,
    BulkArchiveResponse,
)

log = logging.getLogger("stroom.admin.sources")

router = APIRouter(tags=["admin-sources"])

VALID_KINDS = {"rss", "podcast", "youtube"}

REFRESH_THUMB_BACKFILL_LIMIT = 100


async def _admin_source_row(session, source_id: str) -> AdminSource:
    r = await session.exec(sa_text(
        """
        SELECT s.id::text, s.name, s.url, s.kind::text, s.image_url,
               s.weight, s.max_per_rail, s.active, s.poll_interval_min,
               COALESCE(array_agg(t.slug) FILTER (WHERE t.id IS NOT NULL), '{}') AS slugs,
               (SELECT COUNT(*) FROM items WHERE source_id = s.id) AS item_count
        FROM sources s
        LEFT JOIN source_topics st ON st.source_id = s.id
        LEFT JOIN topics t ON t.id = st.topic_id
        WHERE s.id = CAST(:i AS uuid)
        GROUP BY s.id
        """
    ).bindparams(i=source_id))
    row = r.first()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")
    return AdminSource(
        id=row[0], name=row[1], url=row[2], kind=row[3], image_url=row[4],
        weight=row[5], max_per_rail=row[6], active=row[7], poll_interval_min=row[8],
        topic_slugs=list(row[9]), item_count=row[10],
    )


@router.get("/admin/sources", response_model=List[AdminSource])
async def admin_list_sources(session=Depends(get_async_session),
                             user=Depends(require_user)):
    r = await session.exec(sa_text(
        """
        SELECT s.id::text, s.name, s.url, s.kind::text, s.image_url,
               s.weight, s.max_per_rail, s.active, s.poll_interval_min,
               COALESCE(array_agg(t.slug ORDER BY t.slug) FILTER (WHERE t.id IS NOT NULL), '{}') AS slugs,
               (SELECT COUNT(*) FROM items WHERE source_id = s.id) AS item_count
        FROM sources s
        LEFT JOIN source_topics st ON st.source_id = s.id
        LEFT JOIN topics t ON t.id = st.topic_id
        GROUP BY s.id
        ORDER BY s.active DESC, s.name
        """
    ))
    return [
        AdminSource(
            id=row[0], name=row[1], url=row[2], kind=row[3], image_url=row[4],
            weight=row[5], max_per_rail=row[6], active=row[7], poll_interval_min=row[8],
            topic_slugs=list(row[9]), item_count=row[10],
        )
        for row in r.all()
    ]


async def _set_source_topics(session, source_id: str, slugs: List[str]) -> None:
    await session.exec(sa_text(
        "DELETE FROM source_topics WHERE source_id = CAST(:i AS uuid)"
    ).bindparams(i=source_id))
    if not slugs:
        return
    await session.exec(sa_text(
        """
        INSERT INTO source_topics (source_id, topic_id)
        SELECT CAST(:i AS uuid), id FROM topics WHERE slug = ANY(:s)
        """
    ).bindparams(i=source_id, s=list(slugs)))


@router.patch("/admin/sources/{source_id}", response_model=AdminSource)
async def admin_update_source(source_id: str, body: AdminSourceUpdate,
                              session=Depends(get_async_session),
                              user=Depends(require_user)):
    await _admin_source_row(session, source_id)  # 404 if missing

    fields = body.model_dump(exclude_unset=True, exclude_none=False)
    topic_slugs = fields.pop("topic_slugs", None)

    if "kind" in fields and fields["kind"] not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {VALID_KINDS}")
    if "weight" in fields and fields["weight"] is not None:
        if not 1 <= fields["weight"] <= 10:
            raise HTTPException(status_code=400, detail="weight 1-10")
    if "max_per_rail" in fields and fields["max_per_rail"] is not None and fields["max_per_rail"] < 1:
        raise HTTPException(status_code=400, detail="max_per_rail moet ≥1 of null zijn")

    # Bouw dynamische UPDATE
    set_parts = []
    params: dict = {"i": source_id}
    for k, v in fields.items():
        if k == "kind":
            set_parts.append(f"{k} = CAST(:{k} AS content_kind)")
        else:
            set_parts.append(f"{k} = :{k}")
        params[k] = v
    if set_parts:
        await session.exec(sa_text(
            f"UPDATE sources SET {', '.join(set_parts)} WHERE id = CAST(:i AS uuid)"
        ).bindparams(**params))

    if topic_slugs is not None:
        await _set_source_topics(session, source_id, topic_slugs)

    await session.commit()
    return await _admin_source_row(session, source_id)


@router.post("/admin/sources", response_model=AdminSource)
async def admin_create_source(body: AdminSourceCreate,
                              session=Depends(get_async_session),
                              user=Depends(require_user)):
    if body.kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {VALID_KINDS}")
    if not 1 <= body.weight <= 10:
        raise HTTPException(status_code=400, detail="weight 1-10")
    if body.max_per_rail is not None and body.max_per_rail < 1:
        raise HTTPException(status_code=400, detail="max_per_rail moet ≥1 of null zijn")

    r = await session.exec(sa_text(
        """
        INSERT INTO sources (name, url, kind, image_url, weight, max_per_rail, active, poll_interval_min)
        VALUES (:n, :u, CAST(:k AS content_kind), :img, :w, :mpr, :a, :poll)
        RETURNING id::text
        """
    ).bindparams(n=body.name, u=body.url, k=body.kind, img=body.image_url,
                 w=body.weight, mpr=body.max_per_rail, a=body.active,
                 poll=body.poll_interval_min))
    new_id = r.first()[0]
    if body.topic_slugs:
        await _set_source_topics(session, new_id, body.topic_slugs)
    await session.commit()
    return await _admin_source_row(session, new_id)


@router.post("/admin/sources/{source_id}/refresh")
async def admin_refresh_source(source_id: str, request: Request,
                               session=Depends(get_async_session),
                               user=Depends(require_user)):
    """Pull latest items from this source's feed and insert new ones."""
    src = await _admin_source_row(session, source_id)
    result = await refresh_one(request.app.state.http_client, session, src)
    if "error" in result:
        await session.commit()
        raise HTTPException(status_code=502, detail=f"Feed parse error: {result['error']}")
    await session.commit()
    return {"ok": True, **result}


@router.post("/sources/{source_id}/backfill", response_model=BackfillResult)
async def backfill_source(source_id: UUID, request: Request,
                          count: int = Query(20, ge=1, le=100),
                          session=Depends(get_async_session),
                          user=Depends(require_user)):
    """Fetch the source's feed and insert up to `count` older items not yet in DB.

    Useful for podcasts/feeds that publish their full archive: lets the UI
    page back beyond what nightly polling has captured.
    """
    src = await _admin_source_row(session, str(source_id))
    result = await backfill_one(request.app.state.http_client, session, src, target_new=count)
    if "error" in result:
        # No partial state to commit — backfill_one returns early on fetch/parse
        # failure, before any INSERTs run.
        raise HTTPException(status_code=502, detail=f"Feed error: {result['error']}")
    await session.commit()
    return BackfillResult(
        inserted=result["inserted"],
        checked=result["checked"],
        feed_total=result["feed_total"],
    )


async def _bg_backfill_thumbnails(http_client, limit: int):
    """Achter de response: nieuwe DB-sessie, scrape, commit. Best-effort, logged."""
    from core.db import async_session_maker
    try:
        async with async_session_maker() as bg_session:
            n = await backfill_missing_thumbnails(http_client, bg_session, limit)
            log.info("[refresh-all bg] %d thumbnails gevuld", n)
    except Exception as exc:
        log.warning("[refresh-all bg] thumbnail backfill faalde: %s", exc)


@router.post("/admin/sources/refresh-all")
async def admin_refresh_all(background_tasks: BackgroundTasks, request: Request,
                            session=Depends(get_async_session),
                            user=Depends(require_user)):
    """Refresh every active source. Schedules thumbnail-backfill als achtergrondtaak.

    Zelfde watchdogs als /admin/cron/nightly: per-bron 90s + globale 1800s.
    Voorkomt dat één hangende feed de hele admin-actie bevriest (wat eerder
    gebeurde en de DB-pool liet vollopen met idle-in-transaction zombies).
    """
    http_client = request.app.state.http_client

    async def _run() -> dict:
        r = await session.exec(sa_text(
            "SELECT id, name, kind::text, url FROM sources WHERE active ORDER BY name"
        ))
        rows = r.all()
        total_inserted = 0
        total_checked = 0
        errors = 0
        per_source = []
        for row in rows:
            src = type("S", (), {"id": row[0], "name": row[1], "kind": row[2], "url": row[3]})
            try:
                res = await asyncio.wait_for(refresh_one(http_client, session, src), timeout=90.0)
                await session.commit()
            except asyncio.TimeoutError:
                await session.rollback()
                res = {"inserted": 0, "checked": 0, "error": "timeout na 90s"}
                log.warning("[refresh-all] %s timeout na 90s — overgeslagen", row[1])
            except Exception as e:
                await session.rollback()
                res = {"inserted": 0, "checked": 0, "error": str(e)[:200]}
            if "error" in res:
                errors += 1
            total_inserted += res.get("inserted", 0)
            total_checked += res.get("checked", 0)
            per_source.append({"name": row[1], **res})

        background_tasks.add_task(_bg_backfill_thumbnails, http_client, REFRESH_THUMB_BACKFILL_LIMIT)

        return {
            "ok": True,
            "sources": len(rows),
            "errors": errors,
            "inserted": total_inserted,
            "checked": total_checked,
            "thumbnails_scheduled": REFRESH_THUMB_BACKFILL_LIMIT,
            "per_source": per_source,
        }

    try:
        return await asyncio.wait_for(_run(), timeout=1800.0)
    except asyncio.TimeoutError:
        try:
            await session.rollback()
        except Exception:
            pass
        log.warning("[refresh-all] timeout na 1800s — afgekapt")
        return {
            "ok": False,
            "error": "timeout: refresh-all exceeded 1800 seconds",
        }


@router.post("/admin/sources/backfill-stale")
async def admin_sources_backfill_stale(request: Request,
                                       stale_days: int = Query(5, ge=1, le=90),
                                       session=Depends(get_async_session)):
    """Ververs álle actieve bronnen waarvan last_polled_at ouder is dan
    `stale_days` dagen (of NULL — nog nooit gepolld). Bedoeld als
    'inhaalronde' nadat de nightly een tijd niet heeft gedraaid (zoals
    het 2026-06-20 incident). Per-bron 90s watchdog + globale 1800s —
    dezelfde bescherming als /admin/cron/nightly.

    In tegenstelling tot /admin/cron/nightly doet deze endpoint géén
    transcribe/summarize/digest-stappen: alleen feed-pull, items
    invoegen, last_polled_at bijwerken. De workers pikken de nieuwe
    'ready'/'new' items vanzelf op bij de volgende nightly-kick, of je
    draait daarna apart /admin/cron/summarize-articles etc.

    Auth: internal token (zelfde als nightly).
    """
    threshold_days = stale_days
    http_client = request.app.state.http_client

    async def _run() -> dict:
        rows = (await session.exec(sa_text(f"""
            SELECT id, name, kind::text, url,
                   EXTRACT(EPOCH FROM (now() - last_polled_at))::int AS age_s
            FROM sources
            WHERE active
              AND (last_polled_at IS NULL
                   OR last_polled_at < now() - interval '{threshold_days} days')
            ORDER BY last_polled_at NULLS FIRST, name
        """))).all()
        refreshed = 0
        errors = 0
        inserted_total = 0
        per_source = []
        for row in rows:
            src = type("S", (), {"id": row[0], "name": row[1], "kind": row[2], "url": row[3]})
            try:
                res = await asyncio.wait_for(refresh_one(http_client, session, src), timeout=90.0)
                await session.commit()
                refreshed += 1
                inserted_total += res.get("inserted", 0)
                if "error" in res:
                    errors += 1
            except asyncio.TimeoutError:
                await session.rollback()
                errors += 1
                res = {"error": "timeout"}
                log.warning("[backfill-stale] %s timeout na 90s — overgeslagen", row[1])
            except Exception as exc:
                await session.rollback()
                errors += 1
                res = {"error": str(exc)[:200]}
                log.warning("[backfill-stale] %s faalde: %s", row[1], exc)
            per_source.append({
                "name": row[1],
                "kind": row[2],
                "age_seconds_before": row[4],
                **({"inserted": res.get("inserted", 0)} if "error" not in res else {"error": res["error"]}),
            })

        return {
            "ok": True,
            "stale_days": threshold_days,
            "candidates": len(rows),
            "sources_refreshed": refreshed,
            "refresh_errors": errors,
            "new_items_inserted": inserted_total,
            "per_source": per_source,
        }

    try:
        return await asyncio.wait_for(_run(), timeout=1800.0)
    except asyncio.TimeoutError:
        try:
            await session.rollback()
        except Exception:
            pass
        log.warning("[backfill-stale] timeout na 1800s — afgekapt")
        return {
            "ok": False,
            "error": "timeout: backfill-stale exceeded 1800 seconds",
        }


@router.delete("/admin/sources/{source_id}")
async def admin_delete_source(source_id: str,
                              session=Depends(get_async_session),
                              user=Depends(require_user)):
    """Hard delete; cascades to items, item_topics, source_topics."""
    r = await session.exec(sa_text(
        "DELETE FROM sources WHERE id = CAST(:i AS uuid) RETURNING id"
    ).bindparams(i=source_id))
    if not r.first():
        raise HTTPException(status_code=404, detail="Source not found")
    await session.commit()
    return {"ok": True}


@router.post("/admin/articles/backfill")
async def admin_articles_backfill(background_tasks: BackgroundTasks, request: Request,
                                  days: int = Query(14, le=90),
                                  limit: int = Query(500, le=2000),
                                  user=Depends(require_user)):
    """Trigger background trafilatura-extractie voor articles zonder transcript."""
    from core.db import async_session_maker
    background_tasks.add_task(_pipeline_backfill_articles,
                              request.app.state.http_client, async_session_maker, days, limit)
    return {"ok": True, "started": True, "days": days, "limit": limit}


@router.post("/admin/items/bulk-archive", response_model=BulkArchiveResponse)
async def admin_bulk_archive(body: BulkArchiveRequest,
                             session=Depends(get_async_session),
                             user=Depends(require_user)):
    """Archiveer items in bulk op basis van filters (topic, datum, weight, format)."""
    if not body.topic_slugs:
        raise HTTPException(status_code=400, detail="Minstens 1 topic vereist")
    if not body.formats:
        raise HTTPException(status_code=400, detail="Minstens 1 format vereist")
    if body.older_than_days < 1:
        raise HTTPException(status_code=400, detail="older_than_days moet >= 1 zijn")
    if not (1 <= body.weight_max <= 10):
        raise HTTPException(status_code=400, detail="weight_max moet 1-10 zijn")
    # "short" is uitgecommentarieerd in ItemFormat (zie models/base.py
    # TODO 2026-06-20). Archive-allowlist gespiegeld.
    _ALLOWED_FORMATS = {"article", "podcast", "video"}
    if any(f not in _ALLOWED_FORMATS for f in body.formats):
        raise HTTPException(status_code=400, detail=f"format moet een van {_ALLOWED_FORMATS}")

    result = await session.exec(sa_text("""
        UPDATE items i
        SET status = 'archived'::item_status
        FROM sources s
        JOIN source_topics st ON st.source_id = s.id
        JOIN topics t ON t.id = st.topic_id
        WHERE i.source_id = s.id
          AND t.slug = ANY(:topic_slugs)
          AND i.format::text = ANY(:formats)
          AND i.status != 'archived'::item_status
          AND i.created_at < now() - (:older_days * interval '1 day')
          AND s.weight <= :weight_max
        RETURNING i.id
    """).bindparams(
        topic_slugs=list(body.topic_slugs),
        formats=list(body.formats),
        older_days=body.older_than_days,
        weight_max=body.weight_max,
    ))
    archived_ids = result.all()
    await session.commit()
    return BulkArchiveResponse(archived=len(archived_ids))
