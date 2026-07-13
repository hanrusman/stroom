"""Hybride quality/interest-scoring (voorheen inline in main.py).

Quality via een cloud-LLM (model uit settings.model_defaults.score, default
cloud-kimi), interest via lokaal embedding-model + centroid. Fail-open: alle
paden returnen None/lege dict bij faal.
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

from fastapi import FastAPI

from core.config import settings
from services.llm_service import LLMService

log = logging.getLogger("stroom.scoring")

_QUALITY_WEIGHT = settings.QUALITY_HYBRID_QUALITY_WEIGHT
_INTEREST_WEIGHT = settings.QUALITY_HYBRID_INTEREST_WEIGHT

# Quality boost voor huygens ranking: extra seconden per quality punt boven 6
# Factor 2.0 = 2 dagen extra per punt (86400 * 2 = 172800 seconden)
QUALITY_BOOST_SECONDS = int(settings.QUALITY_BOOST_FACTOR * 86400)


def calculate_hybrid(quality: Optional[int], interest: Optional[int]) -> Optional[int]:
    """Hybrid score zoals quality-scorer het deed: q*0.4 + i*0.6.
    Als een van beide ontbreekt, val terug op de andere; beide None → None."""
    if quality is None and interest is None:
        return None
    if quality is None:
        return interest
    if interest is None:
        return quality
    return round(quality * _QUALITY_WEIGHT + interest * _INTEREST_WEIGHT)


# 60-seconden cache voor de model_defaults.score lookup. Voorkomt een DB-roundtrip
# per gescord item. Save via admin-UI doet niet meteen door — pas na deze TTL.
_SCORE_MODEL_CACHE: dict = {"model": None, "ts": 0.0}
_SCORE_MODEL_CACHE_TTL = 60.0


async def get_score_model() -> Optional[str]:
    """Lees de gekozen quality-model uit settings.model_defaults.score.
    None bij faal — quality_service.score_quality valt dan zelf terug op
    cloud-kimi default."""
    now = time.time()
    if (now - _SCORE_MODEL_CACHE["ts"]) < _SCORE_MODEL_CACHE_TTL and _SCORE_MODEL_CACHE["model"]:
        return _SCORE_MODEL_CACHE["model"]
    try:
        from core.db import async_session_maker
        from routers.settings import _load as _load_settings
        async with async_session_maker() as bg:
            defaults = await _load_settings(bg)
        _SCORE_MODEL_CACHE["model"] = defaults.score
        _SCORE_MODEL_CACHE["ts"] = now
        return defaults.score
    except Exception as e:
        log.warning("settings-fetch faalde, fallback default: %s", e)
        return None


async def score_with_quality_scorer(app: FastAPI, text: str,
                                    title: Optional[str] = None) -> Optional[int]:
    """Hybride 1-10 score voor een item. Fail-open: returnt None bij faal."""
    try:
        qs = app.state.quality_service
        llm = LLMService(app.state.llm_client)
        score_model = await get_score_model()
        quality, interest = await qs.score_both(llm, text, title, model=score_model)
        hybrid = calculate_hybrid(quality, interest)
        # Log voor evaluatie tegen de oude (lokale) quality-scorer:
        # te aggregeren via `docker logs stroom-api | grep '\[score\]'`.
        log.info("[score] m=%s q=%s i=%s h=%s title=%r",
                 score_model or "default", quality, interest, hybrid, (title or "")[:60])
        return hybrid
    except Exception as e:
        log.warning("hybrid faalde: %s", e)
        return None


async def score_batch_with_quality_scorer(app: FastAPI, items: List[dict]) -> dict[str, int]:
    """Batch-versie van hybrid scoring.

    Loopt sequentieel zodat we cloud-Kimi niet overspoelen; gebruikt
    `score_both` per item zodat quality + interest concurrent gaan per item.
    Returnt dict id → hybrid_score (faalde items omgeven).
    """
    if not items:
        return {}
    qs = app.state.quality_service
    llm = LLMService(app.state.llm_client)
    score_model = await get_score_model()
    out: dict[str, int] = {}
    for item in items:
        text = (item.get("text") or "")[:8000]
        title = item.get("title")
        item_id = item.get("id")
        if not text or not item_id:
            continue
        try:
            quality, interest = await qs.score_both(llm, text, title, model=score_model)
        except Exception as e:
            log.warning("batch item %s: %s", item_id, e)
            continue
        hybrid = calculate_hybrid(quality, interest)
        if hybrid is not None:
            out[item_id] = hybrid
    if settings.QUALITY_SCORER_DEBUG and out:
        lo = min(out.items(), key=lambda kv: kv[1])
        hi = max(out.items(), key=lambda kv: kv[1])
        log.info("batch debug: lowest=%s (id=%s), highest=%s (id=%s), n=%d",
                 lo[1], lo[0], hi[1], hi[0], len(out))
    return out
