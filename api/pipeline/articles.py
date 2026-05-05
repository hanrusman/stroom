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


async def extract_article_body(client: httpx.AsyncClient, url: str) -> Optional[str]:
    """Best-effort full-article extractie. Returnt platte tekst (>=100 woorden)
    of None bij fail. Async-safe: HTTP via httpx, parsing in thread executor."""
    if not url:
        return None
    try:
        r = await client.get(
            url,
            headers={"User-Agent": "StroomBot/1.0 (+article-ingest)"},
            timeout=12.0, follow_redirects=True,
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


async def summarize_articles(item_ids: list[str], llm_service, async_session_maker) -> int:
    """LLM-summarize voor articles met transcript. Concurrency-limited (3).
    Returnt aantal succesvol verwerkt."""
    if not item_ids:
        return 0
    sem = asyncio.Semaphore(3)
    success = 0

    async def one(item_id: str):
        nonlocal success
        async with sem:
            try:
                async with async_session_maker() as bg:
                    r = await bg.exec(sa_text(
                        "SELECT title, transcript FROM items WHERE id = CAST(:i AS uuid)"
                    ).bindparams(i=item_id))
                    row = r.first()
                    if not row or not row[1]:
                        return
                    title, transcript = row[0], row[1]
                    await bg.exec(sa_text(
                        "UPDATE items SET processing_status='summarizing'::processing_status, "
                        "processing_error=NULL WHERE id = CAST(:i AS uuid)"
                    ).bindparams(i=item_id))
                    await bg.commit()

                cleaned = re.sub(r"\s+", " ", transcript)[:12000]
                summary = await llm_service.call_llm("stroom-bulk", [
                    {"role": "system", "content": (
                        "Je bent een curator van hoogwaardige content. Vat het artikel samen in het "
                        "Nederlands, zakelijk maar warm, max 3 zinnen. Geef alleen de samenvatting "
                        "terug, geen inleiding."
                    )},
                    {"role": "user", "content": f"Titel: {title}\n\nTekst: {cleaned}"},
                ], temperature=0.3)

                async with async_session_maker() as bg:
                    await bg.exec(sa_text(
                        "UPDATE items SET summary=:s, summary_model='stroom-bulk', "
                        "summary_generated_at=now(), processing_status='ready'::processing_status "
                        "WHERE id = CAST(:i AS uuid)"
                    ).bindparams(s=summary.strip(), i=item_id))
                    await bg.commit()
                success += 1
            except Exception as exc:
                try:
                    async with async_session_maker() as bg:
                        await bg.exec(sa_text(
                            "UPDATE items SET processing_status='failed'::processing_status, "
                            "processing_error=:e WHERE id = CAST(:i AS uuid)"
                        ).bindparams(e=f"article-summarize: {exc}"[:500], i=item_id))
                        await bg.commit()
                except Exception:
                    pass

    await asyncio.gather(*[one(i) for i in item_ids])
    print(f"[article-summarize] klaar — {success}/{len(item_ids)} succes", flush=True)
    return success
