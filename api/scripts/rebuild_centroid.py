"""Bouw de interest-centroid opnieuw uit positief-gerate lessons (rating=1).

Run binnen stroom-api container:
    python /app/scripts/rebuild_centroid.py

Embeddings komen sinds 2026-06 van de stroom-embed sidecar (ONNX-int8 e5-small),
niet meer uit een in-process sentence-transformer. Zo embedden centroid (hier,
prefix=passage) en query (quality_service, prefix=query) via exact hetzelfde
model — geen fp32/int8-drift in de cosine-vergelijking.

Output: /data/centroid.npz (atomisch via tmp + os.replace).
"""
import os
import sys
import asyncio
from pathlib import Path

import numpy as np
import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, "/app")
from core.config import settings  # noqa: E402

EMBED_SERVICE_URL = os.environ.get("EMBED_SERVICE_URL", "").rstrip("/")
EMBED_TIMEOUT_SEC = float(os.environ.get("EMBED_TIMEOUT_SEC", "30.0"))
EMBED_BATCH = 32  # sidecar accepteert max 64 per call
OUTPUT_PATH = Path(os.environ.get("CENTROID_PATH", "/data/centroid.npz"))


async def fetch_lessons() -> list[tuple[str, str]]:
    engine = create_async_engine(settings.ASYNC_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            r = await conn.execute(sa.text(
                "SELECT title, body FROM lessons WHERE rating = 1"
            ))
            return [(row[0] or "", row[1] or "") for row in r.fetchall()]
    finally:
        await engine.dispose()


async def embed_corpus(corpus: list[str]) -> np.ndarray:
    """Vraag de sidecar om passage-embeddings, in batches."""
    vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=EMBED_TIMEOUT_SEC) as client:
        for start in range(0, len(corpus), EMBED_BATCH):
            batch = corpus[start:start + EMBED_BATCH]
            resp = await client.post(
                f"{EMBED_SERVICE_URL}/embed",
                json={"texts": batch, "prefix": "passage"},
            )
            resp.raise_for_status()
            vectors.extend(resp.json()["vectors"])
            print(f"[rebuild-centroid] embedded {len(vectors)}/{len(corpus)}", flush=True)
    return np.asarray(vectors, dtype=np.float32)


async def main() -> int:
    if not EMBED_SERVICE_URL:
        print("[rebuild-centroid] EMBED_SERVICE_URL leeg — sidecar onbereikbaar, afbreken",
              flush=True)
        return 2

    try:
        rows = await fetch_lessons()
    except Exception as exc:
        print(f"[rebuild-centroid] DB-query faalde: {exc}", flush=True)
        return 2

    if not rows:
        print("[rebuild-centroid] geen lessons met rating=1, niets te doen", flush=True)
        return 1

    # Raw title\nbody; de sidecar prepend zelf de "passage: "-prefix.
    corpus = [f"{title}\n{body}"[:8000] for title, body in rows]
    print(f"[rebuild-centroid] {len(corpus)} lessons — embeddings via sidecar...", flush=True)

    try:
        embeddings = await embed_corpus(corpus)
    except Exception as exc:
        print(f"[rebuild-centroid] embed faalde: {exc}", flush=True)
        return 2

    centroid = np.mean(embeddings, axis=0).astype(np.float32)
    centroid /= np.linalg.norm(centroid)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # np.savez voegt automatisch ".npz" toe aan een string-pad maar respecteert
    # een open file-handle. Schrijf via handle zodat tmp + os.replace atomisch werken.
    tmp = OUTPUT_PATH.with_suffix(".npz.tmp")
    with open(tmp, "wb") as fh:
        np.savez(fh, centroid=centroid, corpus_size=len(corpus))
    os.replace(tmp, OUTPUT_PATH)

    print(f"[rebuild-centroid] geschreven naar {OUTPUT_PATH} "
          f"(shape={centroid.shape}, corpus_size={len(corpus)})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
