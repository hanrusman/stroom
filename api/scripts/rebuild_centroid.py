"""Bouw de interest-centroid opnieuw uit positief-gerate lessons (rating=1).

Run binnen stroom-api container:
    python /app/scripts/rebuild_centroid.py

Output: /data/centroid.npz (atomisch via tmp + os.replace).
"""
import os
import sys
import asyncio
from pathlib import Path

import numpy as np
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sentence_transformers import SentenceTransformer

sys.path.insert(0, "/app")
from core.config import settings  # noqa: E402

EMBED_MODEL_NAME = "intfloat/multilingual-e5-small"
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


async def main() -> int:
    try:
        rows = await fetch_lessons()
    except Exception as exc:
        print(f"[rebuild-centroid] DB-query faalde: {exc}", flush=True)
        return 2

    if not rows:
        print("[rebuild-centroid] geen lessons met rating=1, niets te doen", flush=True)
        return 1

    print(f"[rebuild-centroid] {len(rows)} lessons gevonden — model laden...", flush=True)
    model = SentenceTransformer(EMBED_MODEL_NAME, device="cpu")

    corpus = [f"passage: {title}\n{body}"[:8000] for title, body in rows]
    print(f"[rebuild-centroid] embeddings berekenen ({len(corpus)} items)...", flush=True)

    try:
        embeddings = model.encode(
            corpus,
            batch_size=16,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    except Exception as exc:
        print(f"[rebuild-centroid] encode faalde: {exc}", flush=True)
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
