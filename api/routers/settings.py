import asyncio
import time
from typing import List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.auth import require_user
from core.config import settings as app_settings
from core.db import get_async_session
from pipeline.model_catalog import (
    MODEL_CATALOG,
    BY_ALIAS,
    is_embedding_alias,
    stroom_name_for_alias,
)

router = APIRouter()

# Vrije modelnaam — de geldige set is dynamisch en komt uit GET /admin/models
# (live LiteLLM). resolve_model() vertaalt een Stroom-naam naar de echte alias.
DigestModel = str


class ModelDefaults(BaseModel):
    expand: DigestModel = "qwen"
    distill: DigestModel = "qwen"
    digest: DigestModel = "opus"
    # Aparte synthese-laag voor de weekdigest. Drift-knop: kies hier een ander
    # (bv. niet-reasoning) model dan de dag-digest. Default = opus (gelijk aan digest).
    digest_weekly: DigestModel = "opus"
    ask: DigestModel = "qwen"
    score: DigestModel = "cloud-kimi"


class Settings(BaseModel):
    model_defaults: ModelDefaults


DEFAULTS = ModelDefaults(
    expand="qwen", distill="qwen", digest="opus", digest_weekly="opus",
    ask="qwen", score="cloud-kimi",
)


async def _load(session) -> ModelDefaults:
    row = (await session.execute(
        sa_text("SELECT value FROM app_settings WHERE key = 'model_defaults'")
    )).first()
    if not row:
        return DEFAULTS
    try:
        # Tolerate missing keys (older rows) by merging onto DEFAULTS.
        merged = {**DEFAULTS.model_dump(), **(row[0] or {})}
        return ModelDefaults(**merged)
    except Exception:
        return DEFAULTS


@router.get("/admin/settings", response_model=Settings)
async def get_settings(session=Depends(get_async_session), user=Depends(require_user)):
    return Settings(model_defaults=await _load(session))


@router.put("/admin/settings", response_model=Settings)
async def put_settings(body: Settings, session=Depends(get_async_session), user=Depends(require_user)):
    await session.execute(sa_text("""
        INSERT INTO app_settings (key, value, updated_at)
        VALUES ('model_defaults', CAST(:v AS jsonb), now())
        ON CONFLICT (key) DO UPDATE
          SET value = EXCLUDED.value, updated_at = now()
    """), {"v": body.model_defaults.model_dump_json()})
    await session.commit()
    return Settings(model_defaults=await _load(session))


# ---------------------------------------------------------------------------
# Dynamische modellijst — wat LiteLLM nú serveert, verrijkt met curatie.
# ---------------------------------------------------------------------------

class ModelInfo(BaseModel):
    name: str                       # Stroom-naam (te gebruiken in model_defaults / endpoints)
    litellm: str                    # onderliggende LiteLLM-alias
    label: str                      # UI-label
    category: str                   # 'local' | 'cloud'
    status: str = "ok"              # 'ok' | 'degraded' | 'unknown'
    reason: Optional[str] = None    # toelichting bij 'degraded'/'unknown'


def _litellm_base() -> str:
    """Leid de LiteLLM-basis-URL af van de chat-completions-URL in de config."""
    url = app_settings.LITELLM_URL
    return url.split("/v1/")[0] if "/v1/" in url else url.rstrip("/")


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {app_settings.LITELLM_MASTER_KEY}"}


# Health van krediet-/quota-gevoelige aliassen wordt live gepolld maar gecached:
# de probe doet een echte provider-call, dus niet bij elke admin-render opnieuw.
_HEALTH_TTL = 60.0
_health_cache: dict = {"ts": 0.0, "status": {}}  # alias -> (status, reason)
_health_lock = asyncio.Lock()


