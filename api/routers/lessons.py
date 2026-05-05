from datetime import datetime
from typing import List, Literal, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.auth import require_user
from core.db import async_session_maker, get_async_session
from services.llm_service import LLMService

router = APIRouter()


# ---- Models ----


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
    expansion: Optional[str] = None
    expansion_model: Optional[str] = None
    expansion_generated_at: Optional[str] = None


class LessonRating(BaseModel):
    rating: Optional[int]  # 1, -1, or None


DigestModel = Literal["qwen", "sonnet", "opus"]
DigestWindow = Literal["daily", "weekly"]
LessonsDigestFilter = Literal["useful", "not-useful", "all"]

_MODEL_ALIAS: dict[str, str] = {
    "qwen": "stroom-bulk",
    "sonnet": "stroom-sonnet",
    "opus": "stroom-deep",
}
_WINDOW_HOURS: dict[str, int] = {"daily": 24, "weekly": 168}
_FILTER_RATING: dict[str, int] = {"useful": 1, "not-useful": -1, "all": 0}
_DIGEST_GENERATION_STALE_MIN = 10
_DIGEST_MAX_LESSONS = 80


_LESSON_SELECT = (
    "SELECT l.id::text, l.idx, l.title, l.body, l.rating, l.rated_at, "
    "       l.item_id::text, i.title, s.name, i.media_url, "
    "       l.expansion, l.expansion_model, l.expansion_generated_at "
    "FROM lessons l "
    "JOIN items i ON i.id = l.item_id "
    "JOIN sources s ON s.id = i.source_id"
)


def _lesson_row(r) -> LessonRead:
    return LessonRead(
        id=r[0], idx=r[1], title=r[2], body=r[3],
        rating=r[4], rated_at=str(r[5]) if r[5] else None,
        item_id=r[6], item_title=r[7], source_name=r[8], media_url=r[9],
        expansion=r[10],
        expansion_model=r[11],
        expansion_generated_at=str(r[12]) if r[12] else None,
    )


# ---- Read endpoints ----


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


# ---- Distill more lessons ----


def _llm(request: Request) -> LLMService:
    return LLMService(request.app.state.http_client)


def _next_idx(rows: list[tuple]) -> int:
    return (max((r[1] for r in rows), default=0) + 1)


