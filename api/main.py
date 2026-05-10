from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select
from typing import List, Optional, Literal
from pydantic import BaseModel
from core.db import get_async_session
from core.config import settings
from models.base import (
    Item, ItemStatus, ProcessingStatus,
    Topic, ItemFormat, Source,
)
from sqlalchemy import text as sa_text
from services.llm_service import LLMService
import asyncio
import httpx
import os
import re
from datetime import datetime
from starlette.middleware.base import BaseHTTPMiddleware
from core.auth import (
    SESSION_COOKIE, hash_password, verify_password,
    check_login_rate_limit, reset_login_rate_limit,
    create_session, delete_session, get_session_user,
    set_session_cookie, clear_session_cookie, require_user,
)
from routers import legacy as legacy_router
from routers import lessons as lessons_router
from routers import settings as settings_router
from routers import admin_topics as admin_topics_router
from routers import ask as ask_router
from routers import inbox as inbox_router


# --- Queue tunables ---
# Hard caps voorkomen dat cron/inbox de queue volgooit en de VPS plat trekt.
SUMMARIZE_QUEUE_MAX_DEPTH = int(os.environ.get('SUMMARIZE_QUEUE_MAX_DEPTH', 30))
TRANSCRIBE_QUEUE_MAX_DEPTH = int(os.environ.get('TRANSCRIBE_QUEUE_MAX_DEPTH', 30))
SUMMARIZE_WORKERS = int(os.environ.get('SUMMARIZE_WORKERS', 2))
LLM_HTTP_TIMEOUT_SEC = float(os.environ.get('LLM_HTTP_TIMEOUT_SEC', 60))
LLM_MAX_CONCURRENT = int(os.environ.get('LLM_MAX_CONCURRENT', 4))
WORKER_IDLE_POLL_SEC = float(os.environ.get('WORKER_IDLE_POLL_SEC', 10))
QUEUE_DEPTH_LOG_EVERY_SEC = 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Generieke client voor RSS/og:image/Vikunja/Obsidian — kort timeout.
    app.state.http_client = httpx.AsyncClient(
        timeout=30.0,
        limits=httpx.Limits(max_connections=10),
    )
    # Aparte client voor LLM-calls. Beperkte pool zodat een trage LLM
    # niet de gewone API-requests platlegt.
    app.state.llm_client = httpx.AsyncClient(
        timeout=LLM_HTTP_TIMEOUT_SEC,
        limits=httpx.Limits(max_connections=LLM_MAX_CONCURRENT),
    )

    from core.db import async_session_maker
    worker_tasks: list[asyncio.Task] = []
    for i in range(SUMMARIZE_WORKERS):
        worker_tasks.append(asyncio.create_task(_summarize_worker(i, async_session_maker)))
    worker_tasks.append(asyncio.create_task(_transcribe_worker(async_session_maker)))
    worker_tasks.append(asyncio.create_task(_queue_depth_logger(async_session_maker)))

    yield

    for t in worker_tasks:
        t.cancel()
    for t in worker_tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass
    await app.state.http_client.aclose()
    await app.state.llm_client.aclose()


app = FastAPI(title="Stroom API", lifespan=lifespan, root_path="/api")

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
_INTERNAL_TOKEN_PATH_SUFFIXES = (
    "/transcribe-callback",
    "/admin/cron/nightly",
    "/admin/cron/transcribe-podcasts",
    "/admin/cron/transcribe-videos",
    "/admin/cron/summarize-articles",
    "/admin/cron/digest-topics",
)
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

        # 3. Internal-token paths (samenvat-agent callback, cron) — accept token
        # OR fall through to session-cookie auth (admin user kicking the cron from UI).
        if any(path.endswith(s) for s in _INTERNAL_TOKEN_PATH_SUFFIXES):
            tok = request.headers.get("x-stroom-internal-token", "")
            if INTERNAL_TOKEN and tok and tok == INTERNAL_TOKEN:
                return await call_next(request)
            # geen (geldige) token → laat block 4 het proberen via session cookie

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

app.include_router(legacy_router.router)
app.include_router(lessons_router.router)
app.include_router(settings_router.router)
app.include_router(admin_topics_router.router)
app.include_router(ask_router.router)
app.include_router(inbox_router.router)


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
    format: Optional[str] = None
    status: Optional[str] = None
    processing_status: Optional[str] = None
    has_summary: bool = False
    has_transcript: bool = False
    scheduled_for: Optional[str] = None
    quality_score: Optional[int] = None


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
    transcript_segments: Optional[List[dict]] = None
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
    quality_score: Optional[int] = None


class StatusUpdate(BaseModel):
    status: ItemStatus


class SearchHit(BaseModel):
    id: str
    title: str
    format: str
    source_name: str
    published_at: Optional[str]
    snippet: str
    rank: float


@app.get("/search", response_model=List[SearchHit])
async def search_items(q: str = Query(..., min_length=2),
                       format: Optional[str] = Query(None),
                       limit: int = Query(20, le=100),
                       session=Depends(get_async_session)):
    """Postgres FTS over title+summary+transcript+description.
    `q` accepteert websearch_to_tsquery syntax: 'foo bar' (AND), 'foo OR bar', '"exact phrase"'."""
    fmt_filter = ""
    if format in ("article", "podcast", "video"):
        fmt_filter = f"AND i.format = '{format}'::item_format"

    r = await session.exec(sa_text(
        f"""
        SELECT i.id::text, i.title, i.format::text, s.name,
               i.published_at,
               ts_headline('simple',
                           coalesce(i.summary, i.description, left(i.transcript, 4000), ''),
                           websearch_to_tsquery('simple', :q),
                           'MaxFragments=2,MinWords=8,MaxWords=22,StartSel=<mark>,StopSel=</mark>') as snippet,
               ts_rank(i.search_tsv, websearch_to_tsquery('simple', :q)) as rank
        FROM items i
        JOIN sources s ON s.id = i.source_id
        WHERE i.search_tsv @@ websearch_to_tsquery('simple', :q)
          AND i.status <> 'archived'::item_status
          {fmt_filter}
        ORDER BY rank DESC, i.published_at DESC NULLS LAST
        LIMIT :lim
        """
    ).bindparams(q=q, lim=limit))
    rows = r.all()
    return [SearchHit(
        id=row[0], title=row[1], format=row[2], source_name=row[3],
        published_at=str(row[4]) if row[4] else None,
        snippet=row[5] or "",
        rank=float(row[6]),
    ) for row in rows]


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
                   i.status::text, i.processing_status::text, i.scheduled_for,
                   i.transcript_segments,
                   i.quality_score
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
        transcript=row[6], transcript_segments=row[18],
        author=row[7],
        media_url=row[8], thumbnail_url=row[9],
        source_name=row[10], source_url=row[11], source_image_url=row[12],
        published_at=str(row[13]) if row[13] else None,
        topics=list(row[14]),
        status=ItemStatus(row[15]),
        processing_status=ProcessingStatus(row[16]),
        queue_position=queue_pos,
        scheduled_for=str(row[17]) if row[17] else None,
        quality_score=row[19],
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


