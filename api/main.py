from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from typing import List, Optional, Literal
from pydantic import BaseModel
from core.db import get_async_session
from core.config import settings
from models.base import (
    Item, Insight, ItemStatus, ProcessingStatus,
    InsightCategory, Save, Todo,
    Episode, EpisodeRange, EpisodeStatus,
    Topic, ItemFormat, Source,
)
from sqlalchemy import text as sa_text
from services.llm_service import LLMService
from services.obsidian_service import ObsidianService
from services.vikunja_service import VikunjaService
from services.podcast_service import PodcastService
from sqlalchemy.orm import selectinload
import asyncio
import httpx
import os
import re
from datetime import datetime
from fastapi import Cookie
from starlette.middleware.base import BaseHTTPMiddleware
from core.auth import (
    SESSION_COOKIE, hash_password, verify_password,
    check_login_rate_limit, reset_login_rate_limit,
    create_session, delete_session, get_session_user,
    set_session_cookie, clear_session_cookie, require_user,
)

# --- Response Models ---


class InsightRead(BaseModel):
    id: str
    text: str


class StreamItem(BaseModel):
    id: str
    title: str
    summary: Optional[str]
    type: str
    status: str
    published_at: Optional[str]
    duration: Optional[int]
    insights: List[InsightRead]


class ItemDetail(BaseModel):
    id: str
    title: str
    summary: Optional[str]
    type: str
    insights: List[InsightRead]


class SaveCreate(BaseModel):
    insight_id: str
    category: InsightCategory
    note: Optional[str] = None


class SaveRead(BaseModel):
    id: str
    insight_id: str
    category: InsightCategory
    note: Optional[str]
    obsidian_synced: bool
    obsidian_path: Optional[str]


class TodoCreate(BaseModel):
    insight_id: str
    title: str


class TodoRead(BaseModel):
    id: str
    insight_id: str
    vikunja_task_id: int
    title: str
    done: bool


class EpisodeCreate(BaseModel):
    range: EpisodeRange
    title: str


class EpisodeRead(BaseModel):
    id: str
    range: EpisodeRange
    title: str
    status: EpisodeStatus
    audio_url: Optional[str]


# --- Lifespan ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=300.0)
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="Stroom API", lifespan=lifespan)

_DEFAULT_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8101",
    "http://10.100.0.252:8101",
    "https://stroom.c4w.nl",
    "http://stroom.c4w.nl",
]
_extra = [o.strip() for o in os.environ.get("STROOM_ALLOWED_ORIGINS", "").split(",") if o.strip()]
_ALLOWED_ORIGINS = list(dict.fromkeys(_DEFAULT_ORIGINS + _extra))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Auth: middleware whitelist + CSRF Origin-check ---

_PUBLIC_PATHS = {"/", "/health", "/openapi.json", "/docs", "/redoc",
                 "/auth/login", "/auth/me", "/auth/logout"}
_INTERNAL_TOKEN_PATH_SUFFIXES = ("/transcribe-callback", "/admin/cron/nightly")
INTERNAL_TOKEN = os.environ.get("STROOM_INTERNAL_TOKEN", "")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        # 1. CSRF Origin guard: accept origins in the CORS allowlist.
        # SameSite=Lax already blocks cross-site cookies; this is belt-and-suspenders.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin not in _ALLOWED_ORIGINS:
                from fastapi.responses import JSONResponse
                print(f"[csrf] rejected origin={origin!r} path={path}", flush=True)
                return JSONResponse({"detail": "Ongeldige origin"}, status_code=403)

        # 2. Path whitelist (public + auth endpoints + internal callbacks)
        if path in _PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)

        # 3. Internal-token paths (samenvat-agent callbacks)
        if any(path.endswith(s) for s in _INTERNAL_TOKEN_PATH_SUFFIXES):
            tok = request.headers.get("x-stroom-internal-token", "")
            if INTERNAL_TOKEN and tok and tok == INTERNAL_TOKEN:
                return await call_next(request)
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "internal token vereist"}, status_code=401)

        # 4. Everything else needs a session cookie
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Niet ingelogd"}, status_code=401)
        # Validate session lazily — endpoints that need user info use Depends(require_user).
        from core.db import async_session_maker
        async with async_session_maker() as session:
            user = await get_session_user(session, token)
        if not user:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Niet ingelogd"}, status_code=401)
        request.state.user = user
        return await call_next(request)


app.add_middleware(AuthMiddleware)


# --- Auth routes ---


class LoginBody(BaseModel):
    email: str
    password: str


@app.post("/auth/login")
async def auth_login(body: LoginBody, request: Request, response: Response,
                     session=Depends(get_async_session)):
    rate_key = request.client.host if request.client else "unknown"
    if not check_login_rate_limit(rate_key):
        raise HTTPException(status_code=429, detail="Te veel pogingen, probeer over 15 minuten opnieuw")

    email = (body.email or "").strip().lower()
    password = body.password or ""
    if not email or not password:
        raise HTTPException(status_code=400, detail="E-mail en wachtwoord vereist")

    r = await session.exec(sa_text(
        "SELECT id::text, email, password_hash FROM users WHERE email = :e"
    ).bindparams(e=email))
    row = r.first()
    if not row or not verify_password(password, row[2]):
        raise HTTPException(status_code=401, detail="Ongeldige inloggegevens")

    reset_login_rate_limit(rate_key)
    token, expires_at = await create_session(session, row[0])
    set_session_cookie(response, token, expires_at)
    return {"user": {"id": row[0], "email": row[1]}}


