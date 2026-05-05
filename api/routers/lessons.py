from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.db import get_async_session
from core.auth import require_user

router = APIRouter()


class LessonRead(BaseModel):
    id: str
    idx: int
    title: str
    body: str
    rating: Optional[int]
    rated_at: Optional[str]
    item_id: str
    item_title: str
    source_name: str
    media_url: Optional[str]


class LessonRating(BaseModel):
    rating: Optional[int]  # 1, -1, or None


_LESSON_SELECT = (
    "SELECT l.id::text, l.idx, l.title, l.body, l.rating, l.rated_at, "
    "       l.item_id::text, i.title, s.name, i.media_url "
    "FROM lessons l "
    "JOIN items i ON i.id = l.item_id "
    "JOIN sources s ON s.id = i.source_id"
)


def _lesson_row(r) -> LessonRead:
    return LessonRead(
        id=r[0], idx=r[1], title=r[2], body=r[3],
        rating=r[4], rated_at=str(r[5]) if r[5] else None,
        item_id=r[6], item_title=r[7], source_name=r[8], media_url=r[9],
    )


@router.get("/huygens/items/{item_id}/lessons", response_model=List[LessonRead])
async def list_lessons(item_id: str, session=Depends(get_async_session)):
    result = await session.exec(sa_text(
        f"{_LESSON_SELECT} WHERE l.item_id = CAST(:i AS uuid) ORDER BY l.idx ASC"
    ).bindparams(i=item_id))
    return [_lesson_row(r) for r in result.all()]


@router.get("/lessons", response_model=List[LessonRead])
async def list_all_lessons(rating: Optional[int] = Query(None, description="Filter op rating: 1, -1, of leeg voor alles"),
                           limit: int = Query(200, le=1000),
                           session=Depends(get_async_session),
                           user=Depends(require_user)):
    """Cross-item lessons-overzicht. Default: alleen +1 (nuttig)."""
    where = ""
    params: dict = {"lim": limit}
    if rating in (1, -1):
        where = "WHERE l.rating = :r"
        params["r"] = rating
    elif rating is None:
        where = "WHERE l.rating = 1"
    result = await session.exec(sa_text(
        f"{_LESSON_SELECT} {where} ORDER BY l.rated_at DESC NULLS LAST, l.idx ASC LIMIT :lim"
    ).bindparams(**params))
    return [_lesson_row(r) for r in result.all()]


@router.post("/lessons/{lesson_id}/rate", response_model=LessonRead)
async def rate_lesson(lesson_id: str, body: LessonRating, session=Depends(get_async_session)):
    if body.rating not in (None, 1, -1):
        raise HTTPException(status_code=400, detail="rating must be 1, -1, or null")
    if body.rating is None:
        await session.exec(sa_text(
            "UPDATE lessons SET rating = NULL, rated_at = NULL WHERE id = CAST(:i AS uuid)"
        ).bindparams(i=lesson_id))
    else:
        await session.exec(sa_text(
            "UPDATE lessons SET rating = :r, rated_at = now() WHERE id = CAST(:i AS uuid)"
        ).bindparams(r=body.rating, i=lesson_id))
    await session.commit()
    result = await session.exec(sa_text(
        f"{_LESSON_SELECT} WHERE l.id = CAST(:i AS uuid)"
    ).bindparams(i=lesson_id))
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="lesson not found")
    return _lesson_row(row)
