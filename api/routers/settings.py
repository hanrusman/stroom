from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.auth import require_user
from core.db import get_async_session

router = APIRouter()

DigestModel = Literal[
    "qwen", "sonnet", "opus", "long",
    "cloud-kimi", "cloud-qwen-coder", "cloud-gpt-120b",
    "cloud-gpt-20b", "cloud-gemma",
]


class ModelDefaults(BaseModel):
    expand: DigestModel
    distill: DigestModel
    digest: DigestModel
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
