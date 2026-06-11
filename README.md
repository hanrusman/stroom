# Stroom

A personal content-curation platform. RSS, YouTube, and podcasts come in;
AI-summarized, topic-classified items come out, queryable in Postgres+pgvector
and pushable to Obsidian and Vikunja.

The name is the Dutch word for *stream* — the continuous flow of content
coming in.

> **Status:** personal-use software. Single-user auth, single deploy target.
> Useful as a reference for building a similar tool — not a turnkey SaaS.
> See [SECURITY.md](./SECURITY.md) for what you need to change before
> exposing it anywhere beyond `localhost`.

## What it does

- **Aggregates** RSS, Atom, YouTube and podcast feeds on a schedule.
- **Transcribes** audio/video items via an external WhisperX service.
- **Summarizes** items via a configurable mix of local (Ollama) and cloud
  (Anthropic, Gemini) models, routed through a LiteLLM proxy.
- **Classifies** items into user-configured topics (ML + keywords).
- **Scores** items on quality and personal interest using local embeddings
  and an LLM judge.
- **Digests** items per topic into a daily/weekly summary.
- **Exports** insights to an Obsidian vault and tasks to Vikunja.

## Architecture

| Component | Image / tool | Purpose |
|-----------|--------------|---------|
| `stroom-api` | FastAPI + SQLModel | Core API — items, sources, topics, queue, scoring |
| `stroom-web` | React + Vite | Inbox, sources, topics, audio player, admin |
| `stroom-db` | `pgvector/pgvector:pg16` | Source of truth — tables, embeddings, full-text search |
| `stroom-media` | `nginx:alpine` | Static-serves audio/video blobs |
| `stroom-rss-bridge` | `rssbridge/rss-bridge` | Generates RSS for sources without a native feed |
| `litellm` | `ghcr.io/berriai/litellm` | OpenAI-compatible gateway to local + cloud models |
| `transcribe-agent` | sibling service | WhisperX wrapper for podcast/video transcription |
| Ollama | external (host) | Local model runtime — referenced via `OLLAMA_BASE_URL` |

The API is the source of truth. The web client is a thin React UI. The
transcribe-agent is a separate service you provide (any HTTP service that
accepts `POST /process` with `{url, source_type, model_name,
stroom_item_id}` and POSTs back to `/huygens/items/{id}/transcribe-callback`).

## Getting started

You'll need: Docker, an Ollama install with `qwen3.6` and `nomic-embed-text`
pulled (or equivalent models), and API keys for whichever cloud providers you
want to enable.

```bash
# Clone
git clone https://github.com/hanrusman/stroom.git
cd stroom

# Configure
cp .env.example .env
# edit .env: set STROOM_DB_PASSWORD, LITELLM_MASTER_KEY,
# STROOM_INTERNAL_TOKEN, and any API keys you want

# Apply schema (assumes a running Postgres reachable via DATABASE_URL)
psql "$DATABASE_URL" < schema/stroom-schema.sql

# Seed a login user (one-off, see schema/seeds/006-create-user.py for usage)

# Run the API
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8100

# Run the web client (in another terminal)
cd web
npm install
npm run dev  # Vite dev server on :8102
```

A `docker-compose.yml` is not shipped in this repo — you wire the services
together to match your environment. See [`.env.example`](./.env.example) for
the variables the API expects.

## Layout

```
├── .env.example                # Required environment variables
├── litellm/
│   └── config.yaml             # LiteLLM model aliases (stroom-bulk, etc.)
├── schema/
│   ├── stroom-schema.sql       # Postgres schema (pgvector, FTS, enums)
│   ├── migrations/             # Forward-only schema migrations
│   └── seeds/                  # Topics, initial sources, login user
├── media/                      # Audio/video blob storage (nginx-served)
├── api/                        # FastAPI service
│   ├── main.py                 # App entry, middleware, queue workers
│   ├── core/                   # Auth, DB, config
│   ├── models/                 # SQLModel models
│   ├── routers/                # API endpoints (lessons, inbox, ask, …)
│   └── services/               # LLM, scoring, Obsidian, Vikunja
└── web/                        # React + Vite client
    ├── src/
    │   ├── App.tsx
    │   ├── AdminPage.tsx
    │   ├── api.ts              # TypeScript API client
    │   └── …
    └── package.json
```

## Configuration

All configuration is via environment variables. See [`.env.example`](./.env.example)
for the full list. The minimum you need to set:

| Variable | Why |
|----------|-----|
| `STROOM_DB_PASSWORD` | Postgres password for the `stroom` user. |
| `DATABASE_URL`, `ASYNC_DATABASE_URL` | Connection strings for the API. |
| `LITELLM_MASTER_KEY` | Auth for the LiteLLM proxy. |
| `STROOM_INTERNAL_TOKEN` | Shared secret for machine-to-machine endpoints. |
| `STROOM_ALLOWED_ORIGINS` | Comma-separated extra CORS origins. |
| `OLLAMA_BASE_URL` | Where the LiteLLM proxy can reach Ollama. |

For local AI calls you'll also want one or more of `ANTHROPIC_API_KEY`,
`GEMINI_API_KEY`, and whichever model aliases you wire into `litellm/config.yaml`.

## Key design decisions

1. **Queue with memory gates.** Items flow `pending → processing → ready`.
   Workers refuse to claim new work if the host has less RAM available than
   `TRANSCRIBE_MIN_FREE_MB` / `SUMMARIZE_MIN_FREE_MB`. Avoids OOM on small
   VPSes where Whisper-medium and the baseline together blow the RAM ceiling.

2. **Async digests via BackgroundTasks.** Topic and lessons digests don't
   block the request — the API kicks off a task, the UI polls until
   `is_generating=false`. Simple, no Redis required.

3. **Local-first scoring.** Personal-interest scoring uses a local
   sentence-transformer + a centroid you maintain. Quality scoring is
   pluggable: a local embedding heuristic or a cloud LLM judge.

4. **Long transcripts route to long-context.** Transcripts over ~10 min
   skip the bulk model and go to a long-context cloud model so the whole
   thing fits in one prompt.

5. **No multi-tenant, no public sign-up.** Single user, password-hashed
   with scrypt, session cookies with `HttpOnly + SameSite=Lax + Secure`.
   CSRF protection via Origin check plus the SameSite cookie. If you want to
   share Stroom with friends, see [SECURITY.md](./SECURITY.md) for what to
   harden first.

## Security

See [SECURITY.md](./SECURITY.md). The short version: scrypt passwords,
session cookies, CSRF Origin check, parameterized SQL, sanitized markdown
rendering via DOMPurify with an explicit tag/attribute allowlist, an SSRF
guard on server-side URL fetches, and http(s)-only validation on feed-supplied
link targets in the UI. See SECURITY.md for remaining known limitations.

## License

[MIT](./LICENSE).
