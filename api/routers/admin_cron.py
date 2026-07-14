"""Admin: cron-orkestratie (nightly, queue-vulling, watchdog) — voorheen in main.py."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text as sa_text

from core.auth import require_user
from core.config import settings
from core.db import get_async_session
from pipeline.digest import DIGEST_GENERATION_STALE_MIN
from pipeline.feeds import refresh_one
from routers.digests import DIGEST_WINDOWS, WEEKLY_MIN_AGE_HOURS, DigestModel, DigestWindow, run_digest_generation_bg
from schemas.admin import QueueItem
from workers import monitor

log = logging.getLogger("stroom.admin.cron")

router = APIRouter(tags=["admin-cron"])

CRON_WEIGHT_MIN = 5
CRON_MAX_TRANSCRIBE_ATTEMPTS = 3
CRON_SKIP_ATTEMPTS = 99  # sentinel: items met deze waarde worden nooit meer geprobeerd
CRON_STUCK_ACTIVE_MIN = 5  # heartbeat-timeout: actief item zonder ping voor N min = écht hangend.
                           # Hergebruikt als minimum-leeftijd voor queue-items vóór ze als 'stalled'
                           # kunnen tellen (anders zou net-binnen-gequeued tijdens een API-restart-blip
                           # direct gefaald worden).
CRON_NIGHTLY_HOURS = 24 * 7  # nightly kijkt 7 dagen terug — vangnet voor items die door piek/restart gemist zijn


async def _cron_unstuck(session) -> int:
    """Reset items stuck in queues/processing.

    Strategie:
    - Actief-bezig items (transcribing/summarizing): meet liveness via heartbeat.
      Geen ping voor N min = hangend.
    - In-queue items: wachten is OK zolang er ergens een actief item is met
      verse heartbeat. Pas als de pipeline werkelijk stil staat (geen enkele
      heartbeat in N min) gelden queue-items als 'stalled'. Dit voorkomt
      false-positives bij grote batches/lange podcasts waar semaphore=1 een
      uur queue-wachttijd makkelijk legitiem maakt.

    Self-clean: aan het begin terminaten we andere stroom-api connecties die
    langer dan 5 min in 'idle in transaction' zitten. Dat zijn zombies van
    vorige cron-runs die ergens halverwege refresh_one zijn blijven hangen
    (bv. door een langzame feed-HTTP-call of een crash mid-request). Zonder
    deze stap lekken ze elke nacht opnieuw een connectie en na een paar dagen
    zit de pool vol — exact het probleem dat 2026-06-20 tot een vastgelopen
    nightly leidde. De eigen connectie wordt expliciet uitgesloten.
    """
    try:
        r_zombies = await session.exec(sa_text("""
            SELECT count(*) FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
              AND state = 'idle in transaction'
              AND query_start < now() - interval '5 minutes'
        """))
        n_zombies = r_zombies.scalar() or 0
        if n_zombies:
            log.info("[cron-unstuck] terminating %d zombie idle-in-transaction "
                     "sessie(s) ouder dan 5 min", n_zombies)
            await session.exec(sa_text("""
                SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND state = 'idle in transaction'
                  AND query_start < now() - interval '5 minutes'
            """))
            await session.commit()
    except Exception as exc:
        # pg_terminate mag de rest van _cron_unstuck nooit breken — als de
        # postgres-versie geen current_database() kent of perms ontbreken,
        # log het en ga door met de echte unstuck-stappen.
        log.warning("[cron-unstuck] zombie-clean faalde (genegeerd): %s", exc)
        try:
            await session.rollback()
        except Exception:
            pass

    # Actief-bezig items: liveness-check via heartbeat
    r_active = await session.exec(sa_text(f"""
        UPDATE items SET
          processing_status = 'failed'::processing_status,
          processing_error = 'no heartbeat > {CRON_STUCK_ACTIVE_MIN} min — auto-reset by cron'
        WHERE processing_status IN
              ('transcribing'::processing_status, 'summarizing'::processing_status)
          AND queued_at IS NOT NULL
          AND COALESCE(last_progress_at, queued_at) < now() - interval '{CRON_STUCK_ACTIVE_MIN} minutes'
    """))
    n_active = r_active.rowcount or 0

    # In-queue items: alleen 'stalled' als de pipeline werkelijk stil staat.
    # Twee onafhankelijke liveness-signalen moeten BEIDE dood zijn:
    #  1. geen actief item met verse last_progress_at (SQL, hieronder), én
    #  2. geen worker-loop-heartbeat in de laatste N min (workers/monitor).
    # Signaal 2 is cruciaal bij mem-gate-druk: dan claimt niemand iets (dus geen
    # actief item), maar de workers LEVEN — ze pollen alleen en wachten op RAM.
    # Zonder deze check faalde de watchdog elke ronde de hele getemperde wachtrij.
    workers_alive = monitor.workers_alive(CRON_STUCK_ACTIVE_MIN * 60)
    n_queued_stalled = 0
    if workers_alive:
        log.info("[cron-unstuck] queue-stall-check overgeslagen — workers leven "
                 "(nieuwste heartbeat %.0fs geleden, waarschijnlijk mem-gated)",
                 monitor.newest_beat_age())
    else:
        r_queued = await session.exec(sa_text(f"""
            UPDATE items SET
              processing_status = 'failed'::processing_status,
              processing_error = 'queue stalled (no active workers) — auto-reset by cron'
            WHERE processing_status IN
                  ('queued'::processing_status, 'transcribe_queued'::processing_status,
                   'summarize_queued'::processing_status)
              AND queued_at IS NOT NULL
              AND queued_at < now() - interval '{CRON_STUCK_ACTIVE_MIN} minutes'
              AND NOT EXISTS (
                SELECT 1 FROM items active
                WHERE active.processing_status IN
                      ('transcribing'::processing_status, 'summarizing'::processing_status)
                  AND active.last_progress_at IS NOT NULL
                  AND active.last_progress_at > now() - interval '{CRON_STUCK_ACTIVE_MIN} minutes'
              )
        """))
        n_queued_stalled = r_queued.rowcount or 0
    n = n_active + n_queued_stalled

    # Reset topic digests stuck in queue (worker crasht voordat generatie begint)
    # Dit kan gebeuren als de API herstart terwijl een digest in de wachtrij staat
    r2 = await session.exec(sa_text("""
        UPDATE topic_digests SET is_generating=false, error='wachtrij timeout — worker crashed?'
        WHERE is_generating=true AND generation_started_at IS NULL
          AND queued_at < now() - interval '4 hours'
    """))
    n += r2.rowcount or 0

    # Reset lessons digests stuck in queue
    r3 = await session.exec(sa_text("""
        UPDATE lessons_digests SET is_generating=false, error='wachtrij timeout — worker crashed?'
        WHERE is_generating=true AND generation_started_at IS NULL
          AND queued_at < now() - interval '4 hours'
    """))
    n += r3.rowcount or 0

    await session.commit()
    return n


async def _cron_queue_transcribes(session, *, content_kind: str,
                                  hours: Optional[int] = None,
                                  weight_min: int = CRON_WEIGHT_MIN,
                                  limit: Optional[int] = None) -> int:
    """Mark items as queued for transcription (A2 GPU). Increments transcribe_attempts.

    `content_kind`: 'podcast' or 'youtube'.
    `hours`: only items published in last N hours, or None for all-time backlog.

    Hard cap: nooit meer dan TRANSCRIBE_QUEUE_MAX_DEPTH items totaal in
    de pipeline (queued + transcribing). Bij volle queue: 0.
    """
    r = await session.exec(sa_text(
        "SELECT COUNT(*) FROM items WHERE processing_status IN "
        "('transcribe_queued'::processing_status, 'transcribing'::processing_status)"
    ))
    in_flight = r.first()[0] or 0
    available = max(0, settings.TRANSCRIBE_QUEUE_MAX_DEPTH - in_flight)
    if available == 0:
        log.info("[cron] transcribe-queue vol (%d/%d), niets gequeued voor %s",
                 in_flight, settings.TRANSCRIBE_QUEUE_MAX_DEPTH, content_kind)
        return 0
    effective_limit = min(limit, available) if limit else available

    where_age = "AND i.published_at >= now() - (:hrs * interval '1 hour')" if hours is not None else ""
    sql = """
        WITH picks AS (
          SELECT i.id
          FROM items i
          JOIN sources s ON s.id = i.source_id
          WHERE i.type = CAST(:kind AS content_kind)
            AND s.weight >= :wmin
            AND s.active
            AND (i.transcript IS NULL OR i.transcript = '')
            AND i.media_url IS NOT NULL AND i.media_url <> ''
            AND i.processing_status NOT IN
                ('transcribe_queued'::processing_status, 'transcribing'::processing_status,
                 'queued'::processing_status, 'summarizing'::processing_status)
            AND i.transcribe_attempts < :max_att
            """ + where_age + """
          ORDER BY s.weight DESC, i.published_at DESC
          LIMIT :lim
        )
        UPDATE items SET
          processing_status = 'transcribe_queued'::processing_status,
          queued_at = now(),
          processing_error = NULL,
          transcribe_attempts = transcribe_attempts + 1
        WHERE id IN (SELECT id FROM picks)
        RETURNING id
    """
    params: dict = {"kind": content_kind, "wmin": weight_min,
                    "max_att": CRON_MAX_TRANSCRIBE_ATTEMPTS, "lim": effective_limit}
    if hours is not None:
        params["hrs"] = hours
    r = await session.exec(sa_text(sql).bindparams(**params))
    n = len(r.all())
    await session.commit()
    return n


async def _cron_pick_articles_for_summary(session, *,
                                          hours: Optional[int] = None,
                                          weight_min: int = CRON_WEIGHT_MIN,
                                          limit: int = 200) -> list[str]:
    """Pick articles needing summary, pre-mark als 'summarize_queued'.

    Workers (zie workers/summarize.py) draineren de queue. Cron flipt alleen
    statussen — geen background-task spawn.

    Hard cap: nooit meer dan SUMMARIZE_QUEUE_MAX_DEPTH items totaal in
    de pipeline (queued + summarizing). Bij volle queue: lege list.
    """
    r = await session.exec(sa_text(
        "SELECT COUNT(*) FROM items WHERE processing_status IN "
        "('summarize_queued'::processing_status, 'summarizing'::processing_status)"
    ))
    in_flight = r.first()[0] or 0
    available = max(0, settings.SUMMARIZE_QUEUE_MAX_DEPTH - in_flight)
    if available == 0:
        log.info("[cron] summarize-queue vol (%d/%d), niets gequeued",
                 in_flight, settings.SUMMARIZE_QUEUE_MAX_DEPTH)
        return []
    effective_limit = min(limit, available)

    where_age = "AND i.published_at >= now() - (:hrs * interval '1 hour')" if hours is not None else ""
    sql = """
        WITH picks AS (
          SELECT i.id
          FROM items i
          JOIN sources s ON s.id = i.source_id
          WHERE i.format = 'article'::item_format
            AND s.weight >= :wmin
            AND s.active
            AND COALESCE(NULLIF(i.transcript, ''), NULLIF(i.description, '')) IS NOT NULL
            AND length(COALESCE(NULLIF(i.transcript, ''), NULLIF(i.description, ''))) >= 200
            AND (i.summary IS NULL OR i.summary = '')
            AND i.processing_status NOT IN
                ('summarize_queued'::processing_status, 'summarizing'::processing_status,
                 'queued'::processing_status, 'transcribing'::processing_status)
            """ + where_age + """
          ORDER BY s.weight DESC, i.published_at DESC
          LIMIT :lim
        )
        UPDATE items SET
          processing_status = 'summarize_queued'::processing_status,
          queued_at = now(),
          processing_error = NULL
        WHERE id IN (SELECT id FROM picks)
        RETURNING id::text
    """
    params: dict = {"wmin": weight_min, "lim": effective_limit}
    if hours is not None:
        params["hrs"] = hours
    r = await session.exec(sa_text(sql).bindparams(**params))
    ids = [row[0] for row in r.all()]
    await session.commit()
    return ids


async def _cron_kick_topic_digests(app, session, *, model: DigestModel = "opus",
                                   window: str = "daily",
                                   min_age_hours: Optional[float] = None) -> int:
    """For every topic, mark its digest as is_generating and kick a bg task.

    Note: generation_started_at wordt pas gezet wanneer de task daadwerkelijk
    begint (binnen de semaphore), niet hier. Dit voorkomt false-positive stale
    detectie wanneer veel topics in de wachtrij staan.

    min_age_hours: sla een topic over als z'n digest recenter dan dit is. Zo
    draait de weekdigest ~wekelijks ondanks de dagelijkse cron (zelfherstellend)."""
    from datetime import datetime

    window_hours = DIGEST_WINDOWS[window]
    rows = (await session.exec(sa_text(
        "SELECT id::text, slug, name FROM topics ORDER BY sort_order, name"
    ))).all()
    started = 0
    for tid, slug, name in rows:
        existing = (await session.exec(sa_text(
            "SELECT is_generating, generation_started_at, generated_at FROM topic_digests "
            "WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w"
        ).bindparams(tid=tid, w=window_hours))).first()
        # Skip als er al een digest bezig is of in de wachtrij staat:
        # - is_generating=true EN generation_started_at=NULL → in wachtrij, skip
        # - is_generating=true EN generation_started_at < 30 min geleden → actief bezig, skip
        # - is_generating=true EN generation_started_at > 30 min geleden → echte stale, mag opnieuw
        if existing and existing[0]:
            started_at = existing[1]
            if started_at is None:
                continue  # In wachtrij, andere worker pakt 'm
            if (datetime.now(started_at.tzinfo) - started_at).total_seconds() < DIGEST_GENERATION_STALE_MIN * 60:
                continue  # Actief bezig
        # Nog vers genoeg? Sla over (gebruikt voor de ~wekelijkse weekdigest).
        elif existing and min_age_hours is not None and existing[2] is not None:
            age_s = (datetime.now(existing[2].tzinfo) - existing[2]).total_seconds()
            if age_s < min_age_hours * 3600:
                continue
        if existing:
            # is_generating=true zetten, maar generation_started_at pas in de worker
            await session.exec(sa_text(
                "UPDATE topic_digests SET is_generating=true, generation_started_at=NULL, "
                "queued_at=now(), error=NULL "
                "WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w"
            ).bindparams(tid=tid, w=window_hours))
        else:
            # Insert zonder generation_started_at - die komt pas in de worker
            await session.exec(sa_text(
                "INSERT INTO topic_digests (topic_id, window_hours, is_generating, generation_started_at, queued_at) "
                "VALUES (CAST(:tid AS uuid), :w, true, NULL, now())"
            ).bindparams(tid=tid, w=window_hours))
        await session.commit()
        asyncio.create_task(run_digest_generation_bg(app, tid, name, slug, model, window_hours))
        started += 1
    return started


# Run-lock: voorkomt dat overlappende cron-aanroepen (de uurlijkse light-pas, de
# nachtelijke full, en handmatige triggers) tegelijk dezelfde refresh-loop draaien
# en de gedeelde httpx-pool leegtrekken — de contentie-spiraal die de transcribe-
# stap deed verhongeren. Eén actieve run tegelijk; een tweede aanroep no-opt direct.
# Single uvicorn-proces, dus een module-flag volstaat: er zit geen await tussen de
# check en de set, dus het is race-vrij in asyncio (geen DB-advisory-lock nodig).
_nightly_running = False


@router.post("/admin/cron/nightly")
async def admin_cron_nightly(request: Request = None,
                             light: bool = Query(False),
                             digests: bool = Query(True),
                             session=Depends(get_async_session)):
    """Nightly job: reset stuck → refresh sources → queue items.

    `light=true` (daytime-pas): alleen feeds verversen + artikelen samenvatten
    (cloud-vriendelijk). Slaat transcriptie (GPU/lokaal) én digests over — die
    blijven nachtwerk. Bedoeld om overdag uurlijks te draaien zodat summaries
    niet tot de volgende ochtend wachten, zonder de A2-GPU overdag te belasten.

    `digests=false`: wél transcripties queueen (full queue-vulling) maar de
    dag/week-digests overslaan — voor een hourly test-cron die de pipeline vaak
    draait zonder elke keer nieuwe digests te genereren. Digests lopen dan via
    een aparte dagelijkse full-run (zonder dit flag).

    Cron flipt alleen statussen naar *_queued. De worker pool draineert
    de queues vanzelf (bounded door SUMMARIZE_WORKERS + hard cap op
    queue-depth). Geen background-task spawn meer hier.

    Twee watchdogs beschermen tegen een hang-request:
    - Per-bron asyncio.wait_for(90s): één langzame feed kan niet de hele loop
      gijzelen. Bij timeout: rollback + refresh_errors++ + doorgaan.
    - Globale asyncio.wait_for(1800s): harde bovengrens voor de hele run. Bij
      timeout returnen we een JSON-error en laat de AsyncSession contextmanager
      een rollback doen — geen open transactie, geen pool-lek.

    Auth: internal token or admin session cookie.
    """
    global _nightly_running
    if _nightly_running:
        # Er draait al een run; niet nóg een concurrente refresh-loop starten.
        log.info("[cron] nightly al bezig — aanroep overgeslagen (light=%s, digests=%s)",
                 light, digests)
        return {"ok": False, "skipped": "already_running", "light": light, "digests": digests}
    _nightly_running = True

    http_client = request.app.state.http_client if request else None
    app = request.app if request else None

    async def _run() -> dict:
        unstuck = await _cron_unstuck(session)

        # Refresh sources
        rows = (await session.exec(sa_text(
            "SELECT id, name, kind::text, url FROM sources WHERE active ORDER BY name"
        ))).all()
        refreshed = 0
        refresh_errors = 0
        inserted_total = 0
        for row in rows:
            src = type("S", (), {"id": row[0], "name": row[1], "kind": row[2], "url": row[3]})
            try:
                res = await asyncio.wait_for(refresh_one(http_client, session, src), timeout=90.0)
                await session.commit()
                refreshed += 1
                inserted_total += res.get("inserted", 0)
                if "error" in res:
                    refresh_errors += 1
            except asyncio.TimeoutError:
                await session.rollback()
                refresh_errors += 1
                log.warning("[cron] refresh %s timeout na 90s — overgeslagen", row[1])
            except Exception as exc:
                await session.rollback()
                refresh_errors += 1
                log.warning("[cron] refresh %s faalde: %s", row[1], exc)

        article_ids = await _cron_pick_articles_for_summary(session, hours=CRON_NIGHTLY_HOURS)

        if light:
            # Daytime-pas: GEEN transcriptie (GPU/lokaal) en GEEN digests — nachtwerk.
            podcasts_queued = videos_queued = digests_started = weekly_started = 0
        else:
            podcasts_queued = await _cron_queue_transcribes(session, content_kind="podcast", hours=CRON_NIGHTLY_HOURS)
            videos_queued = await _cron_queue_transcribes(session, content_kind="youtube", hours=CRON_NIGHTLY_HOURS)

            if digests:
                from routers.settings import _load as _load_settings
                _settings = await _load_settings(session)
                digests_started = await _cron_kick_topic_digests(app, session, model=_settings.digest, window="daily")
                # Weekdigest hoeft maar ~wekelijks: alleen (re)genereren als de bestaande
                # ouder is dan WEEKLY_MIN_AGE_HOURS. Componeert uit de dag-digests (goedkoop),
                # dus dit kan veilig elke nacht meeliften zonder de oude 19u-hang.
                weekly_model = _settings.digest_weekly or _settings.digest
                weekly_started = await _cron_kick_topic_digests(
                    app, session, model=weekly_model, window="weekly", min_age_hours=WEEKLY_MIN_AGE_HOURS,
                )
            else:
                # digests=false: queue wel, digests niet (hourly test-cron).
                digests_started = weekly_started = 0

        return {
            "ok": True,
            "light": light,
            "stuck_reset": unstuck,
            "sources_refreshed": refreshed,
            "refresh_errors": refresh_errors,
            "new_items_inserted": inserted_total,
            "podcasts_queued": podcasts_queued,
            "videos_queued": videos_queued,
            "articles_summarize_kicked": len(article_ids),
            "digests_started": digests_started,
            "weekly_started": weekly_started,
        }

    try:
        return await asyncio.wait_for(_run(), timeout=1800.0)
    except asyncio.TimeoutError:
        # Harde watchdog. _run is geannuleerd; AsyncSession __aexit__ zal
        # een rollback doen zodat er geen open transactie achterblijft en
        # de connectie terugkeert in de pool.
        try:
            await session.rollback()
        except Exception:
            pass
        log.warning("[cron] nightly timeout na 1800s — afgekapt")
        return {
            "ok": False,
            "error": "timeout: nightly exceeded 1800 seconds",
        }
    finally:
        _nightly_running = False


@router.post("/admin/cron/transcribe-podcasts")
async def admin_cron_transcribe_podcasts(hours: int = Query(CRON_NIGHTLY_HOURS, ge=1, le=720),
                                         session=Depends(get_async_session)):
    await _cron_unstuck(session)
    n = await _cron_queue_transcribes(session, content_kind="podcast", hours=hours)
    return {"ok": True, "queued": n, "hours": hours}


@router.post("/admin/cron/transcribe-videos")
async def admin_cron_transcribe_videos(hours: int = Query(CRON_NIGHTLY_HOURS, ge=1, le=720),
                                       session=Depends(get_async_session)):
    await _cron_unstuck(session)
    n = await _cron_queue_transcribes(session, content_kind="youtube", hours=hours)
    return {"ok": True, "queued": n, "hours": hours}


@router.post("/admin/cron/summarize-articles")
async def admin_cron_summarize_articles(hours: int = Query(CRON_NIGHTLY_HOURS, ge=1, le=720),
                                        session=Depends(get_async_session)):
    await _cron_unstuck(session)
    article_ids = await _cron_pick_articles_for_summary(session, hours=hours)
    return {"ok": True, "articles_kicked": len(article_ids), "hours": hours}


@router.post("/admin/cron/digest-topics")
async def admin_cron_digest_topics(request: Request,
                                   window: DigestWindow = Query("daily"),
                                   model: DigestModel = Query("opus"),
                                   session=Depends(get_async_session)):
    started = await _cron_kick_topic_digests(request.app, session, model=model, window=window)
    return {"ok": True, "digests_started": started, "window": window, "model": model}


@router.get("/admin/cron/digest-status")
async def admin_cron_digest_status(window: DigestWindow = Query("daily"),
                                   session=Depends(get_async_session)):
    """Snel overzicht hoeveel digests in_progress zijn — voor de UI om voortgang te tonen."""
    w = DIGEST_WINDOWS[window]
    r = (await session.execute(sa_text("""
        SELECT
          COUNT(*) FILTER (WHERE is_generating) AS in_progress,
          COUNT(*) FILTER (WHERE NOT is_generating AND markdown IS NOT NULL AND markdown <> '') AS done,
          COUNT(*) FILTER (WHERE NOT is_generating AND error IS NOT NULL) AS failed
        FROM topic_digests WHERE window_hours = :w
    """), {"w": w})).first()
    return {"window": window, "in_progress": r[0], "done": r[1], "failed": r[2]}


@router.get("/admin/cron/last-result")
async def admin_cron_last_result(session=Depends(get_async_session)):
    """Monitoring-snapshot van de cron/feed-poll gezondheid.

    Geeft per actieve bron de leeftijd van de laatste poll, aggregaten
    (hoeveel bronnen ouder dan 24 uur, oudste poll ooit), en de huidige
    DB-pool-staat (idle / idle-in-transaction / active). Bedoeld voor
    Netdata of een andere externe monitor: simpele drempel op
    `oldest_last_polled_seconds > 90000` page't je als cron >25 uur
    niet heeft gedraaid. Auth: internal token (zelfde als andere
    /admin/cron/* endpoints — bewust zonder user-cookie zodat externe
    monitors met één token kunnen pollen).
    """
    from datetime import datetime, timezone
    rows = (await session.exec(sa_text("""
        SELECT name, kind::text, last_polled_at, last_poll_status,
               EXTRACT(EPOCH FROM (now() - last_polled_at))::int AS age_sec
        FROM sources
        WHERE active
        ORDER BY last_polled_at NULLS FIRST
    """))).all()
    sources = [
        {
            "name": r[0],
            "kind": r[1],
            "last_polled_at": r[2].isoformat() if r[2] else None,
            "last_poll_status": r[3],
            "age_seconds": r[4],
        }
        for r in rows
    ]

    over_24h = sum(1 for s in sources
                   if s["age_seconds"] is None or s["age_seconds"] > 24 * 3600)
    oldest = max((s["age_seconds"] for s in sources if s["age_seconds"] is not None),
                 default=None)

    # DB-pool-staat. Zelfde SQL als _cron_unstuck gebruikt voor de cleanup,
    # maar nu read-only. Handig om te zien of er weer zombies opbouwen.
    pool_rows = (await session.exec(sa_text("""
        SELECT state, count(*)::int FROM pg_stat_activity
        WHERE datname = current_database()
        GROUP BY state
    """))).all()
    pool = {state: count for state, count in pool_rows}

    # Items per processing-status, om te zien of de queue leeg-loopt
    proc_rows = (await session.exec(sa_text("""
        SELECT processing_status::text, count(*)::int FROM items
        GROUP BY processing_status
    """))).all()
    processing = {status: count for status, count in proc_rows}

    return {
        "ok": True,
        "now": datetime.now(timezone.utc).isoformat(),
        "sources_total": len(sources),
        "sources_over_24h": over_24h,
        "oldest_last_polled_seconds": oldest,
        "pool": pool,
        "processing": processing,
        "sources": sources,
    }


@router.delete("/admin/queue/{item_id}")
async def admin_queue_remove(item_id: str, session=Depends(get_async_session),
                             user=Depends(require_user)):
    """Haal een item uit de queue: reset processing_status naar 'ready'."""
    r = await session.exec(sa_text(
        "UPDATE items SET processing_status='ready'::processing_status, queued_at=NULL, "
        "processing_error='handmatig uit queue gehaald' "
        "WHERE id = CAST(:i AS uuid) "
        "AND processing_status IN ('queued'::processing_status, 'transcribe_queued'::processing_status, "
        "'summarize_queued'::processing_status, 'transcribing'::processing_status, 'summarizing'::processing_status) "
        "RETURNING id"
    ).bindparams(i=item_id))
    found = bool(r.first())
    await session.commit()
    if not found:
        raise HTTPException(status_code=404, detail="Item niet in queue")
    return {"ok": True, "id": item_id}


@router.post("/admin/queue/restart")
async def admin_queue_restart(session=Depends(get_async_session), user=Depends(require_user)):
    """Onstuck-pas. Workers pakken vanzelf de volgende items op."""
    unstuck = await _cron_unstuck(session)
    return {"ok": True, "stuck_reset": unstuck}


@router.get("/admin/queue", response_model=list[QueueItem])
async def admin_queue(session=Depends(get_async_session),
                      user=Depends(require_user)):
    r = await session.exec(sa_text(
        """
        SELECT i.id::text, i.title, s.name, i.format::text,
               i.processing_status::text, i.queued_at
        FROM items i
        JOIN sources s ON s.id = i.source_id
        WHERE i.processing_status IN (
            'transcribe_queued', 'transcribing',
            'summarize_queued', 'summarizing'
        )
        ORDER BY
          CASE i.processing_status::text
            WHEN 'transcribing' THEN 1
            WHEN 'summarizing' THEN 2
            WHEN 'transcribe_queued' THEN 3
            WHEN 'summarize_queued' THEN 4
            ELSE 5
          END,
          i.queued_at ASC NULLS LAST
        """
    ))
    rows = r.all()
    out = []
    pos = 0
    for row in rows:
        if row[4] in ("transcribe_queued", "summarize_queued"):
            pos += 1
        out.append(QueueItem(
            id=row[0], title=row[1], source_name=row[2], format=row[3],
            processing_status=row[4],
            queued_at=str(row[5]) if row[5] else None,
            queue_position=pos if row[4] == "queued" else None,
        ))
    return out
