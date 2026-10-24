from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text as sql

from core.db import get_async_session
from services import podcast_converter as pc

router = APIRouter(prefix="/podcast-tests", tags=["Podcast converter"])


class GenerateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=pc.MAX_TEXT)
    model: Literal["omnivoice", "kittentts", "cosyvoice"]

    @field_validator("text")
    @classmethod
    def meaningful_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Plak eerst een tekst.")
        return value


@router.get("/models")
async def models(request: Request):
    return await pc.catalog(request.app.state.http_client)


@router.get("")
async def history(session=Depends(get_async_session)):
    if not pc.enabled():
        return []
    rows = (await session.execute(sql("SELECT * FROM podcast_tests ORDER BY created_at DESC LIMIT 30"))).mappings()
    return [pc.public_job(row) for row in rows]


@router.post("", status_code=202)
async def generate(body: GenerateRequest, request: Request, session=Depends(get_async_session)):
    choices = await pc.catalog(request.app.state.http_client)
    selected = next(m for m in choices["models"] if m["id"] == body.model)
    if not selected["available"]:
        raise HTTPException(503, selected["reason"])
    return await pc.enqueue(session, body.text, body.model)


@router.get("/{job_id}/audio")
async def audio(job_id: UUID, session=Depends(get_async_session)):
    status = (await session.execute(sql("SELECT status FROM podcast_tests WHERE id=:id"), {"id": job_id})).scalar()
    path = pc.audio_path(job_id)
    if status != "ready" or not path.is_file():
        raise HTTPException(404, "Audio is nog niet beschikbaar.")
    return FileResponse(path, media_type="audio/mpeg", filename=f"stroom-{job_id}.mp3",
                        content_disposition_type="inline", headers={"Cache-Control": "private, no-store"})


@router.delete("/{job_id}", status_code=204)
async def remove(job_id: UUID, session=Depends(get_async_session)):
    # No lock needed: the worker only moves 'queued' to 'rendering' conditionally,
    # and a row being rendered is never deleted here.
    deleted = (await session.execute(sql(
        "DELETE FROM podcast_tests WHERE id=:id AND status<>'rendering' RETURNING id"
    ), {"id": job_id})).first()
    if not deleted:
        exists = (await session.execute(sql("SELECT 1 FROM podcast_tests WHERE id=:id"), {"id": job_id})).first()
        if exists:
            raise HTTPException(409, "Deze podcast wordt nog gemaakt.")
        raise HTTPException(404, "Test niet gevonden.")
    await session.commit()
    pc.audio_path(job_id).unlink(missing_ok=True)
