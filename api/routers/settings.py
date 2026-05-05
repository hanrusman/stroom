from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.auth import require_user
from core.db import get_async_session

router = APIRouter()

DigestModel = Literal["qwen", "sonnet", "opus"]


class ModelDefaults(BaseModel):
    expand: DigestModel
    distill: DigestModel
    digest: DigestModel


class Settings(BaseModel):
    model_defaults: ModelDefaults


DEFAULTS = ModelDefaults(expand="qwen", distill="qwen", digest="opus")


async def _load(session) -> ModelDefaults:
    row = (await session.execute(
        sa_text("SELECT value FROM app_settings WHERE key = 'model_defaults'")
    )).first()
    if not row:
        return DEFAULTS
    try:
        return ModelDefaults(**row[0])
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
