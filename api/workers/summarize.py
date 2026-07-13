"""Summarize-queue: routing, retry, worker-loop.

`settings.SUMMARIZE_WORKERS` instances draaien parallel. Concurrency op LLM
is daarmee per definitie begrensd op N. Geen losse `create_task` per item —
als de pool vol zit, wacht de queue gewoon.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy import text as sa_text

from core.config import settings
from core.memory import mem_gate_blocks
from pipeline.feeds import INBOX_SOURCE_NAME
from services.lessons import ARTICLE_MIN_BODY_FOR_LESSONS, distill_lessons_for_item
from services.llm_service import LLMService
from services.scoring import score_with_quality_scorer
from workers import monitor

log = logging.getLogger("stroom.worker.summarize")

SHORT_SUMMARY_SYSTEM = (
    "Je bent een curator van hoogwaardige content. Vat het artikel samen in het "
    "Nederlands, zakelijk maar warm, max 3 zinnen.\n\n"
    "Lever alleen de samenvatting, geen extra uitleg of JSON."
)

LONG_SUMMARY_SYSTEM = (
    "Je bent een curator van hoogwaardige content. Vat onderstaande lange transcriptie "
    "gestructureerd samen in het Nederlands, zakelijk maar warm. Lever platte tekst "
    "(geen JSON, geen markdown-fences) in deze vorm:\n"
    "- 1 zin met het hoofdonderwerp\n"
    "- 3-5 bullets met de belangrijkste subonderwerpen (1 zin per bullet)\n"
    "- 1 zin met een conclusie of inzicht"
)

ARTICLE_SUMMARY_SYSTEM = (
    "Je bent een curator van hoogwaardige content. Vat dit artikel inhoudelijk samen "
    "in het Nederlands, zakelijk maar warm. Lever platte tekst (geen JSON, geen "
    "markdown-fences) in deze vorm:\n"
    "- 1 zin met de kern van het artikel\n"
    "- 2-5 bullets met de belangrijkste punten, argumenten of voorbeelden (1 zin per bullet)\n"
    "- 1 zin met de conclusie of het inzicht dat blijft hangen\n\n"
    "Pas het aantal bullets aan op de rijkdom van het artikel; liever 2 rake bullets "
    "dan 5 opgerekte."
)


def pick_summary_route(raw: str, duration_seconds: int | None,
                       is_article: bool = False) -> dict:
    """Kies model + trim + prompt op basis van content-type en lengte.

    Tekstartikelen (type='rss') krijgen een eigen gestructureerde prompt los van
    de transcript-routing; voor lange artikelen (>20k chars) gaat het naar het
    cloud-model met groot context-window.

    Transcripties (podcast/video): lange transcripties (> 10 min, of >20k chars
    als duration onbekend) gaan naar een cloud-model met groot context-window
    i.p.v. de lokale 12k-trim. Geeft betere samenvattingen voor 3-uur Acquired e.d.
    """
    if is_article:
        is_long = len(raw) >= settings.LONG_TRANSCRIPT_CHAR_FALLBACK
        return {
            "model": settings.LONG_TRANSCRIPT_MODEL if is_long else "stroom-bulk",
            "cleaned": re.sub(r"\s+", " ", raw).strip()[
                :(settings.LONG_TRANSCRIPT_MAX_CHARS if is_long else 12000)],
            "system_prompt": ARTICLE_SUMMARY_SYSTEM,
            "timeout": settings.LONG_TRANSCRIPT_TIMEOUT_SEC if is_long else 180.0,
            "is_long": is_long,
        }
    duration = duration_seconds or 0
    is_long = (duration >= settings.LONG_TRANSCRIPT_DURATION_SECONDS
               or len(raw) >= settings.LONG_TRANSCRIPT_CHAR_FALLBACK)
    if is_long:
        return {
            "model": settings.LONG_TRANSCRIPT_MODEL,
            "cleaned": re.sub(r"\s+", " ", raw).strip()[:settings.LONG_TRANSCRIPT_MAX_CHARS],
            "system_prompt": LONG_SUMMARY_SYSTEM,
            "timeout": settings.LONG_TRANSCRIPT_TIMEOUT_SEC,
            "is_long": True,
        }
    return {
        "model": "stroom-bulk",
        "cleaned": re.sub(r"\s+", " ", raw).strip()[:12000],
        "system_prompt": SHORT_SUMMARY_SYSTEM,
        "timeout": 180.0,
        "is_long": False,
    }


async def summarize_with_retry(llm_service, model: str, messages: list, *,
                               temperature: float, timeout: float,
                               attempts: int = settings.SUMMARIZE_MAX_ATTEMPTS) -> str:
    """`call_llm` met retry+backoff op transiente fouten.

    Transient = HTTP 429 / 5xx (incl. de 502 die `call_llm` gooit bij lege
    content) en netwerk-/timeout-fouten. Niet-transiente 4xx (bv. 400 bad
    request) bubbelen direct, want die lossen niet op met opnieuw proberen.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await llm_service.call_llm(
                model, messages, temperature=temperature, timeout=timeout)
        except HTTPException as exc:
            transient = exc.status_code == 429 or exc.status_code >= 500
            if not transient or attempt == attempts:
                raise
            last_exc = exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == attempts:
                raise
            last_exc = exc
        backoff = min(settings.SUMMARIZE_RETRY_BASE_SEC * (2 ** (attempt - 1)), 30.0)
        log.info("[sum-retry] %s poging %d/%d faalde (%s); retry over %.0fs",
                 model, attempt, attempts, last_exc, backoff)
        await asyncio.sleep(backoff)
    # Onbereikbaar (laatste poging raise't al), maar voor de typechecker:
    raise last_exc if last_exc else RuntimeError("summarize-retry zonder resultaat")


