from typing import Literal, Optional, List
from datetime import datetime

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
    id: Optional[str] = None
    question: str
    answer: str
    model: AskModel
    sources_used: list[str]  # which fields fed the prompt: 'transcript', 'description', 'summary', 'lessons'
    created_at: Optional[str] = None


class QuestionHistoryItem(BaseModel):
    id: str
    item_id: str
    item_title: Optional[str] = None
    question: str
    answer: str
    model: Optional[str] = None
    sources_used: list[str]
    created_at: str


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

    answer_text = (answer or "").strip()

    # Save question to database
    await session.execute(sa_text("""
        INSERT INTO item_questions (item_id, user_id, question, answer, model, sources_used)
        VALUES (CAST(:iid AS uuid), CAST(:uid AS uuid), :q, :a, :m, :src)
    """), {
        "iid": item_id,
        "uid": str(user["id"]),
        "q": q,
        "a": answer_text,
        "m": model,
        "src": sources_used
    })
    await session.commit()

    return AskAnswer(
        question=q,
        answer=answer_text,
        model=model,
        sources_used=sources_used,
    )


@router.get("/huygens/items/{item_id}/questions", response_model=List[AskAnswer])
async def get_item_questions(item_id: str,
                              limit: int = Query(20, ge=1, le=100),
                              session=Depends(get_async_session),
                              user=Depends(require_user)):
    """Get question history for a specific item."""
    rows = (await session.execute(sa_text("""
        SELECT question, answer, model, sources_used, created_at
        FROM item_questions
        WHERE item_id = CAST(:iid AS uuid) AND user_id = CAST(:uid AS uuid)
        ORDER BY created_at DESC
        LIMIT :lim
    """), {"iid": item_id, "uid": str(user["id"]), "lim": limit})).all()

    return [AskAnswer(
        question=r[0],
        answer=r[1],
        model=r[2],
        sources_used=r[3] or [],
        created_at=str(r[4]) if r[4] else None
    ) for r in rows]


@router.get("/me/questions", response_model=List[QuestionHistoryItem])
async def get_user_questions(limit: int = Query(50, ge=1, le=200),
                              offset: int = Query(0, ge=0),
                              session=Depends(get_async_session),
                              user=Depends(require_user)):
    """Get all questions asked by the current user across all items."""
    rows = (await session.execute(sa_text("""
        SELECT q.id::text, q.item_id::text, i.title, q.question, q.answer, q.model, q.sources_used, q.created_at
        FROM item_questions q
        JOIN items i ON i.id = q.item_id
        WHERE q.user_id = CAST(:uid AS uuid)
        ORDER BY q.created_at DESC
        LIMIT :lim OFFSET :off
    """), {"uid": str(user["id"]), "lim": limit, "off": offset})).all()

    return [QuestionHistoryItem(
        id=r[0],
        item_id=r[1],
        item_title=r[2],
        question=r[3],
        answer=r[4],
        model=r[5],
        sources_used=r[6] or [],
        created_at=str(r[7])
    ) for r in rows]


@router.delete("/huygens/items/{item_id}/questions/{question_id}")
async def delete_question(item_id: str, question_id: str,
                          session=Depends(get_async_session),
                          user=Depends(require_user)):
    """Delete a specific question (only if owned by current user)."""
    result = await session.execute(sa_text("""
        DELETE FROM item_questions
        WHERE id = CAST(:qid AS uuid)
          AND item_id = CAST(:iid AS uuid)
          AND user_id = CAST(:uid AS uuid)
        RETURNING id
    """), {"qid": question_id, "iid": item_id, "uid": str(user.id)})
    await session.commit()

    if not result.first():
        raise HTTPException(status_code=404, detail="Question not found")
    return {"ok": True}
