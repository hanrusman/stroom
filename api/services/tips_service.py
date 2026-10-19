"""Tips-job: aanbevelingen uit transcripten extraheren, verifiëren en opslaan."""

import asyncio
import json
import os
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy import text as sa_text

from services.llm_service import parse_llm_json
from services.tips_prompts import EXTRACT_SYSTEM, VERIFY_SYSTEM
from services.tips_helpers import (
    CATEGORIES,
    WEIGHT,
    clean_tips,
    parse_tips,
    parse_verify,
    title_key,
    windows,
)
from services.tips_aggregate import aggregate, query_works

__all__ = [
    "CATEGORIES",
    "WEIGHT",
    "aggregate",
    "clean_tips",
    "last_result",
    "load_mentions",
    "load_works",
    "parse_tips",
    "parse_verify",
    "pick_items",
    "query_works",
    "run_tips_job",
    "scan_item",
    "spawn_tips_job",
    "title_key",
    "verify_new_works",
    "windows",
]

MAX_CONCURRENCY = 2
EXTRACT_TIMEOUT = 180.0
VERIFY_BATCH = 40
MIN_VERIFY_SCORE = 2

_sem = asyncio.Semaphore(MAX_CONCURRENCY)
_job_lock = asyncio.Lock()
_tasks: set[asyncio.Task] = set()
last_result: dict = {}

_UPSERT_SCAN_SQL = """
INSERT INTO tip_scans (item_id, status, windows, attempts, model, error, scanned_at)
VALUES (CAST(:i AS uuid), :status, :windows, 1, :model, :error, now())
ON CONFLICT (item_id) DO UPDATE SET
    status = EXCLUDED.status,
    windows = EXCLUDED.windows,
    attempts = tip_scans.attempts + 1,
    model = EXCLUDED.model,
    error = EXCLUDED.error,
    scanned_at = now()
"""

_INSERT_MENTION_SQL = """
INSERT INTO tip_mentions
    (item_id, window_offset, category, title, title_key, creator,
     recommended_by, strength, why, quote, model, created_at)
VALUES
    (CAST(:i AS uuid), :offset, :category, :title, :title_key, :creator,
     :recommended_by, :strength, :why, :quote, :model, now())
"""


def tips_model() -> str:
    """Modelnaam voor het extraheren van tips."""
    return os.environ.get("TIPS_MODEL", "cloud-gemma")


def verify_model() -> str:
    """Modelnaam voor het verifiëren van werken."""
    return os.environ.get("TIPS_VERIFY_MODEL", "cloud-mistral")


def max_items_default() -> int:
    """Standaardaantal items per jobrun."""
    return int(os.environ.get("TIPS_MAX_ITEMS", "40"))


async def _llm_json(
    llm,
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int,
    timeout: float,
) -> object:
    """LLM-aanroep met JSON-antwoord, met retries en concurrency-beperking."""
    json_retried = False
    last_exc: Exception | None = None
    for attempt in range(6):
        try:
            async with _sem:
                raw = await llm.call_llm(
                    model,
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.1,
                    response_format="json_object",
                    timeout=timeout,
                    max_tokens=max_tokens,
                )
            return parse_llm_json(raw)
        except json.JSONDecodeError as exc:
            if json_retried:
                raise
            json_retried = True
            last_exc = exc
            continue
        except HTTPException as exc:
            if exc.status_code == 429 or exc.status_code >= 500:
                last_exc = exc
            else:
                raise
        except httpx.HTTPError as exc:
            last_exc = exc
        if attempt < 5:
            await asyncio.sleep(min(60, 4 * 2 ** attempt))
    raise last_exc


async def load_mentions(session) -> list[dict]:
    """Alle tip-mentions met bron- en afleveringsgegevens."""
    stmt = sa_text(
        """
        SELECT m.item_id::text, m.title_key, m.category, m.title, m.creator,
               m.recommended_by, m.strength, m.why, m.quote,
               s.name, i.title, to_char(i.published_at, 'YYYY-MM-DD')
        FROM tip_mentions m
        JOIN items i ON i.id = m.item_id
        JOIN sources s ON s.id = i.source_id
        """
    )
    rows = (await session.exec(stmt)).all()
    return [
        {
            "item_id": row[0],
            "title_key": row[1],
            "category": row[2],
            "title": row[3],
            "creator": row[4],
            "recommended_by": row[5],
            "strength": row[6],
            "why": row[7],
            "quote": row[8],
            "source": row[9],
            "episode": row[10],
            "published": row[11],
        }
        for row in rows
    ]


async def load_works(session) -> dict[str, dict]:
    """Alle geverifieerde werken als dict per title_key."""
    stmt = sa_text(
        "SELECT title_key, keep, title, creator, category, confidence FROM tip_works"
    )
    rows = (await session.exec(stmt)).all()
    return {
        row[0]: {
            "keep": row[1],
            "title": row[2],
            "creator": row[3],
            "category": row[4],
            "confidence": row[5],
        }
        for row in rows
    }