@app.post("/auth/logout")
async def auth_logout(request: Request, response: Response,
                      session=Depends(get_async_session)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await delete_session(session, token)
    clear_session_cookie(response)
    return {"ok": True}


@app.get("/auth/me")
async def auth_me(request: Request, session=Depends(get_async_session)):
    token = request.cookies.get(SESSION_COOKIE)
    user = await get_session_user(session, token)
    if not user:
        raise HTTPException(status_code=401, detail="Niet ingelogd")
    return {"user": user}


# --- Endpoints ---


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/stream", response_model=List[StreamItem])
async def get_stream(
    status: Literal["all", "new", "pinned", "later", "archived"] = "all",
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    session=Depends(get_async_session),
):
    statement = (
        select(Item)
        .where(Item.processing_status == ProcessingStatus.READY)
        .options(selectinload(Item.insights))
        .order_by(Item.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if status and status != "all":
        statement = statement.where(Item.status == status)

    results = await session.exec(statement)
    items = results.all()

    return [
        StreamItem(
            id=str(item.id),
            title=item.title,
            summary=item.summary,
            type=item.type,
            status=item.status,
            published_at=str(item.published_at) if item.published_at else None,
            duration=item.duration_seconds,
            insights=[InsightRead(id=str(i.id), text=i.text) for i in item.insights],
        )
        for item in items
    ]


@app.get("/items/{item_id}", response_model=ItemDetail)
async def get_item_detail(item_id: str, session=Depends(get_async_session)):
    item = await session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    insights_result = await session.exec(select(Insight).where(Insight.item_id == item.id))
    insights = insights_result.all()

    return ItemDetail(
        id=str(item.id),
        title=item.title,
        summary=item.summary,
        type=item.type,
        insights=[InsightRead(id=str(i.id), text=i.text) for i in insights],
    )


@app.post("/items/{item_id}/regenerate")
async def regenerate_summary(item_id: str, session=Depends(get_async_session)):
    llm = LLMService(app.state.http_client)
    item = await llm.regenerate_summary(session, item_id)
    return {"id": str(item.id), "summary": item.summary, "status": item.processing_status}


@app.post("/insights/{insight_id}/explore")
async def explore_insight(
    insight_id: str, query: str, session=Depends(get_async_session)
):
    llm = LLMService(app.state.http_client)
    generator = await llm.explore_insight(session, insight_id, query)
    return StreamingResponse(generator, media_type="text/plain")


@app.post("/saves", response_model=SaveRead)
async def create_save(save_in: SaveCreate, session=Depends(get_async_session)):
    insight = await session.get(Insight, save_in.insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    db_save = Save(insight_id=save_in.insight_id, category=save_in.category, note=save_in.note)
    session.add(db_save)
    await session.commit()
    await session.refresh(db_save)

    obsidian = ObsidianService(app.state.http_client)
    db_save = await obsidian.push_insight(session, str(db_save.id))

    return SaveRead(
        id=str(db_save.id),
        insight_id=str(db_save.insight_id),
        category=db_save.category,
        note=db_save.note,
        obsidian_synced=db_save.obsidian_synced,
        obsidian_path=db_save.obsidian_path,
    )


@app.post("/todos", response_model=TodoRead)
async def create_todo(todo_in: TodoCreate, session=Depends(get_async_session)):
    vikunja = VikunjaService(app.state.http_client)
    db_todo = await vikunja.create_task(session, todo_in.insight_id, todo_in.title)
    return TodoRead(
        id=str(db_todo.id),
        insight_id=str(db_todo.insight_id),
        vikunja_task_id=db_todo.vikunja_task_id,
        title=db_todo.title,
        done=db_todo.done,
    )


@app.post("/episodes", response_model=EpisodeRead)
async def create_episode(
    episode_in: EpisodeCreate,
    background_tasks: BackgroundTasks,
    session=Depends(get_async_session),
):
    db_episode = Episode(range=episode_in.range, title=episode_in.title)
    session.add(db_episode)
    await session.commit()
    await session.refresh(db_episode)

    podcast_svc = PodcastService(app.state.http_client)
    background_tasks.add_task(podcast_svc.generate_episode_task, str(db_episode.id))

    return EpisodeRead(
        id=str(db_episode.id),
        range=db_episode.range,
        title=db_episode.title,
        status=db_episode.status,
        audio_url=db_episode.audio_url,
    )


# --- Huygens (topic-aggregation viewer) ---


class TopicRead(BaseModel):
    slug: str
    name: str
    item_count: int


class HuygensItem(BaseModel):
    id: str
    title: str
    description: Optional[str]
    author: Optional[str]
    thumbnail_url: Optional[str]
    media_url: Optional[str]
    source_name: str
    source_image_url: Optional[str]
    published_at: Optional[str]


class HuygensRail(BaseModel):
    format: ItemFormat
    items: List[HuygensItem]


class HuygensTopic(BaseModel):
    slug: str
    name: str
    rails: List[HuygensRail]


class HuygensItemDetail(BaseModel):
    id: str
    format: ItemFormat
    title: str
    description: Optional[str]
    summary: Optional[str]
    summary_model: Optional[str]
    transcript: Optional[str]
    author: Optional[str]
    media_url: Optional[str]
    thumbnail_url: Optional[str]
    source_name: str
    source_url: str
    source_image_url: Optional[str]
    published_at: Optional[str]
    topics: List[str]
    status: ItemStatus
    processing_status: ProcessingStatus
    queue_position: Optional[int] = None
    scheduled_for: Optional[str] = None


class StatusUpdate(BaseModel):
    status: ItemStatus


@app.get("/huygens/items/{item_id}", response_model=HuygensItemDetail)
async def huygens_item(item_id: str, session=Depends(get_async_session)):
    result = await session.exec(
        sa_text(
            """
            SELECT i.id::text, i.format::text, i.title, i.description, i.summary,
                   i.summary_model,
                   i.transcript, i.author, i.media_url, i.thumbnail_url,
                   s.name, s.url, s.image_url, i.published_at,
                   COALESCE(array_agg(t.name) FILTER (WHERE t.id IS NOT NULL), '{}') AS topic_names,
                   i.status::text, i.processing_status::text, i.scheduled_for
            FROM items i
            JOIN sources s ON s.id = i.source_id
            LEFT JOIN item_topics it ON it.item_id = i.id
            LEFT JOIN topics t ON t.id = it.topic_id
            WHERE i.id = CAST(:iid AS uuid)
            GROUP BY i.id, s.name, s.url, s.image_url
            """
        ).bindparams(iid=item_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    if not row[1]:
        raise HTTPException(status_code=400, detail="Item has no format")
    queue_pos: Optional[int] = None
    if row[16] == "queued":
        qr = await session.exec(sa_text(
            """
            SELECT COUNT(*) + 1 FROM items
            WHERE processing_status = 'queued'::processing_status
              AND queued_at < (SELECT queued_at FROM items WHERE id = CAST(:i AS uuid))
            """
        ).bindparams(i=item_id))
        queue_pos = qr.first()[0]

    return HuygensItemDetail(
        id=row[0], format=ItemFormat(row[1]), title=row[2],
        description=row[3], summary=row[4], summary_model=row[5],
        transcript=row[6], author=row[7],
        media_url=row[8], thumbnail_url=row[9],
        source_name=row[10], source_url=row[11], source_image_url=row[12],
        published_at=str(row[13]) if row[13] else None,
        topics=list(row[14]),
        status=ItemStatus(row[15]),
        processing_status=ProcessingStatus(row[16]),
        queue_position=queue_pos,
        scheduled_for=str(row[17]) if row[17] else None,
    )


async def _fetch_item_row(session, item_id: str):
    r = await session.exec(sa_text(
        "SELECT title, type::text, transcript, description, media_url, processing_status::text "
        "FROM items WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    row = r.first()
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"title": row[0], "type": row[1], "transcript": row[2], "description": row[3],
            "media_url": row[4], "processing_status": row[5]}


@app.post("/huygens/items/{item_id}/status", response_model=HuygensItemDetail)
async def set_item_status(item_id: str, body: StatusUpdate, session=Depends(get_async_session)):
    await _fetch_item_row(session, item_id)
    await session.exec(sa_text(
        "UPDATE items SET status = CAST(:s AS item_status) WHERE id = CAST(:i AS uuid)"
    ).bindparams(s=body.status.value, i=item_id))
    await session.exec(sa_text(
        "INSERT INTO feed_events (item_id, event_type) "
        "VALUES (CAST(:i AS uuid), CAST(:e AS feed_event_type))"
    ).bindparams(i=item_id, e=body.status.value))
    await session.commit()
    return await huygens_item(item_id, session)


class ScheduleUpdate(BaseModel):
    scheduled_for: Optional[datetime] = None


@app.post("/huygens/items/{item_id}/schedule", response_model=HuygensItemDetail)
async def schedule_item(item_id: str, body: ScheduleUpdate, session=Depends(get_async_session)):
    """Set or clear scheduled_for. Setting a date also flips status to 'later'."""
    await _fetch_item_row(session, item_id)
    if body.scheduled_for is None:
        await session.exec(sa_text(
            "UPDATE items SET scheduled_for = NULL WHERE id = CAST(:i AS uuid)"
        ).bindparams(i=item_id))
    else:
        await session.exec(sa_text(
            "UPDATE items SET scheduled_for = :w, status = 'later'::item_status "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(w=body.scheduled_for, i=item_id))
        await session.exec(sa_text(
            "INSERT INTO feed_events (item_id, event_type) "
            "VALUES (CAST(:i AS uuid), 'later'::feed_event_type)"
        ).bindparams(i=item_id))
    await session.commit()
    return await huygens_item(item_id, session)


# --- Lessons ---


class LessonRead(BaseModel):
    id: str
    idx: int
    title: str
    body: str
    rating: Optional[int]
    rated_at: Optional[str]


class LessonRating(BaseModel):
    rating: Optional[int]  # 1, -1, or None


@app.get("/huygens/items/{item_id}/lessons", response_model=List[LessonRead])
async def list_lessons(item_id: str, session=Depends(get_async_session)):
    result = await session.exec(sa_text(
        "SELECT id::text, idx, title, body, rating, rated_at FROM lessons "
        "WHERE item_id = CAST(:i AS uuid) ORDER BY idx ASC"
    ).bindparams(i=item_id))
    rows = result.all()
    return [
        LessonRead(
            id=r[0], idx=r[1], title=r[2], body=r[3],
            rating=r[4], rated_at=str(r[5]) if r[5] else None,
        )
        for r in rows
    ]


@app.post("/lessons/{lesson_id}/rate", response_model=LessonRead)
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
        "SELECT id::text, idx, title, body, rating, rated_at FROM lessons "
        "WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=lesson_id))
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="lesson not found")
    return LessonRead(
        id=row[0], idx=row[1], title=row[2], body=row[3],
        rating=row[4], rated_at=str(row[5]) if row[5] else None,
    )


# --- Filtered list (saved / summarized / scheduled) ---


HuygensFilter = Literal["all", "saved", "summarized", "scheduled"]
HuygensWindow = Literal["all", "24h", "7d", "30d"]

_WINDOW_INTERVAL: dict[str, str] = {
    "24h": "24 hours",
    "7d":  "7 days",
    "30d": "30 days",
}


@app.get("/huygens/items", response_model=List[HuygensItem])
async def list_filtered_items(
    filter: HuygensFilter = Query("all"),
    window: HuygensWindow = Query("all"),
    topic: Optional[str] = Query(None, description="Topic slug to constrain to"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    session=Depends(get_async_session),
):
    if filter == "all" and window == "all" and not topic:
        raise HTTPException(status_code=400, detail="At least one filter required")

    clauses: list[str] = ["s.active = true"]
    params: dict = {"lim": limit, "off": offset}

    if filter == "saved":
        clauses.append("i.status = 'pinned'::item_status")
    elif filter == "summarized":
        clauses.append("i.summary IS NOT NULL AND i.summary <> ''")
    elif filter == "scheduled":
        clauses.append("i.scheduled_for IS NOT NULL")

    if window != "all":
        clauses.append(f"i.published_at >= now() - INTERVAL '{_WINDOW_INTERVAL[window]}'")

    join_topic = ""
    if topic:
        topic_row = (await session.exec(select(Topic).where(Topic.slug == topic))).first()
        if not topic_row:
            raise HTTPException(status_code=404, detail="Topic not found")
        join_topic = "JOIN item_topics it ON it.item_id = i.id"
        clauses.append("it.topic_id = :tid")
        params["tid"] = topic_row.id

    order = "i.scheduled_for ASC" if filter == "scheduled" else "COALESCE(i.published_at, i.created_at) DESC"
    sql = f"""
        SELECT DISTINCT i.id::text, i.title, i.description, i.author,
               i.thumbnail_url, i.media_url,
               s.name, s.image_url, i.published_at
        FROM items i
        JOIN sources s ON s.id = i.source_id
        {join_topic}
        WHERE {" AND ".join(clauses)}
        ORDER BY {order.replace('i.', '')}
        LIMIT :lim OFFSET :off
    """
    # SELECT DISTINCT requires order columns to be in SELECT — rewrite ordering to use selected cols
    sql = f"""
        SELECT i.id::text, i.title, i.description, i.author,
               i.thumbnail_url, i.media_url,
               s.name, s.image_url, i.published_at, i.scheduled_for
        FROM items i
        JOIN sources s ON s.id = i.source_id
        {join_topic}
        WHERE {" AND ".join(clauses)}
        GROUP BY i.id, s.name, s.image_url
        ORDER BY {order}
        LIMIT :lim OFFSET :off
    """
    result = await session.exec(sa_text(sql).bindparams(**params))
    rows = result.all()
    return [
        HuygensItem(
            id=r[0], title=r[1], description=r[2], author=r[3],
            thumbnail_url=r[4], media_url=r[5],
            source_name=r[6], source_image_url=r[7],
            published_at=str(r[8]) if r[8] else None,
        )
        for r in rows
    ]


# --- Topic digest ---


class TopicDigest(BaseModel):
    markdown: str
    item_count: int
    model: Optional[str]
    window_hours: int
    generated_at: str


DIGEST_WINDOW_HOURS = 24
DIGEST_MAX_ITEMS = 40
DIGEST_PER_ITEM_CHARS = 600


def _strip_html(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@app.get("/huygens/{slug}/digest", response_model=TopicDigest)
async def get_topic_digest(slug: str, session=Depends(get_async_session)):
    topic = (await session.exec(select(Topic).where(Topic.slug == slug))).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    row = (await session.exec(sa_text(
        "SELECT markdown, item_count, model, window_hours, generated_at "
        "FROM topic_digests WHERE topic_id = :tid"
    ).bindparams(tid=topic.id))).first()
    if not row:
        raise HTTPException(status_code=404, detail="No digest yet")
    return TopicDigest(
        markdown=row[0], item_count=row[1], model=row[2],
        window_hours=row[3], generated_at=str(row[4]),
    )


DigestModel = Literal["qwen", "sonnet", "opus"]
DIGEST_MODEL_MAP: dict[str, str] = {
    "qwen": "stroom-bulk",
    "sonnet": "stroom-sonnet",
    "opus": "stroom-deep",
}


@app.post("/huygens/{slug}/digest", response_model=TopicDigest)
async def regenerate_topic_digest(slug: str, model: DigestModel = Query("opus"),
                                  session=Depends(get_async_session)):
    topic = (await session.exec(select(Topic).where(Topic.slug == slug))).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    rows = (await session.exec(sa_text(
        f"""
        SELECT i.title, i.format::text, s.name, i.summary, i.description, i.published_at, i.media_url
        FROM items i
        JOIN item_topics it ON it.item_id = i.id
        JOIN sources s ON s.id = i.source_id
        WHERE it.topic_id = :tid
          AND i.published_at >= now() - INTERVAL '{DIGEST_WINDOW_HOURS} hours'
          AND s.active = true
        ORDER BY i.published_at DESC
        LIMIT {DIGEST_MAX_ITEMS}
        """
    ).bindparams(tid=topic.id))).all()

    if not rows:
        raise HTTPException(status_code=400, detail=f"Geen items in {topic.name} van laatste {DIGEST_WINDOW_HOURS}u")

    blocks: list[str] = []
    for title, fmt, sname, summary, desc, pub, url in rows:
        body = (summary or "").strip() or _strip_html(desc)
        if not body:
            continue
        body = body[:DIGEST_PER_ITEM_CHARS]
        when = str(pub)[:16] if pub else ""
        url_line = f"URL: {url}\n" if url else ""
        blocks.append(f"### [{fmt}] {title}\n_{sname} · {when}_\n{url_line}\n{body}")
    if not blocks:
        raise HTTPException(status_code=400, detail="Items hebben geen tekst om samen te vatten")

    corpus = "\n\n---\n\n".join(blocks)
    system_prompt = (
        "Je bent een redacteur die een persoonlijke dagsamenvatting schrijft over een specifiek thema. "
        f"De gebruiker volgt het thema '{topic.name}' en heeft geen tijd om alles te lezen. "
        "Schrijf een markdown-digest in het Nederlands met:\n"
        "1. Een korte intro (2 zinnen) over wat er vandaag opviel.\n"
        "2. Per cluster (groepeer waar logisch) een H3-kop, dan 2-4 zinnen die de gemeenschappelijke draad uitleggen. "
        "Verwijs naar bronnen met markdown-links: [Bronnaam](URL).\n"
        "3. Een '## Verder lezen' lijst (markdown bullet list) van max 5 items die individueel de moeite waard zijn — "
        "elke regel als `- [Titel](URL) — korte reden waarom (1 zin).`\n"
        "Wees scherp, geen marketingtaal. Als bronnen elkaar tegenspreken, benoem dat. "
        "Gebruik UITSLUITEND de URLs die in de bronlijst staan; verzin geen URLs."
    )
    llm_alias = DIGEST_MODEL_MAP[model]
    llm = LLMService(app.state.http_client)
    try:
        markdown = await llm.call_llm(llm_alias, [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Items van laatste {DIGEST_WINDOW_HOURS}u:\n\n{corpus}"},
        ], temperature=0.4)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}")

    markdown = markdown.strip()
    item_count = len(blocks)
    await session.exec(sa_text(
        """
        INSERT INTO topic_digests (topic_id, markdown, item_count, model, window_hours, generated_at)
        VALUES (:tid, :m, :n, :ml, :w, now())
        ON CONFLICT (topic_id) DO UPDATE SET
          markdown = EXCLUDED.markdown,
          item_count = EXCLUDED.item_count,
          model = EXCLUDED.model,
          window_hours = EXCLUDED.window_hours,
          generated_at = EXCLUDED.generated_at
        """
    ).bindparams(tid=topic.id, m=markdown, n=item_count, ml=llm_alias, w=DIGEST_WINDOW_HOURS))
    await session.commit()
    return await get_topic_digest(slug, session)


@app.post("/huygens/items/{item_id}/summarize", response_model=HuygensItemDetail)
async def summarize_item(item_id: str, session=Depends(get_async_session),
                         user=Depends(require_user)):
    item = await _fetch_item_row(session, item_id)
    transcript = (item["transcript"] or "").strip()

    # Geen transcript maar wel media_url → eerst transcriberen.
    # Samenvat-agent levert via callback zowel transcript als summary.
    if not transcript and item["media_url"]:
        cur_status = item["processing_status"]
        if cur_status in ("queued", "transcribing", "summarizing"):
            return await huygens_item(item_id, session)

        if not _check_transcribe_quota(user["id"]):
            raise HTTPException(status_code=429,
                                detail=f"Max {TRANSCRIBE_MAX_PER_HOUR} transcribes per uur bereikt.")

        # 1 actieve transcribe (single GPU). Anders → queue.
        r = await session.exec(sa_text(
            "SELECT COUNT(*) FROM items WHERE processing_status='transcribing'::processing_status"
        ))
        if r.first()[0] >= 1:
            await session.exec(sa_text(
                "UPDATE items SET processing_status='queued'::processing_status, "
                "queued_at=now(), processing_error=NULL "
                "WHERE id = CAST(:i AS uuid)"
            ).bindparams(i=item_id))
            await session.commit()
        else:
            try:
                await _start_transcribe(session, item_id, item["media_url"], item["type"])
            except Exception as exc:
                raise HTTPException(status_code=502, detail=str(exc))
        return await huygens_item(item_id, session)

    # Transcript bestaat (of geen media_url) → direct samenvatten van beschikbare tekst.
    text = transcript or (item["description"] or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Geen transcript, media_url of beschrijving om te samenvatten")

    import re
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()[:12000]

    await session.exec(sa_text(
        "UPDATE items SET processing_status='summarizing'::processing_status, processing_error=NULL "
        "WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    await session.commit()

    try:
        llm = LLMService(app.state.http_client)
        summary = await llm.call_llm("stroom-bulk", [
            {"role": "system", "content": (
                "Je bent een curator van hoogwaardige content. Vat de tekst samen in het Nederlands, "
                "zakelijk maar warm, max 3 zinnen. Geef alleen de samenvatting terug, geen inleiding."
            )},
            {"role": "user", "content": f"Titel: {item['title']}\n\nTekst: {cleaned}"},
        ], temperature=0.3)
        await session.exec(sa_text(
            "UPDATE items SET summary=:s, summary_model='stroom-bulk', summary_generated_at=now(), "
            "processing_status='ready'::processing_status WHERE id = CAST(:i AS uuid)"
        ).bindparams(s=summary.strip(), i=item_id))
        await session.commit()
    except Exception as exc:
        await session.exec(sa_text(
            "UPDATE items SET processing_status='failed'::processing_status, processing_error=:e "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(e=str(exc)[:500], i=item_id))
        await session.commit()
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}")
    return await huygens_item(item_id, session)


# In-memory per-user transcribe rate-limit (max 5 / hour).
_TRANSCRIBE_LOG: dict[str, list[float]] = {}
TRANSCRIBE_WINDOW_S = 3600
TRANSCRIBE_MAX_PER_HOUR = 50


def _check_transcribe_quota(user_id: str) -> bool:
    import time as _t
    now = _t.time()
    recent = [t for t in _TRANSCRIBE_LOG.get(user_id, []) if now - t < TRANSCRIBE_WINDOW_S]
    if len(recent) >= TRANSCRIBE_MAX_PER_HOUR:
        _TRANSCRIBE_LOG[user_id] = recent
        return False
    recent.append(now)
    _TRANSCRIBE_LOG[user_id] = recent
    return True


async def _start_transcribe(session, item_id: str, media_url: str, item_type: str) -> None:
    """Mark item as transcribing and POST to samenvat-agent. Caller commits."""
    await session.exec(sa_text(
        "UPDATE items SET processing_status='transcribing'::processing_status, "
        "processing_error=NULL WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    await session.commit()

    source_type = "podcast" if item_type == "podcast" else "general"
    try:
        r = await app.state.http_client.post(
            "http://samenvat-agent:8080/process",
            json={"url": media_url, "source_type": source_type, "model_name": "medium",
                  "stroom_item_id": item_id},
            timeout=10.0,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"samenvat-agent {r.status_code}: {r.text[:200]}")
    except Exception as exc:
        await session.exec(sa_text(
            "UPDATE items SET processing_status='failed'::processing_status, processing_error=:e "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(e=f"transcribe trigger failed: {exc}"[:500], i=item_id))
        await session.commit()
        raise


async def _process_next_queued(session) -> None:
    """If GPU is free and queue has items, kick off the next one (FIFO)."""
    r = await session.exec(sa_text(
        "SELECT COUNT(*) FROM items WHERE processing_status='transcribing'::processing_status"
    ))
    if r.first()[0] >= 1:
        return
    r = await session.exec(sa_text(
        "SELECT id::text, media_url, type::text FROM items "
        "WHERE processing_status='queued'::processing_status "
        "ORDER BY queued_at ASC LIMIT 1"
    ))
    nxt = r.first()
    if not nxt:
        return
    try:
        await _start_transcribe(session, nxt[0], nxt[1], nxt[2])
    except Exception as exc:
        print(f"[queue] kon volgend item niet starten: {exc}")


@app.post("/huygens/items/{item_id}/transcribe", response_model=HuygensItemDetail)
async def transcribe_item(item_id: str, session=Depends(get_async_session),
                          user=Depends(require_user)):
    item = await _fetch_item_row(session, item_id)
    if not item["media_url"]:
        raise HTTPException(status_code=400, detail="No media_url to transcribe")
    if (item["transcript"] or "").strip():
        raise HTTPException(status_code=409, detail="Item heeft al een transcript")

    r = await session.exec(sa_text(
        "SELECT processing_status::text FROM items WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    cur = r.first()
    if cur and cur[0] in ("queued", "transcribing"):
        raise HTTPException(status_code=409, detail=f"Dit item staat al in de queue ({cur[0]})")

    if not _check_transcribe_quota(user["id"]):
        raise HTTPException(status_code=429,
                            detail=f"Max {TRANSCRIBE_MAX_PER_HOUR} transcribes per uur bereikt.")

    # Globale concurrency: 1 actieve transcribe (single GPU). Anders → queue.
    r = await session.exec(sa_text(
        "SELECT COUNT(*) FROM items WHERE processing_status='transcribing'::processing_status"
    ))
    if r.first()[0] >= 1:
        await session.exec(sa_text(
            "UPDATE items SET processing_status='queued'::processing_status, "
            "queued_at=now(), processing_error=NULL "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(i=item_id))
        await session.commit()
        return await huygens_item(item_id, session)

    try:
        await _start_transcribe(session, item_id, item["media_url"], item["type"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return await huygens_item(item_id, session)


_LESSONS_HEADER_RE = re.compile(
    r"^##\s+(?:Kernlessen|Kernpunten|Key\s+lessons|Key\s+points|Key\s+takeaways)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_LESSON_ITEM_RE = re.compile(
    r"^\s*\d+\.\s+\*\*(?P<title>.+?)\*\*\s*[:.]?\s*(?P<body>.+?)\s*$",
    re.MULTILINE,
)


def parse_lessons(summary_text: str) -> list[tuple[str, str]]:
    """Extract (title, body) tuples from the ## Kernlessen section."""
    if not summary_text:
        return []
    m = _LESSONS_HEADER_RE.search(summary_text)
    if not m:
        return []
    section = summary_text[m.end():]
    end = re.search(r"^(##\s|---\s*$)", section, re.MULTILINE)
    if end:
        section = section[: end.start()]
    out: list[tuple[str, str]] = []
    for item in _LESSON_ITEM_RE.finditer(section):
        title = item.group("title").strip().rstrip(":").strip()
        body = item.group("body").strip()
        if title and body:
            out.append((title, body))
    return out


async def _replace_lessons(session, item_id: str, summary_text: str) -> None:
    """Idempotent: delete existing lessons, then insert parsed ones. Preserves no rating."""
    lessons = parse_lessons(summary_text)
    await session.exec(sa_text(
        "DELETE FROM lessons WHERE item_id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    for idx, (title, body) in enumerate(lessons, start=1):
        await session.exec(sa_text(
            "INSERT INTO lessons (item_id, idx, title, body) "
            "VALUES (CAST(:i AS uuid), :idx, :t, :b)"
        ).bindparams(i=item_id, idx=idx, t=title, b=body))


class TranscribeCallback(BaseModel):
    transcript: Optional[str] = None
    summary: Optional[str] = None
    error: Optional[str] = None


@app.post("/huygens/items/{item_id}/transcribe-callback", response_model=HuygensItemDetail)
async def transcribe_callback(item_id: str, body: TranscribeCallback,
                              session=Depends(get_async_session)):
    await _fetch_item_row(session, item_id)

    if body.error:
        await session.exec(sa_text(
            "UPDATE items SET processing_status='failed'::processing_status, "
            "processing_error=:e WHERE id = CAST(:i AS uuid)"
        ).bindparams(e=body.error[:500], i=item_id))
        await session.commit()
        try:
            await _process_next_queued(session)
        except Exception as exc:
            print(f"[queue] _process_next_queued faalde: {exc}")
        return await huygens_item(item_id, session)

    transcript = (body.transcript or "").strip()
    summary = (body.summary or "").strip()
    if not transcript and not summary:
        raise HTTPException(status_code=400, detail="empty callback payload")

    await session.exec(sa_text(
        """
        UPDATE items SET
          transcript = COALESCE(NULLIF(:t, ''), transcript),
          summary = COALESCE(NULLIF(:s, ''), summary),
          summary_model = CASE WHEN NULLIF(:s, '') IS NOT NULL THEN 'samenvat-agent' ELSE summary_model END,
          summary_generated_at = CASE WHEN NULLIF(:s, '') IS NOT NULL THEN now() ELSE summary_generated_at END,
          processing_status = 'ready'::processing_status,
          processing_error = NULL
        WHERE id = CAST(:i AS uuid)
        """
    ).bindparams(t=transcript, s=summary, i=item_id))
    await session.commit()

    if summary:
        try:
            await _replace_lessons(session, item_id, summary)
            await session.commit()
        except Exception as exc:
            print(f"[lessons] parse/store faalde voor {item_id}: {exc}")

    # GPU-slot is vrij — kick de volgende uit de queue (best-effort).
    try:
        await _process_next_queued(session)
    except Exception as exc:
        print(f"[queue] _process_next_queued faalde: {exc}")

    return await huygens_item(item_id, session)


# --- Admin: sources beheer ---


class AdminSource(BaseModel):
    id: str
    name: str
    url: str
    kind: str
    image_url: Optional[str]
    weight: int
    max_per_rail: Optional[int]
    active: bool
    poll_interval_min: int
    topic_slugs: List[str]
    item_count: int


class AdminSourceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    kind: Optional[str] = None
    image_url: Optional[str] = None
    weight: Optional[int] = None
    max_per_rail: Optional[int] = None
    active: Optional[bool] = None
    poll_interval_min: Optional[int] = None
    topic_slugs: Optional[List[str]] = None


class AdminSourceCreate(BaseModel):
    name: str
    url: str
    kind: str  # rss / podcast / youtube
    image_url: Optional[str] = None
    weight: int = 5
    max_per_rail: Optional[int] = None
    active: bool = True
    poll_interval_min: int = 60
    topic_slugs: List[str] = []


VALID_KINDS = {"rss", "podcast", "youtube"}


async def _admin_source_row(session, source_id: str) -> AdminSource:
    r = await session.exec(sa_text(
        """
        SELECT s.id::text, s.name, s.url, s.kind::text, s.image_url,
               s.weight, s.max_per_rail, s.active, s.poll_interval_min,
               COALESCE(array_agg(t.slug) FILTER (WHERE t.id IS NOT NULL), '{}') AS slugs,
               (SELECT COUNT(*) FROM items WHERE source_id = s.id) AS item_count
        FROM sources s
        LEFT JOIN source_topics st ON st.source_id = s.id
        LEFT JOIN topics t ON t.id = st.topic_id
        WHERE s.id = CAST(:i AS uuid)
        GROUP BY s.id
        """
    ).bindparams(i=source_id))
    row = r.first()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")
    return AdminSource(
        id=row[0], name=row[1], url=row[2], kind=row[3], image_url=row[4],
        weight=row[5], max_per_rail=row[6], active=row[7], poll_interval_min=row[8],
        topic_slugs=list(row[9]), item_count=row[10],
    )


@app.get("/admin/sources", response_model=List[AdminSource])
async def admin_list_sources(session=Depends(get_async_session),
                             user=Depends(require_user)):
    r = await session.exec(sa_text(
        """
        SELECT s.id::text, s.name, s.url, s.kind::text, s.image_url,
               s.weight, s.max_per_rail, s.active, s.poll_interval_min,
               COALESCE(array_agg(t.slug ORDER BY t.slug) FILTER (WHERE t.id IS NOT NULL), '{}') AS slugs,
               (SELECT COUNT(*) FROM items WHERE source_id = s.id) AS item_count
        FROM sources s
        LEFT JOIN source_topics st ON st.source_id = s.id
        LEFT JOIN topics t ON t.id = st.topic_id
        GROUP BY s.id
        ORDER BY s.active DESC, s.name
        """
    ))
    return [
        AdminSource(
            id=row[0], name=row[1], url=row[2], kind=row[3], image_url=row[4],
            weight=row[5], max_per_rail=row[6], active=row[7], poll_interval_min=row[8],
            topic_slugs=list(row[9]), item_count=row[10],
        )
        for row in r.all()
    ]


async def _set_source_topics(session, source_id: str, slugs: List[str]) -> None:
    await session.exec(sa_text(
        "DELETE FROM source_topics WHERE source_id = CAST(:i AS uuid)"
    ).bindparams(i=source_id))
    if not slugs:
        return
    await session.exec(sa_text(
        """
        INSERT INTO source_topics (source_id, topic_id)
        SELECT CAST(:i AS uuid), id FROM topics WHERE slug = ANY(:s)
        """
    ).bindparams(i=source_id, s=list(slugs)))


@app.patch("/admin/sources/{source_id}", response_model=AdminSource)
async def admin_update_source(source_id: str, body: AdminSourceUpdate,
                              session=Depends(get_async_session),
                              user=Depends(require_user)):
    await _admin_source_row(session, source_id)  # 404 if missing

    fields = body.model_dump(exclude_unset=True, exclude_none=False)
    topic_slugs = fields.pop("topic_slugs", None)

    if "kind" in fields and fields["kind"] not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {VALID_KINDS}")
    if "weight" in fields and fields["weight"] is not None:
        if not 1 <= fields["weight"] <= 10:
            raise HTTPException(status_code=400, detail="weight 1-10")
    if "max_per_rail" in fields and fields["max_per_rail"] is not None and fields["max_per_rail"] < 1:
        raise HTTPException(status_code=400, detail="max_per_rail moet ≥1 of null zijn")

    # Bouw dynamische UPDATE
    set_parts = []
    params: dict = {"i": source_id}
    for k, v in fields.items():
        if k == "kind":
            set_parts.append(f"{k} = CAST(:{k} AS content_kind)")
        else:
            set_parts.append(f"{k} = :{k}")
        params[k] = v
    if set_parts:
        await session.exec(sa_text(
            f"UPDATE sources SET {', '.join(set_parts)} WHERE id = CAST(:i AS uuid)"
        ).bindparams(**params))

    if topic_slugs is not None:
        await _set_source_topics(session, source_id, topic_slugs)

    await session.commit()
    return await _admin_source_row(session, source_id)


@app.post("/admin/sources", response_model=AdminSource)
async def admin_create_source(body: AdminSourceCreate,
                              session=Depends(get_async_session),
                              user=Depends(require_user)):
    if body.kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {VALID_KINDS}")
    if not 1 <= body.weight <= 10:
        raise HTTPException(status_code=400, detail="weight 1-10")
    if body.max_per_rail is not None and body.max_per_rail < 1:
        raise HTTPException(status_code=400, detail="max_per_rail moet ≥1 of null zijn")

    r = await session.exec(sa_text(
        """
        INSERT INTO sources (name, url, kind, image_url, weight, max_per_rail, active, poll_interval_min)
        VALUES (:n, :u, CAST(:k AS content_kind), :img, :w, :mpr, :a, :poll)
        RETURNING id::text
        """
    ).bindparams(n=body.name, u=body.url, k=body.kind, img=body.image_url,
                 w=body.weight, mpr=body.max_per_rail, a=body.active,
                 poll=body.poll_interval_min))
    new_id = r.first()[0]
    if body.topic_slugs:
        await _set_source_topics(session, new_id, body.topic_slugs)
    await session.commit()
    return await _admin_source_row(session, new_id)


KIND_TO_FORMAT = {"rss": "article", "podcast": "podcast", "youtube": "video"}


def _feed_first_text(entry, *keys):
    for k in keys:
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list) and v and isinstance(v[0], dict) and v[0].get("value"):
            return v[0]["value"].strip()
    return None


def _feed_media_url(entry):
    for enc in entry.get("enclosures") or []:
        if enc.get("url"):
            return enc["url"]
    if entry.get("media_content"):
        for mc in entry["media_content"]:
            if mc.get("url"):
                return mc["url"]
    return entry.get("link")


def _feed_thumb_url(entry):
    if entry.get("media_thumbnail"):
        return entry["media_thumbnail"][0].get("url")
    # Per-episode itunes:image (podcasts) of generieke image-tag.
    v = entry.get("itunes_image") or entry.get("image")
    if isinstance(v, dict):
        return v.get("href") or v.get("url")
    if isinstance(v, str):
        return v
    return None


_OG_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']', re.I),
]


async def _scrape_og_image(client: httpx.AsyncClient, url: str) -> Optional[str]:
    """Fetch URL, return og:image / twitter:image. Best-effort: returns None on any failure."""
    if not url:
        return None
    try:
        r = await client.get(
            url,
            headers={"User-Agent": "StroomBot/1.0 (+image-ingest)"},
            timeout=8.0, follow_redirects=True,
        )
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return None
        head = r.text[:200_000]
        for pat in _OG_PATTERNS:
            m = pat.search(head)
            if m:
                img = m.group(1).strip()
                if img.startswith("//"):
                    return "https:" + img
                if img.startswith("/"):
                    from urllib.parse import urljoin
                    return urljoin(url, img)
                return img
    except Exception:
        return None
    return None


async def _refresh_one(session, src) -> dict:
    """Fetch src's feed, upsert items, return {inserted, checked, error?}."""
    import feedparser
    from datetime import datetime, timezone

    feed = await asyncio.get_event_loop().run_in_executor(None, feedparser.parse, src.url)
    if feed.bozo and not feed.entries:
        err = str(getattr(feed, "bozo_exception", "unknown"))
        await session.exec(sa_text(
            "UPDATE sources SET last_polled_at = now(), last_poll_status = :st "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(st=f"error: {err[:120]}", i=str(src.id)))
        return {"inserted": 0, "checked": 0, "error": err}

    fmt = KIND_TO_FORMAT.get(src.kind, "article")
    inserted = 0
    for entry in feed.entries[:20]:
        ext_id = entry.get("id") or entry.get("link")
        if not ext_id:
            continue
        title = _feed_first_text(entry, "title") or "(untitled)"
        desc = _feed_first_text(entry, "summary", "description")
        author = _feed_first_text(entry, "author")
        published = None
        st = entry.get("published_parsed") or entry.get("updated_parsed")
        if st:
            published = datetime(*st[:6], tzinfo=timezone.utc)

        media = _feed_media_url(entry)
        thumb = _feed_thumb_url(entry)
        # Geen feed-thumbnail én een artikel-URL → og:image scrapen.
        # Skip podcasts (media_url is audio) en youtube (heeft eigen thumb pad).
        if not thumb and media and src.kind == "rss":
            thumb = await _scrape_og_image(app.state.http_client, media)

        r = await session.exec(sa_text(
            """
            INSERT INTO items
                (source_id, external_id, type, format, title, description,
                 author, media_url, thumbnail_url, published_at,
                 processing_status, status)
            VALUES (CAST(:s AS uuid), :e, CAST(:k AS content_kind), CAST(:f AS item_format),
                    :t, :d, :a, :m, :th, :p, 'ready', 'new')
            ON CONFLICT (source_id, external_id) DO NOTHING
            RETURNING id::text
            """
        ).bindparams(s=str(src.id), e=ext_id, k=src.kind, f=fmt, t=title, d=desc,
                     a=author, m=media, th=thumb, p=published))
        row = r.first()
        if not row:
            continue
        new_item_id = row[0]
        await session.exec(sa_text(
            """
            INSERT INTO item_topics (item_id, topic_id)
            SELECT CAST(:i AS uuid), st.topic_id
            FROM source_topics st WHERE st.source_id = CAST(:s AS uuid)
            """
        ).bindparams(i=new_item_id, s=str(src.id)))
        inserted += 1

    await session.exec(sa_text(
        "UPDATE sources SET last_polled_at = now(), last_poll_status = :st "
        "WHERE id = CAST(:i AS uuid)"
    ).bindparams(st=f"refreshed: {inserted} new", i=str(src.id)))
    return {"inserted": inserted, "checked": len(feed.entries[:20])}


@app.post("/admin/sources/{source_id}/refresh")
async def admin_refresh_source(source_id: str,
                               session=Depends(get_async_session),
                               user=Depends(require_user)):
    """Pull latest items from this source's feed and insert new ones."""
    src = await _admin_source_row(session, source_id)
    result = await _refresh_one(session, src)
    if "error" in result:
        await session.commit()
        raise HTTPException(status_code=502, detail=f"Feed parse error: {result['error']}")
    await session.commit()
    return {"ok": True, **result}


@app.post("/admin/sources/refresh-all")
async def admin_refresh_all(session=Depends(get_async_session),
                            user=Depends(require_user)):
    """Refresh every active source. Returns aggregate + per-source counts."""
    r = await session.exec(sa_text(
        "SELECT id, name, kind::text, url FROM sources WHERE active ORDER BY name"
    ))
    rows = r.all()
    total_inserted = 0
    total_checked = 0
    errors = 0
    per_source = []
    for row in rows:
        src = type("S", (), {"id": row[0], "name": row[1], "kind": row[2], "url": row[3]})
        try:
            res = await _refresh_one(session, src)
            await session.commit()
        except Exception as e:
            await session.rollback()
            res = {"inserted": 0, "checked": 0, "error": str(e)[:200]}
        if "error" in res:
            errors += 1
        total_inserted += res["inserted"]
        total_checked += res["checked"]
        per_source.append({"name": row[1], **res})
    return {
        "ok": True,
        "sources": len(rows),
        "errors": errors,
        "inserted": total_inserted,
        "checked": total_checked,
        "per_source": per_source,
    }


@app.post("/admin/cron/nightly")
async def admin_cron_nightly(session=Depends(get_async_session)):
    """Nightly job: refresh all sources, then queue every transcribe-able item
    from the last 48h that doesn't have a transcript yet. Auth via internal token.

    Steps:
      1. Refresh all active sources (same as admin_refresh_all).
      2. SELECT items where published_at >= now()-'2 days', no transcript,
         media_url present, not already queued/transcribing/summarizing.
      3. Mark each as queued + queued_at=now().
      4. Kick the queue (`_process_next_queued`); transcribe-callback will
         self-drain the rest.
    """
    # 1. refresh sources
    r = await session.exec(sa_text(
        "SELECT id, name, kind::text, url FROM sources WHERE active ORDER BY name"
    ))
    rows = r.all()
    refreshed = 0
    refresh_errors = 0
    inserted_total = 0
    for row in rows:
        src = type("S", (), {"id": row[0], "name": row[1], "kind": row[2], "url": row[3]})
        try:
            res = await _refresh_one(session, src)
            await session.commit()
            refreshed += 1
            inserted_total += res.get("inserted", 0)
            if "error" in res:
                refresh_errors += 1
        except Exception as exc:
            await session.rollback()
            refresh_errors += 1
            print(f"[cron] refresh {row[1]} faalde: {exc}")

    # 2. selecteer kandidaten — alleen audio/video, geen artikelen
    r = await session.exec(sa_text(
        """
        SELECT id::text FROM items
        WHERE published_at >= now() - interval '2 days'
          AND type IN ('podcast'::content_kind, 'youtube'::content_kind)
          AND (transcript IS NULL OR transcript = '')
          AND media_url IS NOT NULL AND media_url <> ''
          AND processing_status NOT IN
              ('queued'::processing_status, 'transcribing'::processing_status, 'summarizing'::processing_status)
        ORDER BY published_at DESC
        """
    ))
    candidate_ids = [row[0] for row in r.all()]

    # 3. queue them
    queued = 0
    for item_id in candidate_ids:
        await session.exec(sa_text(
            "UPDATE items SET processing_status='queued'::processing_status, "
            "queued_at=now(), processing_error=NULL "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(i=item_id))
        queued += 1
    await session.commit()

    # 4. kick the queue
    started = False
    try:
        await _process_next_queued(session)
        started = True
    except Exception as exc:
        print(f"[cron] _process_next_queued faalde: {exc}")

    return {
        "ok": True,
        "sources_refreshed": refreshed,
        "refresh_errors": refresh_errors,
        "new_items_inserted": inserted_total,
        "candidates_queued": queued,
        "queue_started": started,
    }


class QueueItem(BaseModel):
    id: str
    title: str
    source_name: str
    format: str
    processing_status: str
    queued_at: Optional[str]
    queue_position: Optional[int]


@app.get("/admin/queue", response_model=List[QueueItem])
async def admin_queue(session=Depends(get_async_session),
                      user=Depends(require_user)):
    r = await session.exec(sa_text(
        """
        SELECT i.id::text, i.title, s.name, i.format::text,
               i.processing_status::text, i.queued_at
        FROM items i
        JOIN sources s ON s.id = i.source_id
        WHERE i.processing_status IN ('transcribing','queued')
        ORDER BY
          (i.processing_status = 'transcribing') DESC,
          i.queued_at ASC NULLS LAST
        """
    ))
    rows = r.all()
    out = []
    pos = 0
    for row in rows:
        if row[4] == "queued":
            pos += 1
        out.append(QueueItem(
            id=row[0], title=row[1], source_name=row[2], format=row[3],
            processing_status=row[4],
            queued_at=str(row[5]) if row[5] else None,
            queue_position=pos if row[4] == "queued" else None,
        ))
    return out


@app.delete("/admin/sources/{source_id}")
async def admin_delete_source(source_id: str,
                              session=Depends(get_async_session),
                              user=Depends(require_user)):
    """Hard delete; cascades to items, item_topics, source_topics."""
    r = await session.exec(sa_text(
        "DELETE FROM sources WHERE id = CAST(:i AS uuid) RETURNING id"
    ).bindparams(i=source_id))
    if not r.first():
        raise HTTPException(status_code=404, detail="Source not found")
    await session.commit()
    return {"ok": True}


@app.get("/topics", response_model=List[TopicRead])
async def list_topics(session=Depends(get_async_session)):
    result = await session.exec(
        sa_text(
            """
            SELECT t.slug, t.name, COUNT(it.item_id) AS item_count
            FROM topics t
            LEFT JOIN item_topics it ON it.topic_id = t.id
            GROUP BY t.id, t.slug, t.name
            ORDER BY t.name
            """
        )
    )
    return [TopicRead(slug=r[0], name=r[1], item_count=r[2]) for r in result.all()]


@app.get("/huygens/{slug}", response_model=HuygensTopic)
async def huygens_topic(slug: str, per_rail: int = Query(20, le=50),
                         session=Depends(get_async_session)):
    topic = (await session.exec(select(Topic).where(Topic.slug == slug))).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Ranking: score = epoch(published_at) + weight * 7d
    # → weight=10 boost ~70 dagen, weight=1 ~7 dagen. Geen harde override van recency.
    # Per-source cap via ROW_NUMBER() per source × format.
    result = await session.exec(
        sa_text(
            """
            WITH ranked AS (
              SELECT i.format::text AS fmt, i.id::text AS id, i.title, i.description, i.author,
                     i.thumbnail_url, i.media_url, s.name AS sname, s.image_url AS simg,
                     i.published_at,
                     s.max_per_rail,
                     ROW_NUMBER() OVER (
                       PARTITION BY i.source_id, i.format
                       ORDER BY (EXTRACT(EPOCH FROM i.published_at) + s.weight * 604800) DESC NULLS LAST
                     ) AS rn,
                     (EXTRACT(EPOCH FROM i.published_at) + s.weight * 604800) AS score
              FROM items i
              JOIN item_topics it ON it.item_id = i.id
              JOIN sources s ON s.id = i.source_id
              WHERE it.topic_id = :tid
                AND i.format IS NOT NULL
                AND s.active = true
            )
            SELECT fmt, id, title, description, author, thumbnail_url, media_url,
                   sname, simg, published_at
            FROM ranked
            WHERE max_per_rail IS NULL OR rn <= max_per_rail
            ORDER BY score DESC NULLS LAST
            """
        ).bindparams(tid=topic.id)
    )
    rows = result.all()

    rails: dict[str, List[HuygensItem]] = {f.value: [] for f in ItemFormat}
    for fmt, iid, title, desc, author, thumb, media, sname, simg, pub in rows:
        if len(rails[fmt]) >= per_rail:
            continue
        rails[fmt].append(HuygensItem(
            id=iid, title=title, description=desc, author=author,
            thumbnail_url=thumb, media_url=media, source_name=sname,
            source_image_url=simg,
            published_at=str(pub) if pub else None,
        ))

    return HuygensTopic(
        slug=topic.slug,
        name=topic.name,
        rails=[HuygensRail(format=ItemFormat(f), items=items) for f, items in rails.items()],
    )
