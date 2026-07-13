"""Transcribe-queue: single worker (single GPU), dispatcht naar samenvat-agent."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx
from sqlalchemy import text as sa_text

from core.config import settings
from core.memory import mem_gate_blocks
from workers import monitor

log = logging.getLogger("stroom.worker.transcribe")

# Transient DNS/connect-fouten naar samenvat-agent moeten niet meteen 'failed'
# opleveren — Docker's embedded DNS resolver kan kort flappen bij churn op
# personal_net. Requeue tot N pogingen voordat we echt opgeven.
_TRIGGER_ATTEMPTS: dict[str, int] = {}


async def claim_next_transcribe(session) -> Optional[tuple[str, str, str]]:
    """Atomair één transcribe_queued item claimen — single GPU.

    Geeft (item_id, media_url, type) of None.
    Caller is verantwoordelijk voor het posten naar de transcribe-agent.

    Mem-gate: weigert te claimen als host-RAM onder TRANSCRIBE_MIN_FREE_MB
    zit. Whisper-medium piekt op ~1.6GB host-RAM (model + alignment + audio
    buffer) ook al draait inference op GPU.
    """
    if mem_gate_blocks('trans-worker', settings.TRANSCRIBE_MIN_FREE_MB):
        return None
    # Eerst checken of de GPU al bezet is (slechts 1 transcribing tegelijk).
    r = await session.exec(sa_text(
        "SELECT COUNT(*) FROM items WHERE processing_status='transcribing'::processing_status"
    ))
    if r.first()[0] >= 1:
        return None
    r = await session.exec(sa_text("""
        UPDATE items SET
          processing_status = 'transcribing'::processing_status,
          processing_error = NULL
        WHERE id = (
            SELECT id FROM items
            WHERE processing_status = 'transcribe_queued'::processing_status
            ORDER BY queued_at ASC NULLS LAST
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id::text, media_url, type::text
    """))
    row = r.first()
    await session.commit()
    if not row:
        return None
    return (row[0], row[1], row[2])


async def transcribe_worker(async_session_maker) -> None:
    """Single worker voor de transcribe-queue (single GPU).

    Gebruikt een eigen httpx-client (niet `app.state.http_client`) zodat een
    eventueel kapotte connection-pool of DNS-cache-staat in de gedeelde
    client geen invloed heeft op deze hot path. Een DNS-flap op personal_net
    leek de gedeelde pool in een permanent fail-state te dwingen.
    """
    log.info("[trans-worker] started")
    client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_connections=2))
    while True:
        try:
            monitor.beat("trans-worker")
            async with async_session_maker() as s:
                claim = await claim_next_transcribe(s)
            if not claim:
                await asyncio.sleep(settings.WORKER_IDLE_POLL_SEC)
                continue
            item_id, media_url, item_type = claim
            try:
                source_type = "podcast" if item_type == "podcast" else "general"
                r = await client.post(
                    f"{settings.TRANSCRIBE_AGENT_URL.rstrip('/')}/process",
                    json={"url": media_url, "source_type": source_type,
                          "model_name": "medium", "stroom_item_id": item_id},
                    timeout=10.0,
                )
                if r.status_code >= 400:
                    raise RuntimeError(f"transcribe-agent {r.status_code}: {r.text[:200]}")
                _TRIGGER_ATTEMPTS.pop(item_id, None)
            except Exception as exc:
                transient = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
                attempts = _TRIGGER_ATTEMPTS.get(item_id, 0) + 1
                if transient and attempts < settings.TRANSCRIBE_TRIGGER_MAX_TRIES:
                    _TRIGGER_ATTEMPTS[item_id] = attempts
                    async with async_session_maker() as bg:
                        await bg.exec(sa_text(
                            "UPDATE items SET processing_status='transcribe_queued'::processing_status, "
                            "processing_error=NULL WHERE id = CAST(:i AS uuid)"
                        ).bindparams(i=item_id))
                        await bg.commit()
                    log.warning("[trans-worker] transient trigger fail voor %s "
                                "(poging %d/%d): %s — requeued",
                                item_id, attempts, settings.TRANSCRIBE_TRIGGER_MAX_TRIES, exc)
                    await asyncio.sleep(5)
                else:
                    _TRIGGER_ATTEMPTS.pop(item_id, None)
                    async with async_session_maker() as bg:
                        await bg.exec(sa_text(
                            "UPDATE items SET processing_status='failed'::processing_status, "
                            "processing_error=:e WHERE id = CAST(:i AS uuid)"
                        ).bindparams(e=f"transcribe trigger failed: {exc}"[:500], i=item_id))
                        await bg.commit()
                    log.warning("[trans-worker] kon transcribe niet starten voor %s: %s",
                                item_id, exc)
        except asyncio.CancelledError:
            log.info("[trans-worker] shutting down")
            return
        except Exception as exc:
            log.warning("[trans-worker] error: %s", exc)
            await asyncio.sleep(5)
