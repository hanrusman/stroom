"""Router voor tips: aanbevelingen uit transcripten."""

import time
from typing import Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import require_user
from core.db import get_async_session
from services import tips_service

router = APIRouter()

_CACHE_TTL = 300.0
_CACHE_MAX = 16
_cache: Dict[str, Tuple[float, Optional[str], List[dict]]] = {}


async def _aggregated_works(session, since: Optional[str]) -> List[dict]:
    """Geaggregeerde werken per since-waarde, met cache (TTL 300 s)."""
    finished_at = tips_service.last_result.get("finished_at")
    key = since or ""
    entry = _cache.get(key)
    if entry is not None:
        stored_at, stored_finished, works = entry
        if stored_finished != finished_at:
            _cache.clear()
        elif time.time() - stored_at < _CACHE_TTL:
            return works
        else:
            del _cache[key]
    mentions = await tips_service.load_mentions(session)
    works_by_key = await tips_service.load_works(session)
    works = tips_service.aggregate(mentions, works_by_key, since=since)
    _cache[key] = (time.time(), finished_at, works)
    while len(_cache) > _CACHE_MAX:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest]
    return works


@router.get("/tips")
async def list_tips(
    category: Optional[str] = Query(None),
    since: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    q: Optional[str] = Query(None, max_length=200),
    source: Optional[str] = Query(None),
    strong_only: bool = False,
    min_episodes: int = Query(1, ge=1, le=100),
    sort: Literal["score", "episodes", "recent", "title"] = "score",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session=Depends(get_async_session),
    user=Depends(require_user),
) -> dict:
    """Overzicht van aanbevolen werken met filters."""
    works = await _aggregated_works(session, since)
    return tips_service.query_works(
        works,
        category=category,
        q=q,
        source=source,
        strong_only=strong_only,
        min_episodes=min_episodes,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/tips/mentions")
async def list_tip_mentions(
    title_key: str = Query(..., max_length=300),
    category: Optional[str] = Query(None),
    since: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session=Depends(get_async_session),
    user=Depends(require_user),
) -> dict:
    """Alle vermeldingen van één werk."""
    works = await _aggregated_works(session, since)
    for work in works:
        if work.get("title_key") != title_key:
            continue
        if category is not None and work.get("category") != category:
            continue
        return {
            "title": work.get("title"),
            "creator": work.get("creator"),
            "category": work.get("category"),
            "title_key": work.get("title_key"),
            "episodes": work.get("episodes"),
            "mentions": work.get("mentions"),
        }
    raise HTTPException(status_code=404, detail="Tip niet gevonden")