# --- Filtered list (saved / summarized / scheduled) ---


HuygensFilter = Literal["all", "saved", "summarized", "scheduled", "archived", "inbox"]
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
    elif filter == "archived":
        clauses.append("i.status = 'archived'::item_status")
    elif filter == "summarized":
        clauses.append("i.summary IS NOT NULL AND i.summary <> ''")
        clauses.append("i.status <> 'archived'::item_status")
    elif filter == "scheduled":
        clauses.append("i.scheduled_for IS NOT NULL")
        clauses.append("i.status <> 'archived'::item_status")
    elif filter == "inbox":
        clauses.append("s.name = 'Inbox (handmatig)'")
        clauses.append("i.status <> 'archived'::item_status")
    else:
        clauses.append("i.status <> 'archived'::item_status")

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
               s.name, s.image_url, i.published_at, i.scheduled_for,
               i.format::text, i.status::text, i.processing_status::text,
               (i.summary IS NOT NULL AND i.summary <> '') AS has_summary,
               (i.transcript IS NOT NULL AND i.transcript <> '') AS has_transcript,
               i.quality_score
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
            scheduled_for=str(r[9]) if r[9] else None,
            format=r[10], status=r[11], processing_status=r[12],
            has_summary=bool(r[13]), has_transcript=bool(r[14]),
            quality_score=r[15],
        )
        for r in rows
    ]


# --- Topic digest ---


class TopicDigest(BaseModel):
    markdown: Optional[str]
    item_count: Optional[int]
    model: Optional[str]
    window_hours: int
    generated_at: Optional[str]
    is_generating: bool = False
    error: Optional[str] = None


DigestWindow = Literal["daily", "weekly"]
DIGEST_WINDOWS: dict[str, int] = {"daily": 24, "weekly": 168}
from pipeline.digest import (
    DIGEST_MAX_ITEMS, DIGEST_PER_ITEM_CHARS, DIGEST_MODEL_MAP,
    DIGEST_GENERATION_STALE_MIN,
    strip_html as _strip_html,
    run_digest_generation as _pipeline_run_digest_generation,
)


@app.get("/huygens/{slug}/digest", response_model=TopicDigest)
async def get_topic_digest(slug: str,
                           window: DigestWindow = Query("daily"),
                           session=Depends(get_async_session)):
    topic = (await session.exec(select(Topic).where(Topic.slug == slug))).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    window_hours = DIGEST_WINDOWS[window]
    row = (await session.exec(sa_text(
        "SELECT markdown, item_count, model, window_hours, generated_at, is_generating, error "
        "FROM topic_digests WHERE topic_id = :tid AND window_hours = :w"
    ).bindparams(tid=topic.id, w=window_hours))).first()
    if not row:
        raise HTTPException(status_code=404, detail="No digest yet")
    return TopicDigest(
        markdown=row[0], item_count=row[1], model=row[2],
        window_hours=row[3],
        generated_at=str(row[4]) if row[4] else None,
        is_generating=row[5], error=row[6],
    )


DigestModel = Literal["qwen", "sonnet", "opus"]


async def _run_digest_generation(topic_id: str, topic_name: str, slug: str,
                                 model: DigestModel, window_hours: int):
    """Wrapper: pipeline-call met onze DB-session-maker en LLM-service."""
    from core.db import async_session_maker
    llm = LLMService(app.state.http_client)
    await _pipeline_run_digest_generation(topic_id, topic_name, slug, model, window_hours,
                                          async_session_maker, llm)


class TopicDigestRun(BaseModel):
    id: str
    generated_at: str
    model: Optional[str]
    item_count: Optional[int]
    markdown: str


@app.get("/huygens/{slug}/digest/history", response_model=List[TopicDigestRun])
async def get_topic_digest_history(slug: str,
                                   window: DigestWindow = Query("daily"),
                                   limit: int = Query(7, ge=1, le=30),
                                   session=Depends(get_async_session)):
    topic = (await session.exec(select(Topic).where(Topic.slug == slug))).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    rows = (await session.execute(sa_text("""
        SELECT id::text, generated_at, model, item_count, markdown
        FROM topic_digest_runs
        WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w
        ORDER BY generated_at DESC
        LIMIT :lim
    """), {"tid": str(topic.id), "w": DIGEST_WINDOWS[window], "lim": limit})).all()
    return [TopicDigestRun(
        id=r[0], generated_at=str(r[1]), model=r[2], item_count=r[3], markdown=r[4]
    ) for r in rows]


@app.get("/admin/cron/digest-status")
async def admin_cron_digest_status(window: DigestWindow = Query("daily"),
                                   session=Depends(get_async_session)):
    """Snel overzicht hoeveel digests in_progress zijn — voor de UI om voortgang te tonen."""
    w = DIGEST_WINDOWS[window]
    r = (await session.execute(sa_text("""
        SELECT
          COUNT(*) FILTER (WHERE is_generating) AS in_progress,
          COUNT(*) FILTER (WHERE NOT is_generating AND markdown IS NOT NULL AND markdown <> '') AS done,
          COUNT(*) FILTER (WHERE NOT is_generating AND error IS NOT NULL) AS failed
        FROM topic_digests WHERE window_hours = :w
    """), {"w": w})).first()
    return {"window": window, "in_progress": r[0], "done": r[1], "failed": r[2]}


@app.post("/huygens/{slug}/digest", response_model=TopicDigest)
async def regenerate_topic_digest(slug: str, background_tasks: BackgroundTasks,
                                  model: DigestModel = Query("opus"),
                                  window: DigestWindow = Query("daily"),
                                  session=Depends(get_async_session)):
    topic = (await session.exec(select(Topic).where(Topic.slug == slug))).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    # Capture als plain values vóór commit/close — anders triggert lazy-load na sessie-sluit.
    topic_id = str(topic.id)
    topic_name = topic.name
    window_hours = DIGEST_WINDOWS[window]

    existing = (await session.exec(sa_text(
        "SELECT is_generating, generation_started_at FROM topic_digests "
        "WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w"
    ).bindparams(tid=topic_id, w=window_hours))).first()

    # Check of er een actieve generatie bezig is of in de wachtrij staat:
    # - is_generating=true EN generation_started_at=NULL → in wachtrij
    # - is_generating=true EN generation_started_at < 30 min geleden → actief bezig
    if existing and existing[0]:
        started = existing[1]
        if started is None:
            raise HTTPException(status_code=409, detail="Staat in de wachtrij — even wachten.")
        if (datetime.now(started.tzinfo) - started).total_seconds() < DIGEST_GENERATION_STALE_MIN * 60:
            raise HTTPException(status_code=409, detail="Genereren is al bezig — even wachten.")

    # generation_started_at wordt pas gezet wanneer de task daadwerkelijk begint (in de worker)
    if existing:
        await session.exec(sa_text(
            "UPDATE topic_digests SET is_generating=true, generation_started_at=NULL, "
            "queued_at=now(), error=NULL "
            "WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w"
        ).bindparams(tid=topic_id, w=window_hours))
    else:
        await session.exec(sa_text(
            "INSERT INTO topic_digests (topic_id, window_hours, is_generating, generation_started_at, queued_at) "
            "VALUES (CAST(:tid AS uuid), :w, true, NULL, now())"
        ).bindparams(tid=topic_id, w=window_hours))
    await session.commit()

    background_tasks.add_task(_run_digest_generation, topic_id, topic_name, slug, model, window_hours)
    return await get_topic_digest(slug, window, session)