async def _probe_one(client: httpx.AsyncClient, alias: str) -> Optional[Tuple[str, Tuple[str, Optional[str]]]]:
    """Probe één alias via /health?model=<alias>. None bij probe-fout (→ 'unknown')."""
    try:
        r = await client.get(
            f"{_litellm_base()}/health",
            params={"model": alias},
            headers=_auth_headers(),
            timeout=8.0,
        )
        r.raise_for_status()
        data = r.json()
        unhealthy = data.get("unhealthy_endpoints")
        if not isinstance(unhealthy, list):
            unhealthy = []
        if data.get("unhealthy_count", 0) > 0 or unhealthy:
            reason = None
            if unhealthy and isinstance(unhealthy[0], dict):
                reason = unhealthy[0].get("error") or unhealthy[0].get("message")
            return alias, ("degraded", _short_reason(reason))
        return alias, ("ok", None)
    except Exception:
        return None


async def _flaky_health(client: httpx.AsyncClient) -> dict:
    """Poll de flaky aliassen (parallel, gecached) via /health?model=<alias>.

    Geeft per alias ('degraded', reason) of ('ok', None). Aliassen waarvoor de
    probe zelf faalt ontbreken (→ status blijft 'unknown')."""
    now = time.monotonic()
    if _health_cache["ts"] > 0 and now - _health_cache["ts"] < _HEALTH_TTL:
        return _health_cache["status"]

    # Lock + double-check voorkomt cache-stampede: niet N parallelle requests
    # die elk de flaky modellen pollen (en LiteLLM onnodig belasten).
    async with _health_lock:
        now = time.monotonic()
        if _health_cache["ts"] > 0 and now - _health_cache["ts"] < _HEALTH_TTL:
            return _health_cache["status"]

        flaky = [e.litellm for e in MODEL_CATALOG if e.flaky and not e.hidden]
        results = await asyncio.gather(*(_probe_one(client, a) for a in flaky))
        out = {alias: status for r in results if r for alias, status in [r]}

        _health_cache.update(ts=now, status=out)
        return out


def _short_reason(reason: Optional[str]) -> Optional[str]:
    if not reason:
        return "tijdelijk niet beschikbaar (krediet/quota?)"
    s = str(reason)
    return s[:200] + "…" if len(s) > 200 else s


@router.get("/admin/models", response_model=List[ModelInfo])
async def list_models(request: Request, user=Depends(require_user)):
    """Modellen die LiteLLM nú serveert, met vriendelijke labels en live status.

    Dynamisch: een model dat in litellm/config.yaml wordt toegevoegd verschijnt
    hier automatisch. Embeddings worden weggefilterd. Krediet-/quota-gevoelige
    modellen (Anthropic/Gemini) krijgen een live 'degraded'-status."""
    http_client: httpx.AsyncClient = request.app.state.http_client
    llm_client: httpx.AsyncClient = request.app.state.llm_client

    try:
        resp = await http_client.get(
            f"{_litellm_base()}/v1/models", headers=_auth_headers(), timeout=10.0
        )
        resp.raise_for_status()
        available = [m["id"] for m in resp.json().get("data", []) if m.get("id")]
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Kon de modellijst niet bij LiteLLM ophalen: {exc}",
        )

    health = await _flaky_health(llm_client)

    chat_aliases = [a for a in available if not is_embedding_alias(a)]

    # Sorteer: catalogus-volgorde eerst (vertrouwd), onbekende live-modellen erna.
    order = {e.litellm: i for i, e in enumerate(MODEL_CATALOG)}
    chat_aliases.sort(key=lambda a: (order.get(a, len(order)), a))

    out: List[ModelInfo] = []
    for alias in chat_aliases:
        entry = BY_ALIAS.get(alias)
        # Permanent-dode modellen (geen credit/geen key) volledig verbergen.
        if entry is not None and entry.hidden:
            continue
        status, reason = "ok", None
        if alias in health:
            status, reason = health[alias]
        elif entry is not None and entry.flaky:
            status = "unknown"  # flaky maar health-probe gaf geen uitsluitsel

        out.append(ModelInfo(
            name=stroom_name_for_alias(alias),
            litellm=alias,
            label=entry.label if entry else alias,
            category=entry.category if entry else "cloud",
            status=status,
            reason=reason,
        ))

    return out
