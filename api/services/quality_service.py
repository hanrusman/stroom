import os
import re
import time
import asyncio
from pathlib import Path

import numpy as np
import httpx

from services.llm_service import LLMService
from pipeline.digest_model_map import resolve_model


QUALITY_LLM_MODEL = "cloud-gpt-120b"
QUALITY_LLM_TIMEOUT_SEC = 60.0
CENTROID_PATH = Path("/data/centroid.npz")
# Cosine(query, centroid) -> 1-10 lineair via clip((sim-LOW)/(HIGH-LOW),0,1)*9+1.
# Geijkt op de p10/p90 van een sample van 300 echte items (2026-06-20, int8-model):
# de cosines clusteren strak rond 0.89 (p10=0.866, p90=0.908), dus een band van
# 0.83-0.92 boog de scores omhoog. Env-tunebaar omdat de waarden mee-driften als
# de centroid verandert (nieuwe lessons). Herijk met een sample na grote shifts.
EMBEDDING_SIM_LOW = float(os.environ.get("EMBEDDING_SIM_LOW", "0.866"))
EMBEDDING_SIM_HIGH = float(os.environ.get("EMBEDDING_SIM_HIGH", "0.908"))

# Interest-embeddings draaien sinds 2026-06 in de losse stroom-embed sidecar
# (ONNX-int8 e5-small) i.p.v. in-process sentence-transformers — dat at ~1 GB
# resident en zette de mem-gate dicht. score_interest praat nu over HTTP met
# de sidecar en faalt fail-open naar None bij elke hapering. Een circuit-breaker
# voorkomt dat een zieke/trage sidecar de scoring-pijplijn laat hangen.
EMBED_SERVICE_URL = os.environ.get("EMBED_SERVICE_URL", "").rstrip("/")
EMBED_TIMEOUT_SEC = float(os.environ.get("EMBED_TIMEOUT_SEC", "5.0"))
EMBED_BREAKER_THRESHOLD = int(os.environ.get("EMBED_BREAKER_THRESHOLD", "5"))
EMBED_BREAKER_COOLDOWN_SEC = float(os.environ.get("EMBED_BREAKER_COOLDOWN_SEC", "60"))
EMBED_MAX_CONCURRENCY = int(os.environ.get("EMBED_MAX_CONCURRENCY", "4"))


class QualityService:
    def __init__(self):
        self.centroid = None
        self._client: httpx.AsyncClient | None = None
        self._sem = asyncio.Semaphore(EMBED_MAX_CONCURRENCY)
        self._fail_count = 0
        self._open_until = 0.0  # time.monotonic()-waarde; breaker open zolang now < dit

    def load(self) -> None:
        # Geen in-process model meer; alleen de centroid uit /data inlezen.
        if not EMBED_SERVICE_URL:
            print("Interest-embeddings: EMBED_SERVICE_URL leeg — score_interest geeft None.",
                  flush=True)
        else:
            print(f"Interest-embeddings via sidecar: {EMBED_SERVICE_URL}", flush=True)
        self.reload_centroid()

    def reload_centroid(self) -> None:
        if CENTROID_PATH.exists():
            try:
                data = np.load(CENTROID_PATH)
                self.centroid = data["centroid"].astype(np.float32)
                print(f"Centroid loaded: shape={self.centroid.shape}", flush=True)
            except Exception as e:
                print(f"Failed to load centroid: {e}", flush=True)
                self.centroid = None
        else:
            print("Centroid file not found.", flush=True)
            self.centroid = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=EMBED_TIMEOUT_SEC,
                limits=httpx.Limits(max_connections=EMBED_MAX_CONCURRENCY),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _embed_query(self, text: str) -> np.ndarray | None:
        """Eén query-embedding via de sidecar. None bij breaker-open of faal."""
        if time.monotonic() < self._open_until:
            return None
        async with self._sem:
            try:
                resp = await self._get_client().post(
                    f"{EMBED_SERVICE_URL}/embed",
                    json={"texts": [text[:8000]], "prefix": "query"},
                )
                resp.raise_for_status()
                vec = np.asarray(resp.json()["vectors"][0], dtype=np.float32)
                self._fail_count = 0
                return vec
            except Exception as e:
                self._fail_count += 1
                if self._fail_count >= EMBED_BREAKER_THRESHOLD:
                    self._open_until = time.monotonic() + EMBED_BREAKER_COOLDOWN_SEC
                    self._fail_count = 0
                    print(f"[quality] embed-breaker open voor {EMBED_BREAKER_COOLDOWN_SEC}s "
                          f"(laatste fout: {e})", flush=True)
                return None

    async def score_quality(self, llm_service: LLMService, text: str, title: str | None,
                            model: str | None = None) -> int | None:
        """`model` is een Stroom-modelnaam (qwen/sonnet/opus/cloud-kimi/...)
        of None om de default `cloud-kimi` te gebruiken. Wordt via
        resolve_model() naar de echte LiteLLM-alias vertaald."""
        resolved = resolve_model(model or QUALITY_LLM_MODEL)
        system_prompt = (
            "You are a content quality rater. Score the intellectual quality of the text on a 1-10 scale. "
            "Use the full range: "
            "1-2=spam, clickbait, or pure advertisement; "
            "3-4=shallow overview, obvious points, low signal; "
            "5-6=decent but unremarkable, standard trade-press level; "
            "7-8=well-argued, specific insights, worth reading; "
            "9-10=exceptional depth, original analysis, or rare expertise. "
            "Be discriminating — reward genuine depth, penalise vagueness. "
            "Output ONLY the single digit or '10'. No explanation, no markdown."
        )
        user_prompt = f"Title: {title or 'No title'}\n\nText:\n{text[:8000]}"
        try:
            response = await llm_service.call_llm(
                model=resolved,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.1,
                timeout=QUALITY_LLM_TIMEOUT_SEC,
            )
            match = re.search(r"\b([1-9]|10)\b", response.strip())
            if match:
                return int(match.group(1))
        except Exception as e:
            print(f"Error scoring quality: {e}", flush=True)
        return None

    async def score_interest(self, text: str) -> int | None:
        if self.centroid is None or not EMBED_SERVICE_URL:
            return None
        query_vec = await self._embed_query(text)
        if query_vec is None:
            return None
        try:
            if query_vec.shape != self.centroid.shape:
                return None
            sim = np.dot(query_vec, self.centroid).item()
            normalized = np.clip((sim - EMBEDDING_SIM_LOW) / (EMBEDDING_SIM_HIGH - EMBEDDING_SIM_LOW), 0, 1)
            score = round(normalized * 9) + 1
            return int(score)
        except Exception as e:
            print(f"Error scoring interest: {e}", flush=True)
            return None

    async def score_both(self, llm_service: LLMService, text: str, title: str | None,
                         model: str | None = None) -> tuple[int | None, int | None]:
        q_task = asyncio.create_task(self.score_quality(llm_service, text, title, model))
        i_task = asyncio.create_task(self.score_interest(text))
        quality_score, interest_score = await asyncio.gather(q_task, i_task, return_exceptions=True)
        if isinstance(quality_score, Exception):
            quality_score = None
        if isinstance(interest_score, Exception):
            interest_score = None
        return quality_score, interest_score
