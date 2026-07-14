"""Worker-liveness heartbeats + queue-depth logging (verbeterplan R5).

Elke worker-loop-iteratie (óók wanneer de mem-gate het claimen blokkeert)
roept beat(naam) aan. De cron-watchdog gebruikt workers_alive() om
'getemperd' (workers leven, RAM krap → niks geclaimd) te onderscheiden van
'stalled' (workers echt dood). Zonder dit faalt de watchdog een hele wachtrij
die enkel op geheugen staat te wachten — de bron van de "queue stalled"-golven.

Per-worker (voorheen één globale float): één levende summarize-worker kan een
vastgelopen transcribe-worker niet meer maskeren.
"""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import text as sa_text

log = logging.getLogger("stroom.worker.monitor")

QUEUE_DEPTH_LOG_EVERY_SEC = 60

_heartbeats: dict[str, float] = {}


def beat(worker: str) -> None:
    _heartbeats[worker] = time.time()


def stalled(max_age_sec: float) -> list[str]:
    """Namen van geregistreerde workers zonder heartbeat binnen max_age_sec."""
    now = time.time()
    return [name for name, ts in _heartbeats.items() if now - ts > max_age_sec]


def workers_alive(max_age_sec: float) -> bool:
    """True zolang ÁLLE geregistreerde workers recent een heartbeat gaven.

    Conservatief: één dode worker → False, zodat de cron-watchdog de
    queue-stall-check draait. Geen registraties (net geboot) → False.
    """
    if not _heartbeats:
        return False
    return not stalled(max_age_sec)


def newest_beat_age() -> float:
    """Seconden sinds de meest recente heartbeat (inf zonder registraties)."""
    if not _heartbeats:
        return float("inf")
    return time.time() - max(_heartbeats.values())


async def queue_depth_logger(async_session_maker) -> None:
    """Logt elke ~60s queue-diepte. Hiermee zie je vastlopers vroeg."""
    while True:
        try:
            await asyncio.sleep(QUEUE_DEPTH_LOG_EVERY_SEC)
            async with async_session_maker() as s:
                r = await s.exec(sa_text("""
                    SELECT processing_status::text, COUNT(*) FROM items
                    WHERE processing_status IN (
                        'transcribe_queued','transcribing',
                        'summarize_queued','summarizing'
                    )
                    GROUP BY processing_status
                """))
                depth = {row[0]: row[1] for row in r.all()}
            if depth:
                log.info("queue-depth %s", depth)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            log.warning("queue-depth error: %s", exc)