async def claim_next_summarize(session) -> Optional[str]:
    """Atomair één summarize_queued item claimen.

    Gebruikt FOR UPDATE SKIP LOCKED zodat meerdere workers nooit hetzelfde
    item pakken en geen worker geblokkeerd raakt op een rij die een ander
    al heeft gepakt. Returnt het id::text of None als de queue leeg is.

    Mem-gate: weigert te claimen als host-RAM onder SUMMARIZE_MIN_FREE_MB
    zit. Worker valt dan terug op de idle-poll-sleep en probeert later weer.
    """
    if mem_gate_blocks('sum-worker', settings.SUMMARIZE_MIN_FREE_MB):
        return None
    r = await session.exec(sa_text("""
        UPDATE items SET
          processing_status = 'summarizing'::processing_status,
          processing_error = NULL
        WHERE id = (
            SELECT id FROM items
            WHERE processing_status = 'summarize_queued'::processing_status
            ORDER BY queued_at ASC NULLS LAST
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id::text
    """))
    row = r.first()
    await session.commit()
    return row[0] if row else None


async def summarize_single_item(app: FastAPI, item_id: str, llm_service,
                                async_session_maker, *, score: bool = True) -> bool:
    """Summarize a single item (article/podcast/video with transcript).

    Voor items uit de Inbox-bron wordt na summarize ook lesson-distill
    gedraaid (binnen dezelfde worker — telt mee voor concurrency-budget).
    `score=False` slaat de quality-scoring over.
    """
    try:
        async with async_session_maker() as bg:
            r = await bg.exec(sa_text("""
                SELECT i.title, i.transcript, i.description, i.type::text, s.name,
                       i.duration_seconds
                FROM items i JOIN sources s ON s.id = i.source_id
                WHERE i.id = CAST(:i AS uuid)
            """).bindparams(i=item_id))
            row = r.first()
            if not row:
                return False
            title = row[0]
            raw = (row[1] or "").strip() or re.sub(r"<[^>]+>", " ", row[2] or "").strip()
            article_body = (row[1] or "").strip()
            kind = row[3]
            source_name = row[4]
            duration_seconds = row[5]
            is_article = kind == "rss"
            if not raw:
                await bg.exec(sa_text(
                    "UPDATE items SET processing_status='ready'::processing_status, queued_at=NULL "
                    "WHERE id = CAST(:i AS uuid)"
                ).bindparams(i=item_id))
                await bg.commit()
                return True

        route = pick_summary_route(raw, duration_seconds, is_article=is_article)
        actual_model = route["model"]
        fallback_summary_prompt = ARTICLE_SUMMARY_SYSTEM if is_article else SHORT_SUMMARY_SYSTEM
        try:
            response = await summarize_with_retry(llm_service, route["model"], [
                {"role": "system", "content": route["system_prompt"]},
                {"role": "user", "content": f"Titel: {title}\n\nTekst: {route['cleaned']}"},
            ], temperature=0.3, timeout=route["timeout"])
        except Exception as exc:
            if not route["is_long"]:
                raise
            log.warning("long-context model %s faalde voor %s: %s — "
                        "fallback naar stroom-bulk truncated", route["model"], item_id, exc)
            fallback_cleaned = re.sub(r"\s+", " ", raw).strip()[:12000]
            response = await summarize_with_retry(llm_service, "stroom-bulk", [
                {"role": "system", "content": fallback_summary_prompt},
                {"role": "user", "content": f"Titel: {title}\n\nTekst: {fallback_cleaned}"},
            ], temperature=0.3, timeout=180.0)
            actual_model = f"{route['model']}-fallback-bulk"

        summary = response.strip() if response else ""

        # Get quality score from dedicated service (fail open)
        quality_score = None
        if score and summary:
            quality_score = await score_with_quality_scorer(app, summary, title)
            if quality_score:
                log.info("scored %s: %s/10", item_id, quality_score)

        async with async_session_maker() as bg:
            await bg.exec(sa_text(
                "UPDATE items SET summary=:s, summary_model=:m, "
                "summary_generated_at=now(), processing_status='ready'::processing_status, "
                "quality_score=:q, quality_score_reason='auto', quality_score_updated_at=now(), "
                "queued_at=NULL WHERE id = CAST(:i AS uuid)"
            ).bindparams(s=summary, m=actual_model, i=item_id, q=quality_score))
            await bg.commit()

        # Lesson-distill voor tekstartikelen (en handmatige Inbox-items), mits de
        # full-text echt geëxtraheerd is — niet alleen een RSS-teaser, anders
        # krijg je oppervlakkige/verzonnen lessen. distill_lessons_for_item slaat
        # zelf over als het item al lessen heeft (idempotent bij retry).
        # Best-effort: faalt distill, dan blijft summary nog steeds geldig.
        if ((is_article or source_name == INBOX_SOURCE_NAME)
                and len(article_body) >= ARTICLE_MIN_BODY_FOR_LESSONS):
            try:
                await distill_lessons_for_item(item_id, summary, article_body,
                                               llm_service, async_session_maker)
            except Exception as exc:
                log.warning("distill faalde voor %s: %s", item_id, exc)

        return True
    except Exception as exc:
        try:
            async with async_session_maker() as bg:
                await bg.exec(sa_text(
                    "UPDATE items SET processing_status='failed'::processing_status, "
                    "processing_error=:e, queued_at=NULL WHERE id = CAST(:i AS uuid)"
                ).bindparams(e=f"summarize: {exc}"[:500], i=item_id))
                await bg.commit()
        except Exception:
            pass
        return False


async def summarize_worker(app: FastAPI, idx: int, async_session_maker) -> None:
    """Continu draaiende worker: claim → process → repeat."""
    name = f"sum-worker-{idx}"
    log.info("[%s] started", name)
    llm = LLMService(app.state.llm_client)
    while True:
        try:
            monitor.beat(name)
            async with async_session_maker() as s:
                item_id = await claim_next_summarize(s)
            if not item_id:
                await asyncio.sleep(settings.WORKER_IDLE_POLL_SEC)
                continue
            await summarize_single_item(app, item_id, llm, async_session_maker)
        except asyncio.CancelledError:
            log.info("[%s] shutting down", name)
            return
        except Exception as exc:
            log.warning("[%s] error: %s", name, exc)
            await asyncio.sleep(5)
