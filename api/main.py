"""Stroom API — app-factory.

Alle endpoint-logica leeft in routers/, achtergrondwerk in workers/,
gedeelde logica in services/ en pipeline/. Zie docs/verbeterplan-2026-07.md
(R1) voor de indeling.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.logging import setup_logging
from core.middleware import AuthMiddleware
from routers import admin_cron as admin_cron_router
from routers import admin_quality as admin_quality_router
from routers import admin_sources as admin_sources_router
from routers import admin_topics as admin_topics_router
from routers import ask as ask_router
from routers import auth as auth_router
from routers import digests as digests_router
from routers import huygens as huygens_router
from routers import inbox as inbox_router
from routers import legacy as legacy_router
from routers import lessons as lessons_router
from routers import search as search_router
from routers import settings as settings_router
from routers import transcripts as transcripts_router
from workers.registry import start_workers, stop_workers

setup_logging()


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
        timeout=settings.LLM_HTTP_TIMEOUT_SEC,
        limits=httpx.Limits(max_connections=settings.LLM_MAX_CONCURRENT),
    )

    # Quality scoring: quality via cloud-Kimi (LLM-call), interest via lokaal
    # embedding-model + centroid uit /data.
    # Topics/persons CRUD: direct op /data/topics_config.json.
    from services.quality_service import QualityService
    from services.topics_service import TopicsService
    app.state.quality_service = QualityService()
    app.state.topics_service = TopicsService(Path("/data/topics_config.json"))
    if settings.QUALITY_EMBEDDING_ENABLED:
        try:
            await asyncio.to_thread(app.state.quality_service.load)
        except Exception as e:
            print(f"[lifespan] QualityService.load() faalde, scoring werkt degraded: {e}",
                  flush=True)
    else:
        print("[lifespan] QualityService.load() overgeslagen "
              "(QUALITY_EMBEDDING_ENABLED=false) — interest-score geeft None terug",
              flush=True)

    app.state.worker_tasks = await start_workers(app)

    yield

    await stop_workers(app.state.worker_tasks)
    await app.state.http_client.aclose()
    await app.state.llm_client.aclose()


def create_app() -> FastAPI:
    # OpenAPI docs zijn handig in dev maar lekken endpoint-structuur in productie.
    # Default: dicht. Zet STROOM_ENABLE_DOCS=1 om ze aan te zetten.
    app = FastAPI(
        title="Stroom API",
        lifespan=lifespan,
        root_path="/api",
        docs_url="/docs" if settings.STROOM_ENABLE_DOCS else None,
        redoc_url="/redoc" if settings.STROOM_ENABLE_DOCS else None,
        openapi_url="/openapi.json" if settings.STROOM_ENABLE_DOCS else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuthMiddleware)

    # Volgorde: specifieke paden vóór de catch-all /huygens/{slug} in huygens.
    for mod in (auth_router, search_router, huygens_router, digests_router,
                admin_sources_router, admin_cron_router, admin_quality_router,
                legacy_router, lessons_router, settings_router,
                admin_topics_router, ask_router, inbox_router, transcripts_router):
        app.include_router(mod.router)

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    return app


app = create_app()