@app.post("/huygens/items/{item_id}/summarize", response_model=HuygensItemDetail)
async def summarize_item(item_id: str, session=Depends(get_async_session),
                         user=Depends(require_user)):
    item = await _fetch_item_row(session, item_id)
    transcript = (item["transcript"] or "").strip()

    # Geen transcript maar wel media_url én een audio/video item → eerst transcriberen.
    # Samenvat-agent levert via callback zowel transcript als summary.
    # Voor articles is media_url de artikel-URL zelf, dus skip die path.
    if not transcript and item["media_url"] and item["type"] in ("podcast", "youtube"):
        cur_status = item["processing_status"]
        if cur_status in ("queued", "transcribe_queued", "transcribing", "summarizing"):
            return await huygens_item(item_id, session)

        if not _check_transcribe_quota(user["id"]):
            raise HTTPException(status_code=429,
                                detail=f"Max {TRANSCRIBE_MAX_PER_HOUR} transcribes per uur bereikt.")

        # Altijd queueen; worker pakt op binnen WORKER_IDLE_POLL_SEC.
        # Voorkomt race tussen user-trigger en background worker.
        await session.exec(sa_text(
            "UPDATE items SET processing_status='transcribe_queued'::processing_status, "
            "queued_at=now(), processing_error=NULL "
            "WHERE id = CAST(:i AS uuid)"
        ).bindparams(i=item_id))
        await session.commit()
        return await huygens_item(item_id, session)

    # Transcript bestaat (of geen media_url) → direct samenvatten van beschikbare tekst.
    text = transcript or (item["description"] or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Geen transcript, media_url of beschrijving om te samenvatten")

    import re
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()[:12000]

    await session.exec(sa_text(
        "UPDATE items SET processing_status='summarizing'::processing_status, queued_at=now(), processing_error=NULL "
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


async def _claim_next_summarize(session) -> Optional[str]:
    """Atomair één summarize_queued item claimen.

    Gebruikt FOR UPDATE SKIP LOCKED zodat meerdere workers nooit hetzelfde
    item pakken en geen worker geblokkeerd raakt op een rij die een ander
    al heeft gepakt. Returnt het id::text of None als de queue leeg is.
    """
    r = await session.exec(sa_text("""
        UPDATE items SET
          processing_status = 'summarizing'::processing_status,
          processing_error = NULL
        WHERE id = (
            SELECT id FROM items
            WHERE processing_status = 'summarize_queued'::processing_status
            ORDER BY queued_at ASC NULLS LAST
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id::text
    """))
    row = r.first()
    await session.commit()
    return row[0] if row else None


async def _claim_next_transcribe(session) -> Optional[tuple[str, str, str]]:
    """Atomair één transcribe_queued item claimen — single GPU.

    Geeft (item_id, media_url, type) of None.
    Caller is verantwoordelijk voor het posten naar samenvat-agent.
    """
    # Eerst checken of de GPU al bezet is (slechts 1 transcribing tegelijk).
    r = await session.exec(sa_text(
        "SELECT COUNT(*) FROM items WHERE processing_status='transcribing'::processing_status"
    ))
    if r.first()[0] >= 1:
        return None
    r = await session.exec(sa_text("""
        UPDATE items SET
          processing_status = 'transcribing'::processing_status,
          processing_error = NULL
        WHERE id = (
            SELECT id FROM items
            WHERE processing_status = 'transcribe_queued'::processing_status
            ORDER BY queued_at ASC NULLS LAST
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id::text, media_url, type::text
    """))
    row = r.first()
    await session.commit()
    if not row:
        return None
    return (row[0], row[1], row[2])


async def _summarize_worker(idx: int, async_session_maker) -> None:
    """Continu draaiende worker: claim → process → repeat.

    `SUMMARIZE_WORKERS` instances draaien parallel. Concurrency op LLM
    is daarmee per definitie begrensd op N. Geen losse `create_task`
    per item — als de pool vol zit, wacht de queue gewoon.
    """
    print(f"[sum-worker-{idx}] started", flush=True)
    llm = LLMService(app.state.llm_client)
    while True:
        try:
            async with async_session_maker() as s:
                item_id = await _claim_next_summarize(s)
            if not item_id:
                await asyncio.sleep(WORKER_IDLE_POLL_SEC)
                continue
            await _summarize_single_item(item_id, llm, async_session_maker)
        except asyncio.CancelledError:
            print(f"[sum-worker-{idx}] shutting down", flush=True)
            return
        except Exception as exc:
            print(f"[sum-worker-{idx}] error: {exc}", flush=True)
            await asyncio.sleep(5)


async def _transcribe_worker(async_session_maker) -> None:
    """Single worker voor de transcribe-queue (single GPU)."""
    print("[trans-worker] started", flush=True)
    while True:
        try:
            async with async_session_maker() as s:
                claim = await _claim_next_transcribe(s)
            if not claim:
                await asyncio.sleep(WORKER_IDLE_POLL_SEC)
                continue
            item_id, media_url, item_type = claim
            try:
                source_type = "podcast" if item_type == "podcast" else "general"
                r = await app.state.http_client.post(
                    "http://samenvat-agent:8080/process",
                    json={"url": media_url, "source_type": source_type,
                          "model_name": "medium", "stroom_item_id": item_id},
                    timeout=10.0,
                )
                if r.status_code >= 400:
                    raise RuntimeError(f"samenvat-agent {r.status_code}: {r.text[:200]}")
            except Exception as exc:
                async with async_session_maker() as bg:
                    await bg.exec(sa_text(
                        "UPDATE items SET processing_status='failed'::processing_status, "
                        "processing_error=:e WHERE id = CAST(:i AS uuid)"
                    ).bindparams(e=f"transcribe trigger failed: {exc}"[:500], i=item_id))
                    await bg.commit()
                print(f"[trans-worker] kon transcribe niet starten voor {item_id}: {exc}",
                      flush=True)
        except asyncio.CancelledError:
            print("[trans-worker] shutting down", flush=True)
            return
        except Exception as exc:
            print(f"[trans-worker] error: {exc}", flush=True)
            await asyncio.sleep(5)


async def _queue_depth_logger(async_session_maker) -> None:
    """Logt elke ~60s queue-diepte. Hiermee zie je vastlopers vroeg."""
    while True:
        try:
            await asyncio.sleep(QUEUE_DEPTH_LOG_EVERY_SEC)
            async with async_session_maker() as s:
                r = await s.exec(sa_text("""
                    SELECT processing_status::text, COUNT(*) FROM items
                    WHERE processing_status IN (
                        'transcribe_queued','transcribing',
                        'summarize_queued','summarizing'
                    )
                    GROUP BY processing_status
                """))
                depth = {row[0]: row[1] for row in r.all()}
            if depth:
                print(f"[queue-depth] {depth}", flush=True)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            print(f"[queue-depth] error: {exc}", flush=True)


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
    if cur and cur[0] in ("queued", "transcribe_queued", "transcribing"):
        raise HTTPException(status_code=409, detail=f"Dit item staat al in de queue ({cur[0]})")

    if not _check_transcribe_quota(user["id"]):
        raise HTTPException(status_code=429,
                            detail=f"Max {TRANSCRIBE_MAX_PER_HOUR} transcribes per uur bereikt.")

    # Altijd queueen; transcribe-worker pakt op binnen WORKER_IDLE_POLL_SEC.
    await session.exec(sa_text(
        "UPDATE items SET processing_status='transcribe_queued'::processing_status, "
        "queued_at=now(), processing_error=NULL "
        "WHERE id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    await session.commit()
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
    transcript_segments: Optional[List[dict]] = None
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
        # Worker pakt de volgende vanzelf op binnen WORKER_IDLE_POLL_SEC.
        return await huygens_item(item_id, session)

    transcript = (body.transcript or "").strip()
    summary = (body.summary or "").strip()
    if not transcript and not summary:
        raise HTTPException(status_code=400, detail="empty callback payload")

    import json as _json
    segments_json: Optional[str] = None
    if body.transcript_segments:
        segments_json = _json.dumps(body.transcript_segments)

    # Determine next status: ready if summary present, else queue for summarization
    next_status = 'ready' if summary else 'summarize_queued'

    await session.exec(sa_text(
        """
        UPDATE items SET
          transcript = COALESCE(NULLIF(:t, ''), transcript),
          transcript_segments = COALESCE(CAST(:segs AS jsonb), transcript_segments),
          summary = COALESCE(NULLIF(:s, ''), summary),
          summary_model = CASE WHEN NULLIF(:s, '') IS NOT NULL THEN 'samenvat-agent' ELSE summary_model END,
          summary_generated_at = CASE WHEN NULLIF(:s, '') IS NOT NULL THEN now() ELSE summary_generated_at END,
          processing_status = CAST(:ns AS processing_status),
          processing_error = NULL
        WHERE id = CAST(:i AS uuid)
        """
    ).bindparams(t=transcript, segs=segments_json, s=summary, ns=next_status, i=item_id))
    await session.commit()

    if summary:
        try:
            await _replace_lessons(session, item_id, summary)
            await session.commit()
        except Exception as exc:
            print(f"[lessons] parse/store faalde voor {item_id}: {exc}")

    # Workers (transcribe + summarize) pakken vanzelf de volgende items.
    return await huygens_item(item_id, session)


# --- Item Topics ---

class AddItemTopicRequest(BaseModel):
    topic_slug: str


@app.post("/huygens/items/{item_id}/topics", response_model=HuygensItemDetail)
async def add_item_topic(item_id: str, body: AddItemTopicRequest,
                         session=Depends(get_async_session),
                         user=Depends(require_user)):
    """Add an item to a topic."""
    # Verify item exists
    item = await _fetch_item_row(session, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Get topic
    topic_row = (await session.exec(sa_text(
        "SELECT id FROM topics WHERE slug = :slug"
    ).bindparams(slug=body.topic_slug))).first()
    if not topic_row:
        raise HTTPException(status_code=404, detail=f"Topic '{body.topic_slug}' not found")
    topic_id = topic_row[0]

    # Add to topic (ignore if already exists)
    await session.exec(sa_text(
        "INSERT INTO item_topics (item_id, topic_id) VALUES (CAST(:iid AS uuid), :tid) ON CONFLICT DO NOTHING"
    ).bindparams(iid=item_id, tid=topic_id))
    await session.commit()

    return await huygens_item(item_id, session)


@app.delete("/huygens/items/{item_id}/topics/{topic_slug}", response_model=HuygensItemDetail)
async def remove_item_topic(item_id: str, topic_slug: str,
                            session=Depends(get_async_session),
                            user=Depends(require_user)):
    """Remove an item from a topic."""
    # Verify item exists
    item = await _fetch_item_row(session, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Get topic
    topic_row = (await session.exec(sa_text(
        "SELECT id FROM topics WHERE slug = :slug"
    ).bindparams(slug=topic_slug))).first()
    if not topic_row:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_slug}' not found")
    topic_id = topic_row[0]

    # Remove from topic
    await session.exec(sa_text(
        "DELETE FROM item_topics WHERE item_id = CAST(:iid AS uuid) AND topic_id = :tid"
    ).bindparams(iid=item_id, tid=topic_id))
    await session.commit()

    return await huygens_item(item_id, session)


# --- User: quality score feedback ---

class QualityScoreUpdate(BaseModel):
    quality_score: Optional[int] = None  # 1-10 or null for neutral


@app.patch("/huygens/items/{item_id}/quality-score", response_model=HuygensItemDetail)
async def update_item_quality_score(
    item_id: str,
    update: QualityScoreUpdate,
    session=Depends(get_async_session),
    user=Depends(require_user),
):
    """Update the quality score of an item (user feedback).

    Allows users to correct the auto-generated quality score.
    Set to null to remove the score (neutral).
    """
    # Verify item exists
    item = await _fetch_item_row(session, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Validate score range if provided
    if update.quality_score is not None:
        if not (1 <= update.quality_score <= 10):
            raise HTTPException(status_code=400, detail="Quality score must be between 1 and 10")

    # Update the score
    await session.exec(sa_text(
        "UPDATE items SET quality_score = :score WHERE id = CAST(:id AS uuid)"
    ).bindparams(score=update.quality_score, id=item_id))
    await session.commit()

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
    # Skip image-enclosures: veel RSS-feeds hangen featured images aan als enclosure.
    # Die horen in thumbnail_url, niet in media_url (die wordt als 'open original' link gebruikt).
    for enc in entry.get("enclosures") or []:
        if not enc.get("url"):
            continue
        t = (enc.get("type") or "").lower()
        if t.startswith("image/"):
            continue
        return enc["url"]
    if entry.get("media_content"):
        for mc in entry["media_content"]:
            if not mc.get("url"):
                continue
            t = (mc.get("type") or "").lower()
            if t.startswith("image/"):
                continue
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


from pipeline.articles import (
    extract_article_body as _extract_article_body,
    backfill_articles as _pipeline_backfill_articles,
)


_INBOX_SOURCE_NAME = "Inbox (handmatig)"


async def _summarize_single_item(item_id: str, llm_service, async_session_maker) -> bool:
    """Summarize a single item (article/podcast/video with transcript).

    Voor items uit de Inbox-bron wordt na summarize ook lesson-distill
    gedraaid (binnen dezelfde worker — telt mee voor concurrency-budget).
    """
    try:
        async with async_session_maker() as bg:
            r = await bg.exec(sa_text("""
                SELECT i.title, i.transcript, i.description, i.type::text, s.name
                FROM items i JOIN sources s ON s.id = i.source_id
                WHERE i.id = CAST(:i AS uuid)
            """).bindparams(i=item_id))
            row = r.first()
            if not row:
                return False
            title = row[0]
            raw = (row[1] or "").strip() or re.sub(r"<[^>]+>", " ", row[2] or "").strip()
            article_body = (row[1] or "").strip()
            source_name = row[4]
            if not raw:
                await bg.exec(sa_text(
                    "UPDATE items SET processing_status='ready'::processing_status, queued_at=NULL "
                    "WHERE id = CAST(:i AS uuid)"
                ).bindparams(i=item_id))
                await bg.commit()
                return True

        cleaned = re.sub(r"\s+", " ", raw)[:12000]
        response = await llm_service.call_llm("stroom-bulk", [
            {"role": "system", "content": (
                "Je bent een curator van hoogwaardige content. Vat het artikel samen in het "
                "Nederlands, zakelijk maar warm, max 3 zinnen.\n\n"
                "Beoordeel ook de kwaliteit (1-10) op:\n"
                "- Nieuwswaarde: is dit echt nieuw of oud nieuws?\n"
                "- Diepgang: gaat het verder dan het oppervlakte?\n"
                "- Originaliteit: uniek perspectief of standaard bericht?\n\n"
                "Output strikt als JSON: {\"summary\": \"...\", \"quality_score\": 7}"
            )},
            {"role": "user", "content": f"Titel: {title}\n\nTekst: {cleaned}"},
        ], temperature=0.3, response_format="json_object")

        import json as _json
        try:
            data = _json.loads(response)
            summary = data.get("summary", "").strip()
            quality_score = data.get("quality_score")
            if quality_score is not None:
                quality_score = max(1, min(10, int(quality_score)))
        except Exception:
            summary = response.strip() if response else ""
            quality_score = None

        async with async_session_maker() as bg:
            await bg.exec(sa_text(
                "UPDATE items SET summary=:s, summary_model='stroom-bulk', "
                "summary_generated_at=now(), processing_status='ready'::processing_status, "
                "quality_score=:q, queued_at=NULL WHERE id = CAST(:i AS uuid)"
            ).bindparams(s=summary, i=item_id, q=quality_score))
            await bg.commit()

        # Inbox-items krijgen ook lesson-distill (was het oude inbox-gedrag).
        # Best-effort: faalt distill, dan blijft summary nog steeds geldig.
        if source_name == _INBOX_SOURCE_NAME and article_body:
            try:
                await _distill_lessons_for_item(item_id, summary, article_body,
                                                llm_service, async_session_maker)
            except Exception as exc:
                print(f"[sum-worker] distill faalde voor {item_id}: {exc}", flush=True)

        return True
    except Exception as exc:
        try:
            async with async_session_maker() as bg:
                await bg.exec(sa_text(
                    "UPDATE items SET processing_status='failed'::processing_status, "
                    "processing_error=:e, queued_at=NULL WHERE id = CAST(:i AS uuid)"
                ).bindparams(e=f"summarize: {exc}"[:500], i=item_id))
                await bg.commit()
        except Exception:
            pass
        return False


async def _distill_lessons_for_item(item_id: str, summary: str, article_body: str,
                                     llm_service, async_session_maker) -> int:
    """Genereer kernlessen via LLM en sla ze op. Returnt aantal inserted."""
    body_text = article_body.strip()[:18000]
    if not body_text:
        return 0
    system = (
        "Je destilleert kernlessen uit een bron (artikel). "
        "Lever concrete, bruikbare lessen die de kern van het artikel vangen.\n\n"
        "Output: strikt JSON, vorm: {\"lessons\": [{\"title\": \"…\", \"body\": \"…\"}]}\n"
        "- title: korte kop (4-8 woorden)\n"
        "- body: 1-3 zinnen, concreet en bruikbaar\n"
        "Maximaal 5 lessen. Liever 0 dan oppervlakkig."
    )
    raw = await llm_service.call_llm(
        "stroom-bulk",
        [{"role": "system", "content": system},
         {"role": "user", "content": f"Samenvatting: {summary}\n\nArtikel tekst:\n{body_text}"}],
        temperature=0.4, response_format="json_object",
    )
    import json as _json
    try:
        data = _json.loads(raw)
        new_lessons = data.get("lessons", []) or []
    except _json.JSONDecodeError:
        return 0

    inserted = 0
    async with async_session_maker() as bg:
        for idx, entry in enumerate(new_lessons, start=1):
            t = (entry.get("title") or "").strip()
            b = (entry.get("body") or "").strip()
            if not t or not b:
                continue
            await bg.exec(sa_text(
                "INSERT INTO lessons (item_id, idx, title, body) "
                "VALUES (CAST(:i AS uuid), :idx, :t, :b)"
            ).bindparams(i=item_id, idx=idx, t=t, b=b))
            inserted += 1
        if inserted:
            await bg.commit()
    return inserted


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

        # Voor articles: full body via trafilatura, opslaan in transcript.
        # Best-effort: bij failure blijft description de fallback.
        if fmt == "article" and media:
            body = await _extract_article_body(app.state.http_client, media)
            if body:
                await session.exec(sa_text(
                    "UPDATE items SET transcript = :t WHERE id = CAST(:i AS uuid)"
                ).bindparams(t=body, i=new_item_id))

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


REFRESH_THUMB_BACKFILL_LIMIT = 100


async def _backfill_missing_thumbnails(session, limit: int) -> int:
    """Scrape og:image voor RSS-items die nog geen thumbnail hebben. Returns count gevuld."""
    rows = (await session.exec(sa_text(
        """
        SELECT i.id::text, i.media_url
        FROM items i
        WHERE i.thumbnail_url IS NULL
          AND i.media_url IS NOT NULL
          AND i.type = 'rss'::content_kind
        ORDER BY i.published_at DESC NULLS LAST
        LIMIT :lim
        """
    ).bindparams(lim=limit))).all()
    filled = 0
    for iid, url in rows:
        img = await _scrape_og_image(app.state.http_client, url)
        if img:
            await session.exec(sa_text(
                "UPDATE items SET thumbnail_url=:t WHERE id = CAST(:i AS uuid)"
            ).bindparams(t=img, i=iid))
            filled += 1
    if filled:
        await session.commit()
    return filled


async def _bg_backfill_thumbnails(limit: int):
    """Achter de response: nieuwe DB-sessie, scrape, commit. Best-effort, logged."""
    from core.db import async_session_maker
    try:
        async with async_session_maker() as bg_session:
            n = await _backfill_missing_thumbnails(bg_session, limit)
            print(f"[refresh-all bg] {n} thumbnails gevuld")
    except Exception as exc:
        print(f"[refresh-all bg] thumbnail backfill faalde: {exc}")


@app.post("/admin/sources/refresh-all")
async def admin_refresh_all(background_tasks: BackgroundTasks,
                            session=Depends(get_async_session),
                            user=Depends(require_user)):
    """Refresh every active source. Schedules thumbnail-backfill als achtergrondtaak."""
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

    background_tasks.add_task(_bg_backfill_thumbnails, REFRESH_THUMB_BACKFILL_LIMIT)

    return {
        "ok": True,
        "sources": len(rows),
        "errors": errors,
        "inserted": total_inserted,
        "checked": total_checked,
        "thumbnails_scheduled": REFRESH_THUMB_BACKFILL_LIMIT,
        "per_source": per_source,
    }


CRON_WEIGHT_MIN = 5
CRON_MAX_TRANSCRIBE_ATTEMPTS = 3
CRON_SKIP_ATTEMPTS = 99  # sentinel: items met deze waarde worden nooit meer geprobeerd
CRON_STUCK_MIN = 30  # items in queued/transcribing/summarizing > N min → reset to failed
CRON_NIGHTLY_HOURS = 24  # nightly kijkt 24u terug (niet meer)


async def _cron_unstuck(session) -> int:
    """Reset items that have been stuck in queues/processing too long."""
    # Reset items stuck in processing queues
    r = await session.exec(sa_text(f"""
        UPDATE items SET
          processing_status = 'failed'::processing_status,
          processing_error = 'stuck > {CRON_STUCK_MIN} min — auto-reset by cron'
        WHERE processing_status IN
              ('queued'::processing_status, 'transcribe_queued'::processing_status,
               'summarize_queued'::processing_status, 'transcribing'::processing_status,
               'summarizing'::processing_status)
          AND queued_at IS NOT NULL
          AND queued_at < now() - interval '{CRON_STUCK_MIN} minutes'
        RETURNING id
    """))
    n = len(r.all())

    # Reset topic digests stuck in queue (worker crasht voordat generatie begint)
    # Dit kan gebeuren als de API herstart terwijl een digest in de wachtrij staat
    r2 = await session.exec(sa_text("""
        UPDATE topic_digests SET is_generating=false, error='wachtrij timeout — worker crashed?'
        WHERE is_generating=true AND generation_started_at IS NULL
          AND queued_at < now() - interval '4 hours'
    """))
    n += len(r2.all())

    # Reset lessons digests stuck in queue
    r3 = await session.exec(sa_text("""
        UPDATE lessons_digests SET is_generating=false, error='wachtrij timeout — worker crashed?'
        WHERE is_generating=true AND generation_started_at IS NULL
          AND queued_at < now() - interval '4 hours'
    """))
    n += len(r3.all())

    await session.commit()
    return n


async def _cron_queue_transcribes(session, *, content_kind: str,
                                  hours: Optional[int] = None,
                                  weight_min: int = CRON_WEIGHT_MIN,
                                  limit: Optional[int] = None) -> int:
    """Mark items as queued for transcription (A2 GPU). Increments transcribe_attempts.

    `content_kind`: 'podcast' or 'youtube'.
    `hours`: only items published in last N hours, or None for all-time backlog.

    Hard cap: nooit meer dan TRANSCRIBE_QUEUE_MAX_DEPTH items totaal in
    de pipeline (queued + transcribing). Bij volle queue: 0.
    """
    r = await session.exec(sa_text(
        "SELECT COUNT(*) FROM items WHERE processing_status IN "
        "('transcribe_queued'::processing_status, 'transcribing'::processing_status)"
    ))
    in_flight = r.first()[0] or 0
    available = max(0, TRANSCRIBE_QUEUE_MAX_DEPTH - in_flight)
    if available == 0:
        print(f"[cron] transcribe-queue vol ({in_flight}/{TRANSCRIBE_QUEUE_MAX_DEPTH}), "
              f"niets gequeued voor {content_kind}", flush=True)
        return 0
    effective_limit = min(limit, available) if limit else available

    where_age = "AND i.published_at >= now() - (:hrs * interval '1 hour')" if hours is not None else ""
    sql = """
        WITH picks AS (
          SELECT i.id
          FROM items i
          JOIN sources s ON s.id = i.source_id
          WHERE i.type = CAST(:kind AS content_kind)
            AND s.weight >= :wmin
            AND s.active
            AND (i.transcript IS NULL OR i.transcript = '')
            AND i.media_url IS NOT NULL AND i.media_url <> ''
            AND i.processing_status NOT IN
                ('transcribe_queued'::processing_status, 'transcribing'::processing_status,
                 'queued'::processing_status, 'summarizing'::processing_status)
            AND i.transcribe_attempts < :max_att
            """ + where_age + """
          ORDER BY s.weight DESC, i.published_at DESC
          LIMIT :lim
        )
        UPDATE items SET
          processing_status = 'transcribe_queued'::processing_status,
          queued_at = now(),
          processing_error = NULL,
          transcribe_attempts = transcribe_attempts + 1
        WHERE id IN (SELECT id FROM picks)
        RETURNING id
    """
    params: dict = {"kind": content_kind, "wmin": weight_min,
                    "max_att": CRON_MAX_TRANSCRIBE_ATTEMPTS, "lim": effective_limit}
    if hours is not None:
        params["hrs"] = hours
    r = await session.exec(sa_text(sql).bindparams(**params))
    n = len(r.all())
    await session.commit()
    return n


async def _cron_pick_articles_for_summary(session, *,
                                          hours: Optional[int] = None,
                                          weight_min: int = CRON_WEIGHT_MIN,
                                          limit: int = 200) -> list[str]:
    """Pick articles needing summary, pre-mark als 'summarize_queued'.

    Workers (zie _summarize_worker) draineren de queue. Cron flipt alleen
    statussen — geen background-task spawn.

    Hard cap: nooit meer dan SUMMARIZE_QUEUE_MAX_DEPTH items totaal in
    de pipeline (queued + summarizing). Bij volle queue: lege list.
    """
    r = await session.exec(sa_text(
        "SELECT COUNT(*) FROM items WHERE processing_status IN "
        "('summarize_queued'::processing_status, 'summarizing'::processing_status)"
    ))
    in_flight = r.first()[0] or 0
    available = max(0, SUMMARIZE_QUEUE_MAX_DEPTH - in_flight)
    if available == 0:
        print(f"[cron] summarize-queue vol ({in_flight}/{SUMMARIZE_QUEUE_MAX_DEPTH}), "
              f"niets gequeued", flush=True)
        return []
    effective_limit = min(limit, available)

    where_age = "AND i.published_at >= now() - (:hrs * interval '1 hour')" if hours is not None else ""
    sql = """
        WITH picks AS (
          SELECT i.id
          FROM items i
          JOIN sources s ON s.id = i.source_id
          WHERE i.format = 'article'::item_format
            AND s.weight >= :wmin
            AND s.active
            AND COALESCE(NULLIF(i.transcript, ''), NULLIF(i.description, '')) IS NOT NULL
            AND length(COALESCE(NULLIF(i.transcript, ''), NULLIF(i.description, ''))) >= 200
            AND (i.summary IS NULL OR i.summary = '')
            AND i.processing_status NOT IN
                ('summarize_queued'::processing_status, 'summarizing'::processing_status,
                 'queued'::processing_status, 'transcribing'::processing_status)
            """ + where_age + """
          ORDER BY s.weight DESC, i.published_at DESC
          LIMIT :lim
        )
        UPDATE items SET
          processing_status = 'summarize_queued'::processing_status,
          queued_at = now(),
          processing_error = NULL
        WHERE id IN (SELECT id FROM picks)
        RETURNING id::text
    """
    params: dict = {"wmin": weight_min, "lim": effective_limit}
    if hours is not None:
        params["hrs"] = hours
    r = await session.exec(sa_text(sql).bindparams(**params))
    ids = [row[0] for row in r.all()]
    await session.commit()
    return ids


async def _cron_kick_topic_digests(session, *, model: "DigestModel" = "opus",
                                   window: str = "daily") -> int:
    """For every topic, mark its daily digest as is_generating and kick a bg task.

    Note: generation_started_at wordt pas gezet wanneer de task daadwerkelijk
    begint (binnen de semaphore), niet hier. Dit voorkomt false-positive stale
    detectie wanneer veel topics in de wachtrij staan."""
    window_hours = DIGEST_WINDOWS[window]
    rows = (await session.exec(sa_text(
        "SELECT id::text, slug, name FROM topics ORDER BY sort_order, name"
    ))).all()
    started = 0
    for tid, slug, name in rows:
        existing = (await session.exec(sa_text(
            "SELECT is_generating, generation_started_at FROM topic_digests "
            "WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w"
        ).bindparams(tid=tid, w=window_hours))).first()
        # Skip als er al een digest bezig is of in de wachtrij staat:
        # - is_generating=true EN generation_started_at=NULL → in wachtrij, skip
        # - is_generating=true EN generation_started_at < 30 min geleden → actief bezig, skip
        # - is_generating=true EN generation_started_at > 30 min geleden → echte stale, mag opnieuw
        if existing and existing[0]:
            started = existing[1]
            if started is None:
                continue  # In wachtrij, andere worker pakt 'm
            if (datetime.now(started.tzinfo) - started).total_seconds() < DIGEST_GENERATION_STALE_MIN * 60:
                continue  # Actief bezig
        if existing:
            # is_generating=true zetten, maar generation_started_at pas in de worker
            await session.exec(sa_text(
                "UPDATE topic_digests SET is_generating=true, generation_started_at=NULL, "
                "queued_at=now(), error=NULL "
                "WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w"
            ).bindparams(tid=tid, w=window_hours))
        else:
            # Insert zonder generation_started_at - die komt pas in de worker
            await session.exec(sa_text(
                "INSERT INTO topic_digests (topic_id, window_hours, is_generating, generation_started_at, queued_at) "
                "VALUES (CAST(:tid AS uuid), :w, true, NULL, now())"
            ).bindparams(tid=tid, w=window_hours))
        await session.commit()
        asyncio.create_task(_run_digest_generation(tid, name, slug, model, window_hours))
        started += 1
    return started


@app.post("/admin/cron/nightly")
async def admin_cron_nightly(session=Depends(get_async_session)):
    """Nightly job: reset stuck → refresh sources → queue items.

    Cron flipt alleen statussen naar *_queued. De worker pool draineert
    de queues vanzelf (bounded door SUMMARIZE_WORKERS + hard cap op
    queue-depth). Geen background-task spawn meer hier.

    Auth: internal token or admin session cookie.
    """
    unstuck = await _cron_unstuck(session)

    # Refresh sources
    rows = (await session.exec(sa_text(
        "SELECT id, name, kind::text, url FROM sources WHERE active ORDER BY name"
    ))).all()
    refreshed = 0; refresh_errors = 0; inserted_total = 0
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

    podcasts_queued = await _cron_queue_transcribes(session, content_kind="podcast", hours=CRON_NIGHTLY_HOURS)
    videos_queued = await _cron_queue_transcribes(session, content_kind="youtube", hours=CRON_NIGHTLY_HOURS)
    article_ids = await _cron_pick_articles_for_summary(session, hours=CRON_NIGHTLY_HOURS)

    from routers.settings import _load as _load_settings
    digest_default = (await _load_settings(session)).digest
    digests_started = await _cron_kick_topic_digests(session, model=digest_default, window="daily")

    return {
        "ok": True,
        "stuck_reset": unstuck,
        "sources_refreshed": refreshed,
        "refresh_errors": refresh_errors,
        "new_items_inserted": inserted_total,
        "podcasts_queued": podcasts_queued,
        "videos_queued": videos_queued,
        "articles_summarize_kicked": len(article_ids),
        "digests_started": digests_started,
    }


@app.post("/admin/cron/transcribe-podcasts")
async def admin_cron_transcribe_podcasts(hours: int = Query(24, ge=1, le=720),
                                         session=Depends(get_async_session)):
    await _cron_unstuck(session)
    n = await _cron_queue_transcribes(session, content_kind="podcast", hours=hours)
    return {"ok": True, "queued": n, "hours": hours}


@app.post("/admin/cron/transcribe-videos")
async def admin_cron_transcribe_videos(hours: int = Query(24, ge=1, le=720),
                                       session=Depends(get_async_session)):
    await _cron_unstuck(session)
    n = await _cron_queue_transcribes(session, content_kind="youtube", hours=hours)
    return {"ok": True, "queued": n, "hours": hours}


@app.post("/admin/cron/summarize-articles")
async def admin_cron_summarize_articles(hours: int = Query(24, ge=1, le=720),
                                        session=Depends(get_async_session)):
    await _cron_unstuck(session)
    article_ids = await _cron_pick_articles_for_summary(session, hours=hours)
    return {"ok": True, "articles_kicked": len(article_ids), "hours": hours}


@app.delete("/admin/queue/{item_id}")
async def admin_queue_remove(item_id: str, session=Depends(get_async_session),
                             user=Depends(require_user)):
    """Haal een item uit de queue: reset processing_status naar 'ready'."""
    r = await session.exec(sa_text(
        "UPDATE items SET processing_status='ready'::processing_status, queued_at=NULL, "
        "processing_error='handmatig uit queue gehaald' "
        "WHERE id = CAST(:i AS uuid) "
        "AND processing_status IN ('queued'::processing_status, 'transcribe_queued'::processing_status, "
        "'summarize_queued'::processing_status, 'transcribing'::processing_status, 'summarizing'::processing_status) "
        "RETURNING id"
    ).bindparams(i=item_id))
    found = bool(r.first())
    await session.commit()
    if not found:
        raise HTTPException(status_code=404, detail="Item niet in queue")
    return {"ok": True, "id": item_id}


@app.post("/admin/queue/restart")
async def admin_queue_restart(session=Depends(get_async_session), user=Depends(require_user)):
    """Onstuck-pas. Workers pakken vanzelf de volgende items op."""
    unstuck = await _cron_unstuck(session)
    return {"ok": True, "stuck_reset": unstuck}


@app.post("/admin/cron/digest-topics")
async def admin_cron_digest_topics(window: DigestWindow = Query("daily"),
                                   model: DigestModel = Query("opus"),
                                   session=Depends(get_async_session)):
    started = await _cron_kick_topic_digests(session, model=model, window=window)
    return {"ok": True, "digests_started": started, "window": window, "model": model}


@app.post("/admin/articles/backfill")
async def admin_articles_backfill(background_tasks: BackgroundTasks,
                                  days: int = Query(14, le=90),
                                  limit: int = Query(500, le=2000),
                                  user=Depends(require_user)):
    """Trigger background trafilatura-extractie voor articles zonder transcript."""
    from core.db import async_session_maker
    background_tasks.add_task(_pipeline_backfill_articles,
                              app.state.http_client, async_session_maker, days, limit)
    return {"ok": True, "started": True, "days": days, "limit": limit}


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
        WHERE i.processing_status IN (
            'transcribe_queued', 'transcribing',
            'summarize_queued', 'summarizing'
        )
        ORDER BY
          CASE i.processing_status::text
            WHEN 'transcribing' THEN 1
            WHEN 'summarizing' THEN 2
            WHEN 'transcribe_queued' THEN 3
            WHEN 'summarize_queued' THEN 4
            ELSE 5
          END,
          i.queued_at ASC NULLS LAST
        """
    ))
    rows = r.all()
    out = []
    pos = 0
    for row in rows:
        if row[4] in ("transcribe_queued", "summarize_queued"):
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


class BulkArchiveRequest(BaseModel):
    topic_slugs: List[str]
    older_than_days: int
    weight_max: int = 10
    formats: List[str]  # article, podcast, video, short


class BulkArchiveResponse(BaseModel):
    archived: int


@app.post("/admin/items/bulk-archive", response_model=BulkArchiveResponse)
async def admin_bulk_archive(body: BulkArchiveRequest,
                              session=Depends(get_async_session),
                              user=Depends(require_user)):
    """Archiveer items in bulk op basis van filters (topic, datum, weight, format)."""
    if not body.topic_slugs:
        raise HTTPException(status_code=400, detail="Minstens 1 topic vereist")
    if not body.formats:
        raise HTTPException(status_code=400, detail="Minstens 1 format vereist")
    if body.older_than_days < 1:
        raise HTTPException(status_code=400, detail="older_than_days moet >= 1 zijn")

    # Format values als literals voor SQL
    format_literals = ", ".join([f"'{f}'::item_format" for f in body.formats])
    topic_literals = ", ".join([f"'{s}'" for s in body.topic_slugs])

    result = await session.exec(sa_text(f"""
        UPDATE items i
        SET status = 'archived'::item_status
        FROM sources s
        JOIN source_topics st ON st.source_id = s.id
        JOIN topics t ON t.id = st.topic_id
        WHERE i.source_id = s.id
          AND t.slug IN ({topic_literals})
          AND i.format IN ({format_literals})
          AND i.status != 'archived'::item_status
          AND i.created_at < now() - interval '{body.older_than_days} days'
          AND s.weight <= {body.weight_max}
        RETURNING i.id
    """))
    archived_ids = result.all()
    await session.commit()
    return BulkArchiveResponse(archived=len(archived_ids))


@app.get("/topics", response_model=List[TopicRead])
async def list_topics(session=Depends(get_async_session)):
    result = await session.exec(
        sa_text(
            """
            SELECT t.slug, t.name, COUNT(it.item_id) AS item_count
            FROM topics t
            LEFT JOIN item_topics it ON it.topic_id = t.id
            GROUP BY t.id, t.slug, t.name, t.sort_order
            ORDER BY t.sort_order, t.name
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
                     i.published_at, i.scheduled_for,
                     i.status::text AS istatus, i.processing_status::text AS pstatus,
                     (i.summary IS NOT NULL AND i.summary <> '') AS has_summary,
                     (i.transcript IS NOT NULL AND i.transcript <> '') AS has_transcript,
                     i.quality_score,
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
                AND i.status <> 'archived'::item_status
            )
            SELECT fmt, id, title, description, author, thumbnail_url, media_url,
                   sname, simg, published_at, scheduled_for,
                   istatus, pstatus, has_summary, has_transcript, quality_score
            FROM ranked
            WHERE max_per_rail IS NULL OR rn <= max_per_rail
            ORDER BY score DESC NULLS LAST
"""
        ).bindparams(tid=topic.id)
    )
    rows = result.all()

    rails: dict[str, List[HuygensItem]] = {f.value: [] for f in ItemFormat}
    for (fmt, iid, title, desc, author, thumb, media, sname, simg, pub, sched,
         istatus, pstatus, has_summary, has_transcript, quality_score) in rows:
        if len(rails[fmt]) >= per_rail:
            continue
        rails[fmt].append(HuygensItem(
            id=iid, title=title, description=desc, author=author,
            thumbnail_url=thumb, media_url=media, source_name=sname,
            source_image_url=simg,
            published_at=str(pub) if pub else None,
            scheduled_for=str(sched) if sched else None,
            format=fmt, status=istatus, processing_status=pstatus,
            has_summary=bool(has_summary), has_transcript=bool(has_transcript),
            quality_score=quality_score,
        ))

    return HuygensTopic(
        slug=topic.slug,
        name=topic.name,
        rails=[HuygensRail(format=ItemFormat(f), items=items) for f, items in rails.items()],
    )
