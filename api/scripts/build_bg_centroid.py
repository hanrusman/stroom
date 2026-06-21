"""Bouw het background-centroid voor de contrastieve interest-score.

Het background-centroid is de genormaliseerde mean van een random sample items
("gemiddelde content"). score_interest doet cos(q,pos) - cos(q,bg): hoeveel meer
een item op je likes lijkt dan op gemiddelde content. Dit de-inflateert items die
nu eenmaal op alles lijken (fixt dat not_interesting-items ten onrechte hoog
scoorden).

Run binnen stroom-api:
    python /app/scripts/build_bg_centroid.py

Bevroren artefact: draai alleen opnieuw bij grote shifts in de corpus-mix.
Output: /data/bg_centroid.npz (atomisch via tmp + os.replace).
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
EMBED_BATCH = 4  # klein: grote batches lange teksten kunnen de sidecar laten crashen
SAMPLE_SIZE = int(os.environ.get("BG_SAMPLE_SIZE", "500"))
OUTPUT_PATH = Path(os.environ.get("BG_CENTROID_PATH", "/data/bg_centroid.npz"))
TXT = "COALESCE(summary, transcript, description, title)"


async def fetch_sample() -> list[str]:
    engine = create_async_engine(settings.ASYNC_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            r = await conn.execute(sa.text(
                f"SELECT {TXT} FROM items WHERE {TXT} IS NOT NULL "
                f"AND length({TXT}) > 200 ORDER BY random() LIMIT :n"
            ).bindparams(n=SAMPLE_SIZE))
            return [row[0] for row in r.fetchall()]
    finally:
        await engine.dispose()


async def embed_all(texts: list[str]) -> np.ndarray:
    vecs: list[list[float]] = []
    async with httpx.AsyncClient(timeout=EMBED_TIMEOUT_SEC) as client:
        for start in range(0, len(texts), EMBED_BATCH):
            batch = [t[:8000] for t in texts[start:start + EMBED_BATCH]]
            for attempt in range(2):
                try:
                    resp = await client.post(
                        f"{EMBED_SERVICE_URL}/embed",
                        json={"texts": batch, "prefix": "query"},
                    )
                    resp.raise_for_status()
                    vecs.extend(resp.json()["vectors"])
                    break
                except Exception as exc:
                    if attempt == 0:
                        await asyncio.sleep(3)
                    else:
                        print(f"[bg-centroid] batch {start} overgeslagen: {exc}", flush=True)
            if start % 40 == 0:
                print(f"[bg-centroid] embedded {len(vecs)}/{len(texts)}", flush=True)
    return np.asarray(vecs, dtype=np.float32)


async def main() -> int:
    if not EMBED_SERVICE_URL:
        print("[bg-centroid] EMBED_SERVICE_URL leeg — afbreken", flush=True)
        return 2
    texts = await fetch_sample()
    if len(texts) < 50:
        print(f"[bg-centroid] te weinig items ({len(texts)}) — afbreken", flush=True)
        return 1

    print(f"[bg-centroid] {len(texts)} items — embeddings via sidecar...", flush=True)
    emb = await embed_all(texts)
    if len(emb) < 50:
        print(f"[bg-centroid] te weinig embeddings ({len(emb)}) — afbreken", flush=True)
        return 2

    bg = np.mean(emb, axis=0).astype(np.float32)
    bg /= np.linalg.norm(bg)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_PATH.with_suffix(".npz.tmp")
    with open(tmp, "wb") as fh:
        np.savez(fh, centroid=bg, sample_size=len(emb))
    os.replace(tmp, OUTPUT_PATH)
    print(f"[bg-centroid] geschreven naar {OUTPUT_PATH} "
          f"(shape={bg.shape}, sample={len(emb)})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
