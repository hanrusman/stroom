# Stroom

Personal content curation platform: YouTube / RSS / podcasts → AI summaries → Postgres+pgvector → Obsidian notes, Vikunja todos.

## Stack

| Component | Image / tool | Purpose |
|-----------|--------------|---------|
| `stroom-api` | FastAPI + SQLModel | Core API — items, sources, topics, insights, queue management |
| `stroom-web` | React + Vite | Frontend — inbox, sources, topics, player, admin |
| `stroom-db` | `pgvector/pgvector:pg16` | Source of truth — tables, embeddings, full-text search |
| `stroom-media` | `nginx:alpine` | Serves audio/video blobs |
| `stroom-rss-bridge` | `rssbridge/rss-bridge` | RSS feed generation for sources without native RSS |
| `litellm` | `ghcr.io/berriai/litellm` | OpenAI-compatible gateway to all models |
| `samenvat-agent` | Custom FastAPI | GPU worker — WhisperX transcription + summarization |
| Ollama | external | Runs `qwen3.6` + `nomic-embed-text` via llama.cpp |

## Features

- **Feed aggregation**: RSS, Atom, YouTube, podcast feeds
- **Queue-based processing**: Memory-gated workers for transcription/summarization
- **Topic classification**: ML-based categorization with user-configurable topics
- **Quality + interest scoring**: Embedding-based (local) + LLM-based (cloud) scoring
- **Insights**: LLM-generated insights from content clusters
- **Huygens**: Per-topic digest generation (async via BackgroundTasks)
- **Obsidian integration**: Direct vault writes via REST API
- **Vikunja integration**: Todo creation from insights/items
- **Audio player**: Persistent player with queue support

## Getting Started

See [PLAN.md](./PLAN.md) for the full build plan and architecture decisions.

See [TASKS.md](./TASKS.md) for implementation tasks and progress.

## Layout

```
├── docker-compose.yml          # Stack definition (in vps-stacks/stroom/)
├── litellm/
│   └── config.yaml             # Model routing aliases
├── schema/
│   ├── stroom-schema.sql       # Database schema (Postgres + pgvector)
│   └── seeds/                  # Starter data
├── media/                      # Audio/video blob storage (nginx-served)
├── api/                        # FastAPI application
│   ├── main.py                 # App entry, queue workers, memory gates
│   ├── core/                   # DB, config, auth
│   ├── models/                 # SQLModel models
│   ├── routers/                # API endpoints
│   │   ├── lessons.py          # Items, sources, topics
│   │   ├── inbox.py            # Queue management
│   │   ├── ask.py              # Chat/ask endpoints
│   │   ├── admin_topics.py     # Topic management, digest generation
│   │   ├── settings.py         # User preferences
│   │   └── transcripts.py      # Transcript retrieval
│   └── services/               # Business logic
│       ├── llm_service.py      # LiteLLM client
│       ├── quality_service.py  # Quality + interest scoring
│       ├── topics_service.py   # Topic classification
│       ├── obsidian_service.py # Vault integration
│       └── vikunja_service.py  # Todo integration
└── web/                        # React frontend
    ├── src/
    │   ├── App.tsx             # Main application
    │   ├── AdminPage.tsx       # Admin interface
    │   ├── InterestLearner.tsx # Topic interest feedback
    │   ├── StickyPlayer.tsx    # Persistent audio player
    │   └── api.ts              # API client
    └── package.json
```

## Ports

All bound to `127.0.0.1` (access via Tailscale SSH port-forwarding):

| Port | Service | Description |
|------|---------|-------------|
| `8100` | stroom-api | FastAPI backend |
| `8102` | stroom-web | React dev server / dist |
| `5433` | stroom-db | Postgres (exposed for debugging) |
| `8090` | stroom-media | Nginx media server |
| `8091` | stroom-rss-bridge | RSS-Bridge |
| `4000` | litellm | LLM proxy (via vps-stacks) |

## API Overview

### Core Endpoints

```
GET    /sources                    # List all sources
POST   /sources                    # Create new source
GET    /sources/{id}/items         # Get items for source
GET    /items                      # List items (with filters)
POST   /items/{id}/summarize      # Trigger summarization
POST   /items/{id}/transcribe     # Trigger transcription

# Inbox & Queue
GET    /inbox                     # Get inbox items
POST   /inbox/claim               # Claim next item for processing
POST   /inbox/{id}/release        # Release item back to queue

# Topics & Insights
GET    /topics                    # List topics
GET    /topics/{slug}/items       # Get items by topic
POST   /topics/{slug}/digest      # Generate topic digest (async)
GET    /topics/{slug}/digest      # Get latest digest
GET    /insights                  # List generated insights

# Admin
POST   /admin/cron/nightly         # Trigger nightly cron
GET    /admin/stats                # System stats
POST   /admin/rebuild-centroid     # Rebuild interest centroid

# Callbacks (internal)
POST   /huygens/items/{id}/transcribe-callback  # samenvat-agent callback
```

See [api.ts](./web/src/api.ts) for the full TypeScript client.

## Environment Variables

```bash
# Database
DATABASE_URL=postgresql://stroom:xxx@stroom-db:5432/stroom
ASYNC_DATABASE_URL=postgresql+asyncpg://stroom:xxx@stroom-db:5432/stroom

# LLM
LITELLM_URL=http://litellm:4000/v1/chat/completions
LITELLM_MASTER_KEY=xxx

# Auth
STROOM_INTERNAL_TOKEN=xxx  # For service-to-service callbacks

# Integrations
VIKUNJA_URL=
VIKUNJA_TOKEN=xxx
OBSIDIAN_API_KEY=xxx         # Optional — for REST API writes

# Quality Scoring
QUALITY_SCORER_MODE=embedding  # embedding (local) | cloud (via kimi)
HF_HOME=/data/hf-cache         # Persistent HuggingFace cache
```

## Development

```bash
# Start the stack (from vps-stacks/)
cd ../stroom && docker compose up -d

# Run API locally (with DB from docker)
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Run web dev server
cd web
npm install
npm run dev          # Vite dev server on :8102
```

## Key Design Decisions

See [PLAN.md](./PLAN.md) for the full rationale.

1. **Queue-based processing**: Items flow through `pending` → `processing` → `completed` states. Workers claim items with memory gates (min 2GB free RAM for transcription).

2. **Async digest generation**: Topic digests use FastAPI `BackgroundTasks` with polling pattern. UI polls every 4s until `is_generating=false`.

3. **Embedding-based scoring**: Quality + interest scoring moved from external container into `stroom-api` (2026-05-19). Uses local sentence-transformer for interest, cloud-Kimi for quality.

4. **Memory gates**: Workers refuse new items when host RAM is low. Prevents OOM on small VPS.

5. **Long transcript handling**: Transcripts >10min go to `cloud-kimi` (200K context) instead of local `stroom-bulk` (12K trimmed).

## Related Repos

- [hanrusman/samenvat-agent](https://github.com/hanrusman/samenvat-agent) — GPU transcription worker