@router.post("/huygens/items/{item_id}/lessons/distill", response_model=List[LessonRead])
async def distill_more_lessons(item_id: str,
                               request: Request,
                               model: DigestModel = Query("opus"),
                               session=Depends(get_async_session),
                               user=Depends(require_user)):
    """Genereer extra kernlessen uit transcript (of summary als geen transcript). LLM mag 0 teruggeven."""
    item_row = (await session.exec(sa_text(
        "SELECT title, transcript, summary FROM items WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))).first()
    if not item_row:
        raise HTTPException(status_code=404, detail="Item not found")

    title, transcript, summary = item_row
    body_text = (transcript or "").strip() or (summary or "").strip()
    if not body_text:
        raise HTTPException(status_code=400, detail="Item heeft geen transcript of samenvatting.")

    existing = (await session.exec(sa_text(
        "SELECT idx, title, body FROM lessons WHERE item_id = CAST(:i AS uuid) ORDER BY idx ASC"
    ).bindparams(i=item_id))).all()

    existing_lines = "\n".join(f"- {r[1]}: {r[2]}" for r in existing) or "(nog geen lessen)"

    system = (
        "Je destilleert kernlessen uit een bron (podcast/artikel). "
        "Je hebt al een lijst bestaande lessen gekregen. Lever ALLEEN nieuwe, niet-redundante lessen. "
        "Als alles al gezegd is, lever een lege lijst.\n\n"
        "Output: strikt JSON, vorm: {\"lessons\": [{\"title\": \"…\", \"body\": \"…\"}]}\n"
        "- title: korte kop (4-8 woorden)\n"
        "- body: 1-3 zinnen, concreet en bruikbaar\n"
        "Maximaal 5 nieuwe lessen. Liever 0 dan dubbel."
    )
    user_prompt = (
        f"Bron: '{title}'\n\nBestaande lessen:\n{existing_lines}\n\n"
        f"Tekst:\n{body_text[:18000]}"
    )

    raw = await _llm(request).call_llm(
        _MODEL_ALIAS[model],
        [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
        temperature=0.4, response_format="json_object", timeout=240.0,
    )

    import json
    try:
        data = json.loads(raw)
        new_lessons = data.get("lessons", []) or []
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="LLM gaf geen geldig JSON terug")

    next_i = _next_idx(existing)
    inserted = 0
    for entry in new_lessons:
        t = (entry.get("title") or "").strip()
        b = (entry.get("body") or "").strip()
        if not t or not b:
            continue
        await session.exec(sa_text(
            "INSERT INTO lessons (item_id, idx, title, body) "
            "VALUES (CAST(:i AS uuid), :idx, :t, :b)"
        ).bindparams(i=item_id, idx=next_i, t=t, b=b))
        next_i += 1
        inserted += 1
    if inserted:
        await session.commit()

    result = await session.exec(sa_text(
        f"{_LESSON_SELECT} WHERE l.item_id = CAST(:i AS uuid) ORDER BY l.idx ASC"
    ).bindparams(i=item_id))
    return [_lesson_row(r) for r in result.all()]


# ---- Expand single lesson ----


@router.post("/lessons/{lesson_id}/expand", response_model=LessonRead)
async def expand_lesson(lesson_id: str,
                        request: Request,
                        model: DigestModel = Query("opus"),
                        force: bool = Query(False, description="Hergenereer ook als er al een expansion is"),
                        session=Depends(get_async_session),
                        user=Depends(require_user)):
    row = (await session.exec(sa_text(
        "SELECT l.title, l.body, l.expansion, i.title, i.transcript, i.summary "
        "FROM lessons l JOIN items i ON i.id = l.item_id "
        "WHERE l.id = CAST(:i AS uuid)"
    ).bindparams(i=lesson_id))).first()
    if not row:
        raise HTTPException(status_code=404, detail="Lesson not found")

    l_title, l_body, l_expansion, i_title, transcript, summary = row
    if l_expansion and not force:
        # Cached — gewoon teruggeven
        result = await session.exec(sa_text(
            f"{_LESSON_SELECT} WHERE l.id = CAST(:i AS uuid)"
        ).bindparams(i=lesson_id))
        return _lesson_row(result.first())

    context = (transcript or "").strip() or (summary or "").strip()
    if not context:
        raise HTTPException(status_code=400, detail="Geen brontekst om uit te diepen.")

    system = (
        "Je bent een analytische gids. Diep een specifieke kernles uit met behulp van de brontekst. "
        "Schrijf 2-4 alinea's in het Nederlands. Wees concreet: voorbeelden uit de bron, mogelijke "
        "tegenwerpingen, verbindingen met bredere concepten. Geen marketingtaal. Markdown toegestaan."
    )
    user_prompt = (
        f"Bron: '{i_title}'\n\nLes — **{l_title}**: {l_body}\n\nBrontekst (fragment):\n{context[:18000]}"
    )

    expansion = await _llm(request).call_llm(
        _MODEL_ALIAS[model],
        [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
        temperature=0.5, timeout=240.0,
    )

    await session.exec(sa_text(
        "UPDATE lessons SET expansion=:e, expansion_model=:m, expansion_generated_at=now() "
        "WHERE id = CAST(:i AS uuid)"
    ).bindparams(e=expansion.strip(), m=_MODEL_ALIAS[model], i=lesson_id))
    await session.commit()

    result = await session.exec(sa_text(
        f"{_LESSON_SELECT} WHERE l.id = CAST(:i AS uuid)"
    ).bindparams(i=lesson_id))
    return _lesson_row(result.first())


# ---- Lessons digest ----


class LessonsDigest(BaseModel):
    markdown: Optional[str]
    lesson_count: Optional[int]
    model: Optional[str]
    window_hours: int
    rating: int
    generated_at: Optional[str]
    is_generating: bool = False
    error: Optional[str] = None


def _filter_to_rating(f: str) -> int:
    return _FILTER_RATING[f]


@router.get("/lessons/digest", response_model=LessonsDigest)
async def get_lessons_digest(window: DigestWindow = Query("weekly"),
                             filter: LessonsDigestFilter = Query("useful"),
                             session=Depends(get_async_session)):
    w = _WINDOW_HOURS[window]
    r = _filter_to_rating(filter)
    row = (await session.exec(sa_text(
        "SELECT markdown, lesson_count, model, window_hours, rating, generated_at, is_generating, error "
        "FROM lessons_digests WHERE window_hours = :w AND rating = :r"
    ).bindparams(w=w, r=r))).first()
    if not row:
        raise HTTPException(status_code=404, detail="No digest yet")
    return LessonsDigest(
        markdown=row[0], lesson_count=row[1], model=row[2],
        window_hours=row[3], rating=row[4],
        generated_at=str(row[5]) if row[5] else None,
        is_generating=row[6], error=row[7],
    )


async def _run_lessons_digest_generation(window_hours: int, rating: int, model_alias: str):
    """Background-task: bouw digest uit lessen in venster (op basis van rated_at)."""
    try:
        async with async_session_maker() as bg:
            where_rating = "AND l.rating = :r" if rating in (1, -1) else ""
            params: dict = {"w_int": f"{window_hours} hours", "lim": _DIGEST_MAX_LESSONS}
            if rating in (1, -1):
                params["r"] = rating
            rows = (await bg.exec(sa_text(
                f"""
                SELECT l.title, l.body, l.rating, l.rated_at,
                       i.id::text, i.title, s.name, i.media_url
                FROM lessons l
                JOIN items i ON i.id = l.item_id
                JOIN sources s ON s.id = i.source_id
                WHERE l.rated_at >= now() - INTERVAL '{window_hours} hours'
                  {where_rating}
                ORDER BY l.rated_at DESC
                LIMIT :lim
                """
            ).bindparams(**{k: v for k, v in params.items() if k != "w_int"}))).all()

            if not rows:
                await bg.exec(sa_text(
                    "UPDATE lessons_digests SET is_generating=false, error=:e "
                    "WHERE window_hours=:w AND rating=:r"
                ).bindparams(e=f"Geen lessen in laatste {window_hours}u", w=window_hours, r=rating))
                await bg.commit()
                return

            blocks: list[str] = []
            for l_title, l_body, l_rating, l_rated, i_id, i_title, s_name, m_url in rows:
                marker = "👍" if l_rating == 1 else "👎" if l_rating == -1 else "·"
                src_link = f"[{s_name} — {i_title}]({m_url})" if m_url else f"{s_name} — {i_title}"
                blocks.append(f"- {marker} **{l_title}** — {l_body}\n  _bron: {src_link}_")

            corpus = "\n".join(blocks)
            window_label = "week" if window_hours >= 168 else "dag"
            rating_label = (
                "kernlessen die je als nuttig hebt aangemerkt" if rating == 1
                else "lessen die je als níet-nuttig hebt aangemerkt" if rating == -1
                else "alle gerate lessen"
            )

            system = (
                f"Je schrijft een persoonlijke {window_label}-digest van {rating_label}. "
                "Groepeer in 3-6 thema-clusters. Per cluster:\n"
                "- een H3-kop (`### Thema`)\n"
                "- 2-4 zinnen die de gemeenschappelijke draad uitleggen\n"
                "- verwijs naar bronnen met de markdown-links die in de input staan; verzin geen URLs.\n\n"
                "Sluit af met een `## Actiepunten` lijst (max 5 bullets) met concrete dingen om mee te doen.\n"
                "Wees scherp, geen marketingtaal."
            )
            user_prompt = f"Lessen van laatste {window_hours}u:\n\n{corpus}"

            from services.llm_service import LLMService as _LS
            client = httpx.AsyncClient(timeout=300.0)
            try:
                llm = _LS(client)
                markdown = await llm.call_llm(
                    model_alias,
                    [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
                    temperature=0.4, timeout=300.0,
                )
            finally:
                await client.aclose()

            await bg.exec(sa_text(
                "UPDATE lessons_digests SET markdown=:m, lesson_count=:n, model=:ml, "
                "generated_at=now(), is_generating=false, error=NULL "
                "WHERE window_hours=:w AND rating=:r"
            ).bindparams(m=markdown.strip(), n=len(rows), ml=model_alias, w=window_hours, r=rating))
            await bg.commit()
            print(f"[lessons-digest bg] w={window_hours} r={rating} klaar — {len(rows)} lessen", flush=True)
    except Exception as exc:
        try:
            async with async_session_maker() as bg:
                await bg.exec(sa_text(
                    "UPDATE lessons_digests SET is_generating=false, error=:e "
                    "WHERE window_hours=:w AND rating=:r"
                ).bindparams(e=str(exc)[:500], w=window_hours, r=rating))
                await bg.commit()
        except Exception:
            pass
        print(f"[lessons-digest bg] faalde: {exc}", flush=True)


@router.post("/lessons/digest", response_model=LessonsDigest)
async def regenerate_lessons_digest(background_tasks: BackgroundTasks,
                                    model: DigestModel = Query("opus"),
                                    window: DigestWindow = Query("weekly"),
                                    filter: LessonsDigestFilter = Query("useful"),
                                    session=Depends(get_async_session),
                                    user=Depends(require_user)):
    w = _WINDOW_HOURS[window]
    r = _filter_to_rating(filter)
    model_alias = _MODEL_ALIAS[model]

    existing = (await session.exec(sa_text(
        "SELECT is_generating, generation_started_at FROM lessons_digests "
        "WHERE window_hours=:w AND rating=:r"
    ).bindparams(w=w, r=r))).first()

    if existing and existing[0]:
        started = existing[1]
        if started and (datetime.now(started.tzinfo) - started).total_seconds() < _DIGEST_GENERATION_STALE_MIN * 60:
            raise HTTPException(status_code=409, detail="Genereren is al bezig — even wachten.")

    if existing:
        await session.exec(sa_text(
            "UPDATE lessons_digests SET is_generating=true, generation_started_at=now(), error=NULL "
            "WHERE window_hours=:w AND rating=:r"
        ).bindparams(w=w, r=r))
    else:
        await session.exec(sa_text(
            "INSERT INTO lessons_digests (window_hours, rating, is_generating, generation_started_at) "
            "VALUES (:w, :r, true, now())"
        ).bindparams(w=w, r=r))
    await session.commit()

    background_tasks.add_task(_run_lessons_digest_generation, w, r, model_alias)

    # Geef de huidige rij terug (markdown kan nog leeg zijn).
    row = (await session.exec(sa_text(
        "SELECT markdown, lesson_count, model, window_hours, rating, generated_at, is_generating, error "
        "FROM lessons_digests WHERE window_hours=:w AND rating=:r"
    ).bindparams(w=w, r=r))).first()
    return LessonsDigest(
        markdown=row[0], lesson_count=row[1], model=row[2],
        window_hours=row[3], rating=row[4],
        generated_at=str(row[5]) if row[5] else None,
        is_generating=row[6], error=row[7],
    )
