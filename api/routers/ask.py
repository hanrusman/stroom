from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.auth import require_user
from core.db import get_async_session
from services.llm_service import LLMService

router = APIRouter()

AskModel = Literal["qwen", "sonnet", "opus"]

_MODEL_ALIAS: dict[str, str] = {
    "qwen": "stroom-bulk",
    "sonnet": "stroom-sonnet",
    "opus": "stroom-deep",
}


class AskBody(BaseModel):
    question: str


class AskAnswer(BaseModel):
    question: str
    answer: str
    model: AskModel
    sources_used: list[str]  # which fields fed the prompt: 'transcript', 'description', 'summary', 'lessons'


def _llm(request: Request) -> LLMService:
    return LLMService(request.app.state.http_client)


@router.post("/huygens/items/{item_id}/ask", response_model=AskAnswer)
async def ask_item(item_id: str,
                   body: AskBody,
                   request: Request,
                   model: AskModel = Query("qwen"),
                   session=Depends(get_async_session),
                   user=Depends(require_user)):
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Lege vraag.")
    if len(q) > 500:
        raise HTTPException(status_code=400, detail="Vraag is te lang (max 500 tekens).")

    item_row = (await session.execute(sa_text("""
        SELECT title, transcript, description, summary, type::text
        FROM items WHERE id = CAST(:i AS uuid)
    """), {"i": item_id})).first()
    if not item_row:
        raise HTTPException(status_code=404, detail="Item not found")
    title, transcript, description, summary, item_type = item_row

    sources_used: list[str] = []
    body_text: Optional[str] = None
    if transcript and transcript.strip():
        body_text = transcript.strip()
        sources_used.append("transcript")
    elif description and description.strip():
        # Strip HTML tags from description for cleaner context.
        import re as _re
        body_text = _re.sub(r"<[^>]+>", " ", description)
        body_text = _re.sub(r"\s+", " ", body_text).strip()
        if body_text:
            sources_used.append("description")
    body_text = (body_text or "")[:18000]

    summary_block = (summary or "").strip()
    if summary_block:
        sources_used.append("summary")

    lesson_rows = (await session.execute(sa_text("""
        SELECT title, body FROM lessons WHERE item_id = CAST(:i AS uuid) ORDER BY idx ASC LIMIT 20
    """), {"i": item_id})).all()
    lessons_block = ""
    if lesson_rows:
        lessons_block = "\n".join(f"- {r[0]}: {r[1]}" for r in lesson_rows)
        sources_used.append("lessons")

    if not body_text and not summary_block:
        raise HTTPException(status_code=400, detail="Geen bron-tekst om uit te citeren.")

    system = (
        "Je beantwoordt vragen over één specifieke bron (artikel, podcast, of video). "
        "Gebruik UITSLUITEND wat in de bron staat. Als het antwoord er niet in staat: "
        "zeg dat eerlijk en geef niet een gok. "
        "Antwoord in het Nederlands, beknopt (3-6 zinnen), in markdown indien dat helpt. "
        "Begin niet met 'Het antwoord is' — kom direct ter zake."
    )
    user_prompt_parts = [f"Bron: '{title}' ({item_type})"]
    if summary_block:
        user_prompt_parts.append(f"\nSamenvatting:\n{summary_block}")
    if lessons_block:
        user_prompt_parts.append(f"\nKernlessen:\n{lessons_block}")
    if body_text:
        user_prompt_parts.append(f"\nBrontekst:\n{body_text}")
    user_prompt_parts.append(f"\nVraag van de lezer:\n{q}")
    user_prompt = "\n".join(user_prompt_parts)

    try:
        answer = await _llm(request).call_llm(
            _MODEL_ALIAS[model],
            [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
            temperature=0.2, timeout=180.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}")

    return AskAnswer(
        question=q,
        answer=(answer or "").strip(),
        model=model,
        sources_used=sources_used,
    )