async def pick_items(session, limit: int) -> list[str]:
    """Id's van items die (opnieuw) gescand moeten worden."""
    stmt = sa_text(
        """
        SELECT i.id::text FROM items i
        LEFT JOIN tip_scans t ON t.item_id = i.id
        WHERE i.type::text IN ('podcast', 'youtube')
          AND length(i.transcript) > 200
          AND (t.item_id IS NULL
               OR (t.status = 'failed' AND t.attempts < 3
                   AND t.scanned_at < now() - interval '24 hours'))
        ORDER BY i.published_at DESC NULLS LAST
        LIMIT :lim
        """
    ).bindparams(lim=limit)
    rows = (await session.exec(stmt)).all()
    return [row[0] for row in rows]


async def scan_item(session_maker, llm, item_id: str, model: str) -> dict:
    """Scan één item venster voor venster en sla de gevonden tips op."""
    async with session_maker() as s:
        row = (
            await s.exec(
                sa_text(
                    """
                    SELECT i.transcript, i.title, src.name
                    FROM items i
                    JOIN sources src ON src.id = i.source_id
                    WHERE i.id = CAST(:id AS uuid)
                    """
                ).bindparams(id=item_id)
            )
        ).first()
    if row is None:
        return {"item_id": item_id, "status": "missing", "windows": 0, "tips": 0}
    transcript, title, source = row
    wins = windows(transcript)

    async def extract(offset: int, chunk: str) -> list[dict]:
        user = f'Bron: {source} — "{title}"\n\nFragment:\n{chunk}'
        data = await _llm_json(
            llm, model, EXTRACT_SYSTEM, user, max_tokens=1500, timeout=EXTRACT_TIMEOUT
        )
        return clean_tips(data)

    results = await asyncio.gather(
        *(extract(offset, chunk) for offset, chunk in wins),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, Exception)]
    if errors:
        exc = errors[0]
        error = f"{type(exc).__name__}: {exc}"[:500]
        async with session_maker() as s:
            await s.exec(
                sa_text(_UPSERT_SCAN_SQL).bindparams(
                    i=item_id, status="failed", windows=len(wins), model=model, error=error
                )
            )
            await s.commit()
        print(f"[tips] scan mislukt voor {item_id}: {error}", flush=True)
        return {"item_id": item_id, "status": "failed", "windows": len(wins), "tips": 0}

    tips_total = 0
    async with session_maker() as s:
        await s.exec(
            sa_text(
                "DELETE FROM tip_mentions WHERE item_id = CAST(:i AS uuid)"
            ).bindparams(i=item_id)
        )
        for (offset, _chunk), tips in zip(wins, results):
            for tip in tips:
                await s.exec(
                    sa_text(_INSERT_MENTION_SQL).bindparams(
                        i=item_id,
                        offset=offset,
                        category=tip["category"],
                        title=tip["title"],
                        title_key=title_key(tip["title"]),
                        creator=tip["creator"],
                        recommended_by=tip["recommended_by"],
                        strength=tip["strength"],
                        why=tip["why"],
                        quote=tip["quote"],
                        model=model,
                    )
                )
                tips_total += 1
        await s.exec(
            sa_text(_UPSERT_SCAN_SQL).bindparams(
                i=item_id, status="done", windows=len(wins), model=model, error=None
            )
        )
        await s.commit()
    return {"item_id": item_id, "status": "done", "windows": len(wins), "tips": tips_total}


def _most_common(values: list[str]) -> str:
    """Meest voorkomende waarde; bij gelijke telling de eerstgeziene."""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return max(counts, key=counts.get)


