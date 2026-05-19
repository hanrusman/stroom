import re
import numpy as np
import asyncio
from pathlib import Path
from sentence_transformers import SentenceTransformer
from services.llm_service import LLMService
from pipeline.digest_model_map import resolve_model


QUALITY_LLM_MODEL = "cloud-kimi"
QUALITY_LLM_TIMEOUT_SEC = 20.0
EMBED_MODEL_NAME = "intfloat/multilingual-e5-small"
CENTROID_PATH = Path("/data/centroid.npz")
EMBEDDING_SIM_LOW = 0.83
EMBEDDING_SIM_HIGH = 0.92


class QualityService:
    def __init__(self):
        self.model = None
        self.centroid = None

    def load(self) -> None:
        print("Loading embedding model...", flush=True)
        self.model = SentenceTransformer(EMBED_MODEL_NAME, device="cpu")
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

    async def score_quality(self, llm_service: LLMService, text: str, title: str | None,
                            model: str | None = None) -> int | None:
        """`model` is een Stroom-modelnaam (qwen/sonnet/opus/cloud-kimi/...)
        of None om de default `cloud-kimi` te gebruiken. Wordt via
        resolve_model() naar de echte LiteLLM-alias vertaald."""
        resolved = resolve_model(model or QUALITY_LLM_MODEL)
        system_prompt = (
            "Je bent een kwaliteitsbeoordelaar. Geef een score 1-10 voor de inhoudelijke kwaliteit van de tekst. "
            "Schaal: 1=spam/oppervlakkig, 5=gemiddeld, 10=uitstekend/diepgaand. De meeste content scoort 4-6. "
            "Output ALLEEN het cijfer (1-10). Geen uitleg, geen markdown, geen JSON, geen intro."
        )
        user_prompt = f"Titel: {title or 'Geen titel'}\n\nTekst:\n{text[:8000]}"
        try:
            response = await llm_service.call_llm(
                model=resolved,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.1,
                timeout=QUALITY_LLM_TIMEOUT_SEC
            )
            match = re.search(r"\b([1-9]|10)\b", response.strip())
            if match:
                return int(match.group(1))
        except Exception as e:
            print(f"Error scoring quality: {e}", flush=True)
        return None

    async def score_interest(self, text: str) -> int | None:
        if self.model is None or self.centroid is None:
            return None
        try:
            query_text = f"query: {text[:8000]}"
            query_vec = await asyncio.to_thread(
                self.model.encode,
                [query_text],
                normalize_embeddings=True
            )
            query_vec = query_vec[0]
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
