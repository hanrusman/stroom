"""Full-text search over items (endpoint voorheen in main.py)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text as sa_text

from core.db import get_async_session
from schemas.huygens import SearchHit

router = APIRouter(tags=["search"])


@router.get("/search", response_model=List[SearchHit])
async def search_items(q: str = Query(..., min_length=2),
                       format: Optional[str] = Query(None),
                       limit: int = Query(20, le=100),
                       session=Depends(get_async_session)):
    """Postgres FTS over title+summary+transcript+description.
    `q` accepteert websearch_to_tsquery syntax: 'foo bar' (AND), 'foo OR bar', '"exact phrase"'."""
    fmt_filter = ""
    params: dict = {"q": q, "lim": limit}
    if format in ("article", "podcast", "video"):
        fmt_filter = "AND i.format = :fmt::item_format"
        params["fmt"] = format

    r = await session.exec(sa_text(
        f"""
        SELECT i.id::text, i.title, i.format::text, s.name,
               i.published_at,
               ts_headline('simple',
                           coalesce(i.summary, i.description, left(i.transcript, 4000), ''),
                           websearch_to_tsquery('simple', :q),
                           'MaxFragments=2,MinWords=8,MaxWords=22,StartSel=<mark>,StopSel=</mark>') as snippet,
               ts_rank(i.search_tsv, websearch_to_tsquery('simple', :q)) as rank
        FROM items i
        JOIN sources s ON s.id = i.source_id
        WHERE i.search_tsv @@ websearch_to_tsquery('simple', :q)
          AND i.status <> 'archived'::item_status
          {fmt_filter}
        ORDER BY rank DESC, i.published_at DESC NULLS LAST
        LIMIT :lim
        """
    ).bindparams(**params))
    rows = r.all()
    return [SearchHit(
        id=row[0], title=row[1], format=row[2], source_name=row[3],
        published_at=str(row[4]) if row[4] else None,
        snippet=row[5] or "",
        rank=float(row[6]),
    ) for row in rows]
