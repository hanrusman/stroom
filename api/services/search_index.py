"""Zoeken: zoekvectoren bijhouden + hybride (keyword + semantisch) zoeken.

Keyword = Postgres FTS over search_tsv met NL+EN-stemming (migratie 024;
de zoekvraag wordt omgezet in services/search_query). Semantisch = cosine-afstand op items.search_embedding, een
multilingual-e5-small vector (384 dim) uit de stroom-embed sidecar. Hybride
voegt beide ranglijsten samen met Reciprocal Rank Fusion: geen gedoe met het
schalen van ts_rank tegen cosine, en een item dat in beide lijsten hoog staat
wint.

De sidecar draait op één CPU-thread (~1 s per passage van 512 tokens), dus de
embed-loop werkt in kleine batches met een pauze ertussen. Een volledige
backfill duurt daardoor uren; recente items gaan voor.
"""
import asyncio
import os
from typing import Optional

import httpx
from sqlalchemy import text as sa_text

from services import search_query

EMBED_SERVICE_URL = os.environ.get("EMBED_SERVICE_URL", "").rstrip("/")
ENABLED = (os.environ.get("SEARCH_EMBED_ENABLED", "true").lower() in ("true", "1", "yes")
           and bool(EMBED_SERVICE_URL))
BATCH_SIZE = int(os.environ.get("SEARCH_EMBED_BATCH", "8"))
BATCH_PAUSE_SEC = float(os.environ.get("SEARCH_EMBED_PAUSE_SEC", "5"))
IDLE_SEC = float(os.environ.get("SEARCH_EMBED_IDLE_SEC", "300"))
PASSAGE_TIMEOUT_SEC = float(os.environ.get("SEARCH_EMBED_TIMEOUT_SEC", "120"))
QUERY_TIMEOUT_SEC = float(os.environ.get("SEARCH_QUERY_EMBED_TIMEOUT_SEC", "5"))
# Semantische hits verder dan deze cosine-afstand tellen niet mee: zonder
# drempel levert de vectorzoektocht altijd `pool` items op, ook bij onzin.
# e5-small perst alles samen: in een steekproef van 320 recente items (2026-10-12)
# lagen relevante hits op similarity 0.83-0.88, ruis op 0.78-0.83 en haalde een
# onzin-query 0.834. 0.17 (= sim 0.83) is dus een compromis, geen harde grens.
MAX_DISTANCE = float(os.environ.get("SEARCH_SEMANTIC_MAX_DISTANCE", "0.17"))
# Zoveel kandidaten per ranglijst gaan de fusie in; RRF_K is de standaardwaarde.
POOL = 50
RRF_K = 60

def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


