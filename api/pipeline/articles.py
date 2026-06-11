"""Article-pipeline: full-text extractie via trafilatura + LLM-summarize.

Geen FastAPI dependencies. main.py importeert deze functies en wired ze
in de routes / cron / background-tasks.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import httpx
from sqlalchemy import text as sa_text

from core.url_guard import safe_get


async def extract_article_body(client: httpx.AsyncClient, url: str) -> Optional[str]:
    """Best-effort full-article extractie. Returnt platte tekst (>=100 woorden)
    of None bij fail. Async-safe: HTTP via httpx, parsing in thread executor."""
    if not url:
        return None
    try:
        r = await safe_get(
            client,
            url,
            headers={"User-Agent": "StroomBot/1.0 (+article-ingest)"},
            timeout=12.0,
        )
        if r.status_code != 200:
            return None
        ct = r.headers.get("content-type", "").lower()
        if "html" not in ct and "xml" not in ct:
            return None
        html = r.text
    except Exception:
        return None

    def _do_extract(html_str: str) -> Optional[str]:
        try:
            import trafilatura
            text = trafilatura.extract(
                html_str,
                include_comments=False, include_tables=False,
                include_links=True, include_formatting=True, include_images=True,
                output_format="markdown",
            )
            if not text or len(text.split()) < 100:
                return None
            return _dedupe_images(text)
        except Exception:
            return None

    return await asyncio.get_event_loop().run_in_executor(None, _do_extract, html)


_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _dedupe_images(md: str) -> str:
    """Strip duplicate ![alt](url) lines met dezelfde URL — trafilatura emit
    soms 2x dezelfde image (eenmaal als figure, eenmaal als og:image-fallback)."""
    seen: set[str] = set()
    out: list[str] = []
    for line in md.splitlines():
        m = _IMG_RE.search(line)
        if m:
            url = m.group(1)
            if url in seen:
                continue
            seen.add(url)
        out.append(line)
    return "\n".join(out)


async def backfill_articles(client: httpx.AsyncClient, async_session_maker,
                            days: int, limit: int) -> dict:
    """Trafilatura over articles zonder transcript van de laatste N dagen.
    Returnt {success, failed, total}."""
    sem = asyncio.Semaphore(4)
    async with async_session_maker() as bg:
        rows = (await bg.exec(sa_text(
            f"""
            SELECT id::text, media_url FROM items
            WHERE format='article'::item_format
              AND (transcript IS NULL OR length(transcript) < 200)
              AND media_url IS NOT NULL AND media_url <> ''
              AND published_at >= now() - interval '{int(days)} days'
            ORDER BY published_at DESC
            LIMIT {int(limit)}
            """
        ))).all()

    print(f"[article-backfill] kandidaten: {len(rows)}", flush=True)
    counters = {"success": 0, "failed": 0, "total": len(rows)}

    async def one(item_id: str, url: str):
        async with sem:
            body = await extract_article_body(client, url)
        if not body:
            counters["failed"] += 1
            return
        async with async_session_maker() as bg2:
            await bg2.exec(sa_text(
                "UPDATE items SET transcript = :t WHERE id = CAST(:i AS uuid)"
            ).bindparams(t=body, i=item_id))
            await bg2.commit()
        counters["success"] += 1

    await asyncio.gather(*[one(r[0], r[1]) for r in rows])
    print(f"[article-backfill] klaar — {counters}", flush=True)
    return counters