async def verify_new_works(
    session_maker, llm, model: str, batch_size: int = VERIFY_BATCH
) -> int:
    """Verifieer nieuwe werken in batches en sla de oordelen op in tip_works."""
    async with session_maker() as s:
        rows = (
            await s.exec(
                sa_text(
                    """
                    WITH per_item AS (
                      SELECT m.title_key, m.item_id,
                             max(CASE m.strength WHEN 'strong' THEN 3
                                 WHEN 'medium' THEN 2 ELSE 1 END) AS w
                      FROM tip_mentions m
                      LEFT JOIN tip_works tw ON tw.title_key = m.title_key
                      WHERE tw.title_key IS NULL
                      GROUP BY m.title_key, m.item_id)
                    SELECT title_key FROM per_item
                    GROUP BY title_key
                    HAVING sum(w) >= :min_score
                    ORDER BY sum(w) DESC
                    """
                ).bindparams(min_score=MIN_VERIFY_SCORE)
            )
        ).all()
        keys = [row[0] for row in rows]
        if not keys:
            return 0
        mention_rows = (
            await s.exec(
                sa_text(
                    """
                    SELECT m.title_key, m.title, m.creator, m.category, m.quote, s.name
                    FROM tip_mentions m
                    JOIN items i ON i.id = m.item_id
                    JOIN sources s ON s.id = i.source_id
                    WHERE m.title_key = ANY(:keys)
                    """
                ).bindparams(keys=keys)
            )
        ).all()

    info: dict[str, dict[str, list[str]]] = {
        key: {"titles": [], "creators": [], "categories": [], "quotes": [], "shows": []}
        for key in keys
    }
    for key, title, creator, category, quote, show in mention_rows:
        entry = info[key]
        entry["titles"].append(title)
        entry["creators"].append(creator)
        entry["categories"].append(category)
        if quote and quote.strip():
            entry["quotes"].append(quote.strip()[:140])
        entry["shows"].append(show)

    total = 0
    for start in range(0, len(keys), batch_size):
        part = keys[start : start + batch_size]
        batch: list[dict] = []
        lines: list[str] = []
        for vid, key in enumerate(part):
            entry = info[key]
            item = {
                "vid": vid,
                "title_key": key,
                "title": _most_common(entry["titles"]),
                "creator": _most_common(entry["creators"]),
                "category": _most_common(entry["categories"]),
            }
            batch.append(item)
            lines.append(
                json.dumps(
                    {
                        "id": vid,
                        "category": item["category"],
                        "title": item["title"],
                        "creator": item["creator"],
                        "podcast": list(dict.fromkeys(entry["shows"]))[:3],
                        "quotes": " / ".join(entry["quotes"][:2]),
                    },
                    ensure_ascii=False,
                )
            )
        content = "\n".join(lines)
        try:
            data = await _llm_json(
                llm, model, VERIFY_SYSTEM, content, max_tokens=3000, timeout=300
            )
            verdicts = parse_verify(json.dumps(data), batch)
        except Exception as exc:
            print(
                f"[tips] verify-batch overgeslagen: {type(exc).__name__}: {exc}",
                flush=True,
            )
            continue
        if not verdicts:
            print(
                f"[tips] verify-batch overgeslagen: leeg resultaat ({len(part)} werken)",
                flush=True,
            )
            continue
        saved = 0
        async with session_maker() as s:
            for key, verdict in verdicts.items():
                await s.exec(
                    sa_text(
                        """
                        INSERT INTO tip_works
                            (title_key, keep, title, creator, category, confidence, model)
                        VALUES
                            (:title_key, :keep, :title, :creator, :category,
                             :confidence, :model)
                        ON CONFLICT (title_key) DO UPDATE SET
                            keep = EXCLUDED.keep,
                            title = EXCLUDED.title,
                            creator = EXCLUDED.creator,
                            category = EXCLUDED.category,
                            confidence = EXCLUDED.confidence,
                            model = EXCLUDED.model,
                            verified_at = now()
                        """
                    ).bindparams(
                        title_key=key,
                        keep=verdict["keep"],
                        title=verdict["title"],
                        creator=verdict["creator"],
                        category=verdict["category"],
                        confidence=verdict["confidence"],
                        model=model,
                    )
                )
                saved += 1
            await s.commit()
        total += saved
    return total


async def run_tips_job(session_maker, llm, *, max_items: int | None = None) -> dict:
    """Draai één tips-job: scan items en verifieer daarna nieuwe werken."""
    if _job_lock.locked():
        return {"ok": False, "skipped": "already_running"}
    async with _job_lock:
        model = tips_model()
        vmodel = verify_model()
        last_result.clear()
        last_result.update(
            {
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "items": 0,
                "done": 0,
                "failed": 0,
                "tips": 0,
                "verified": 0,
                "model": model,
                "verify_model": vmodel,
                "error": None,
            }
        )
        try:
            async with session_maker() as s:
                ids = await pick_items(s, max_items or max_items_default())
            last_result["items"] = len(ids)
            for item_id in ids:
                result = await scan_item(session_maker, llm, item_id, model)
                if result["status"] == "done":
                    last_result["done"] += 1
                    last_result["tips"] += result["tips"]
                else:
                    last_result["failed"] += 1
                print(
                    f"[tips] item {item_id}: {result['status']} ({result['tips']} tips)",
                    flush=True,
                )
            last_result["verified"] = await verify_new_works(session_maker, llm, vmodel)
        except Exception as exc:
            last_result["error"] = f"{type(exc).__name__}: {exc}"[:500]
            print(f"[tips] job mislukt: {last_result['error']}", flush=True)
        finally:
            last_result["finished_at"] = datetime.now(timezone.utc).isoformat()
        return {"ok": last_result["error"] is None, **last_result}


def spawn_tips_job(session_maker, llm, *, max_items: int | None = None) -> bool:
    """Start de tips-job op de achtergrond; False als er al één draait."""
    if _job_lock.locked():
        return False
    task = asyncio.create_task(run_tips_job(session_maker, llm, max_items=max_items))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True