async def embed(client: httpx.AsyncClient, texts: list[str], prefix: str,
                timeout: float) -> list[list[float]]:
    resp = await client.post(f"{EMBED_SERVICE_URL}/embed",
                             json={"texts": texts, "prefix": prefix}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["vectors"]


async def embed_query(client: httpx.AsyncClient, q: str) -> Optional[list[float]]:
    """Query-vector, of None als de sidecar er niet is of te traag is —
    de caller valt dan terug op alleen keyword."""
    # Uitsluitingen niet meeembedden: 'tour -kabinet' moet niet naar kabinet zoeken.
    text = search_query.positive_text(q)
    if not EMBED_SERVICE_URL or not text:
        return None
    try:
        return (await embed(client, [text], "query", QUERY_TIMEOUT_SEC))[0]
    except Exception as e:
        print(f"[search] query-embedding faalde, alleen keyword: {e!r}", flush=True)
        return None


async def embed_batch(async_session_maker, client: httpx.AsyncClient) -> int:
    """Embed één batch items zonder actuele zoekvector. Geeft het aantal
    geschreven vectoren terug; 0 = niets te doen.

    Actueel = search_embedded_version gelijk aan search_source_version; de
    trigger uit migratie 024 verhoogt die laatste zodra de passage verandert."""
    async with async_session_maker() as session:
        rows = (await session.exec(sa_text("""
            SELECT i.id::text,
                   stroom_search_passage(i.title, i.summary, i.description, i.transcript),
                   i.search_source_version
            FROM items i
            WHERE i.search_embedded_version IS DISTINCT FROM i.search_source_version
            ORDER BY i.published_at DESC NULLS LAST
            LIMIT :n
        """).bindparams(n=BATCH_SIZE))).all()
    if not rows:
        return 0
    vectors = await embed(client, [r[1] for r in rows], "passage", PASSAGE_TIMEOUT_SEC)
    async with async_session_maker() as session:
        for r, vec in zip(rows, vectors):
            # Is de passage tijdens het embedden veranderd, dan hoort deze
            # vector er niet bij; de volgende ronde pakt het item weer op.
            await session.exec(sa_text("""
                UPDATE items SET search_embedding = CAST(:v AS vector),
                                 search_embedded_version = :ver
                WHERE id = CAST(:i AS uuid) AND search_source_version = :ver
            """).bindparams(v=_vec_literal(vec), i=r[0], ver=r[2]))
        await session.commit()
    return len(rows)


async def embed_loop(async_session_maker, client: httpx.AsyncClient) -> None:
    await asyncio.sleep(90)  # eerst de API en de andere workers laten opstarten
    while True:
        try:
            n = await embed_batch(async_session_maker, client)
        except Exception as e:
            print(f"[search] embed-batch faalde: {e!r}", flush=True)
            n = 0
        await asyncio.sleep(BATCH_PAUSE_SEC if n else IDLE_SEC)


async def search(session, q: str, qvec: Optional[list[float]], fmt: Optional[str],
                 limit: int, mode: str) -> list:
    """Rijen (id, title, format, source_name, published_at, snippet, score, match).
    mode: 'hybrid' | 'keyword' | 'semantic'. Zonder qvec vervalt het
    semantische deel."""
    tsq, excl = await search_query.build(session, q)
    use_kw = mode in ("hybrid", "keyword") and tsq is not None
    use_sem = mode in ("hybrid", "semantic") and qvec is not None
    if not use_kw and not use_sem:
        return []

    fmt_filter = "AND i.format = CAST(:fmt AS item_format)" if fmt else ""
    params: dict = {"lim": limit, "pool": max(POOL, limit), "k": RRF_K}
    if tsq:
        params["tsq"] = tsq
    if fmt:
        params["fmt"] = fmt
    ranked = []
    if use_kw:
        ranked.append(f"""
            SELECT i.id, row_number() OVER (
                       ORDER BY ts_rank(i.search_tsv, CAST(:tsq AS tsquery)) DESC,
                                i.published_at DESC NULLS LAST) AS r,
                   'keyword' AS src
            FROM items i
            WHERE i.search_tsv @@ CAST(:tsq AS tsquery)
              AND i.status <> 'archived'::item_status {fmt_filter}
            ORDER BY r LIMIT :pool
        """)
    if use_sem:
        params["qv"] = _vec_literal(qvec)
        params["maxd"] = MAX_DISTANCE
        excl_filter = ""
        if excl:
            # Uitsluitingen die voor de hele vraag gelden ('tour -kabinet'),
            # niet die onder een OR ('fiets OR koken -kabinet').
            params["excl"] = excl
            excl_filter = "AND NOT i.search_tsv @@ CAST(:excl AS tsquery)"
        # ef_search >= pool, anders levert de HNSW-scan minder dan :pool
        # kandidaten op vóór de status/format-filters.
        await session.exec(sa_text(f"SET LOCAL hnsw.ef_search = {max(100, 2 * params['pool'])}"))
        ranked.append(f"""
            SELECT id, row_number() OVER (ORDER BY d) AS r, 'semantic' AS src
            FROM (
                SELECT i.id, i.search_embedding <=> CAST(:qv AS vector) AS d
                FROM items i
                WHERE i.search_embedding IS NOT NULL
                  AND i.status <> 'archived'::item_status {fmt_filter} {excl_filter}
                ORDER BY d LIMIT :pool
            ) nn
            WHERE d <= :maxd
        """)
    union = " UNION ALL ".join(f"({sql})" for sql in ranked)
    body = "coalesce(i.summary, i.description, left(i.transcript, 4000), '')"
    snippet = (f"ts_headline('dutch', {body}, CAST(:tsq AS tsquery), "
               "'MaxFragments=2,MinWords=8,MaxWords=22,StartSel=<mark>,StopSel=</mark>')"
               if tsq else f"left({body}, 200)")

    r = await session.exec(sa_text(f"""
        WITH ranked AS ({union}),
        fused AS (
            SELECT id, sum(1.0 / (:k + r)) AS score,
                   CASE WHEN count(DISTINCT src) > 1 THEN 'both' ELSE min(src) END AS match
            FROM ranked GROUP BY id
        )
        SELECT i.id::text, i.title, i.format::text, s.name, i.published_at,
               {snippet}, f.score, f.match
        FROM fused f
        JOIN items i ON i.id = f.id
        JOIN sources s ON s.id = i.source_id
        ORDER BY f.score DESC, i.published_at DESC NULLS LAST
        LIMIT :lim
    """).bindparams(**params))
    return r.all()
