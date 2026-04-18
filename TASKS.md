# Stroom · Fase 0 + 1 tasks

You are setting up **infrastructure (Fase 0)** and the **database schema (Fase 1)** for Stroom. Scope is tight: bring the Docker stack up, load the schema, insert seeds, and verify. **Do not** touch `api/`, `web/`, or write application code. **Do not** modify `schema/stroom-schema.sql` or `docker-compose.yml` — if something looks wrong, stop and report.

## What you are building

1. 3 Docker services: Postgres (pgvector), LiteLLM proxy, nginx for media.
2. Database schema: 3 extensions, 8 tables, 3 views.
3. Seed rows in `sources`.

Working directory: `/Users/hanrusman/Code/stroom/` on **strongbad** (the Coloclue VPS). Use Tailscale SSH to get there.

## Pre-flight checks

```bash
# Docker installed & running
docker version

# You are in the project root
cd /Users/hanrusman/Code/stroom && pwd && ls

# Ollama reachable (the URL your .env OLLAMA_BASE_URL will point at)
curl -s http://host.docker.internal:11434/api/tags | head

# Both required Ollama models exist
ollama list | grep -E "qwen3\.6|nomic-embed-text"
# If nomic-embed-text is missing:
ollama pull nomic-embed-text
```

If Docker isn't running or Ollama isn't reachable: **stop. Report back.** Don't improvise.

## Fase 0 — infrastructure

### 0.1 Create `.env`

```bash
cp .env.example .env
```

Fill in these five values (leave the others blank for now — they are for later phases):

- `STROOM_DB_PASSWORD` — `openssl rand -base64 32`
- `LITELLM_MASTER_KEY` — `openssl rand -base64 32`
- `ANTHROPIC_API_KEY` — ask the user
- `GEMINI_API_KEY` — ask the user
- `OLLAMA_BASE_URL` — confirm with the user (likely `http://host.docker.internal:11434`)

### 0.2 Bring up the stack

```bash
docker compose up -d
```

Wait ~90 seconds for all healthchecks to settle, then:

```bash
docker compose ps
```

All 3 services must be `healthy`. If any is not, run `docker compose logs <service>` and report back. **Do not edit docker-compose.yml on your own.**

### 0.3 Verify services

Load env vars first: `set -a && . .env && set +a`

```bash
# Postgres: auth works, server is Postgres 16
psql "postgresql://stroom:${STROOM_DB_PASSWORD}@localhost:5433/stroom" -c "SELECT version();"

# LiteLLM: 4 model aliases show up
curl -s http://localhost:4000/v1/models \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" | jq '.data[].id'
# Expected (any order): stroom-bulk, stroom-embed, stroom-deep, stroom-long-context

# nginx media: returns 200 or 403 (both mean it's up — directory is empty)
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8090/

# Kokoro: (Removed - now integrated into API in Fase 4)
# curl -s http://localhost:8880/v1/audio/voices | jq 'length'
```

If any of these fail, stop and report.

## Fase 1 — schema + seeds

### 1.1 Load the schema

```bash
psql "postgresql://stroom:${STROOM_DB_PASSWORD}@localhost:5433/stroom" \
  -f schema/stroom-schema.sql
```

Expect zero errors. Any error → stop and report.

### 1.2 Verify structure

```bash
psql "postgresql://stroom:${STROOM_DB_PASSWORD}@localhost:5433/stroom" <<'SQL'
\dx
\dt
\dv
SQL
```

Expected:
- **Extensions:** `pgcrypto`, `vector`, `pg_trgm` (plus `plpgsql`, ignore — it's built-in).
- **Tables (8):** `sources`, `items`, `insights`, `saves`, `feed_events`, `episodes`, `reflections`, `todos`.
- **Views (3):** `v_processing_queue`, `v_stream`, `v_obsidian_queue`.

If any count is off, stop and report.

### 1.3 Load seeds

```bash
psql "postgresql://stroom:${STROOM_DB_PASSWORD}@localhost:5433/stroom" \
  -f schema/seeds/001-sources.sql
```

### 1.4 Verify seeds

```bash
psql "postgresql://stroom:${STROOM_DB_PASSWORD}@localhost:5433/stroom" \
  -c "SELECT kind, COUNT(*) FROM sources GROUP BY kind;"
# Expected: 3 rows (youtube, rss, podcast), each count ≥ 1

psql "postgresql://stroom:${STROOM_DB_PASSWORD}@localhost:5433/stroom" \
  -c "SELECT COUNT(*) FROM v_processing_queue;"
# Expected: 0 — nothing has been polled yet, that's correct
```

## Acceptance checklist

- [ ] `docker compose ps` — 3 services `healthy`
- [ ] `curl` to LiteLLM → 4 model aliases
- [ ] `\dt` → 8 tables
- [ ] `\dv` → 3 views
- [ ] `sources` → ≥ 3 rows
- [ ] `v_processing_queue` → 0 rows

## What NOT to do

- ❌ Do not modify `schema/stroom-schema.sql`. If something looks wrong, report and wait.
- ❌ Do not modify `docker-compose.yml` or `litellm/config.yaml`. Same rule.
- ❌ Do not add new env variables beyond those in `.env.example`.
- ❌ Do not create files in `api/` or `web/` — those are for later phases.
- ❌ Do not run `docker compose down -v` — the `-v` wipes the database volume.
- ❌ Do not commit the `.env` file. Confirm with `git check-ignore .env` if in doubt.
- ❌ Do not proceed to Fase 2 (n8n flows) — that needs review first.

## When done, report

1. Output of `docker compose ps`.
2. Output of `psql ... -c "\dt"`.
3. Output of `psql ... -c "SELECT kind, COUNT(*) FROM sources GROUP BY kind;"`.
4. Anything unexpected, no matter how small.

Then wait for review.

---

# Roadmap: Fase 2 - 10

## Fase 2 — n8n Pollers
Build the data ingestion pipeline in n8n.
- Setup YouTube Data API poller.
- Setup RSS feed poller.
- Setup Podcast (iTunes/RSS) poller.
- Insert raw items into `items` table.

## Fase 3 — Automated Summarization
Connect the dots between raw items and AI.
- n8n flow: `v_processing_queue` $\rightarrow$ LiteLLM (Qwen) $\rightarrow$ Summary + Insights.
- Update `items` with summary and populate `insights` table.
- Mark item as `ready`.

## Fase 4 — Core API (FastAPI)
The backend that powers the frontend and integrations.
- Setup FastAPI structure in `/api`.
- Implement Database Layer (SQLAlchemy/SQLModel).
- Endpoints for the "Stream" (getItems, getItemDetail).
- Integrated Kokoro-ONNX for TTS generation.
- "Regenerate summary" endpoint via LiteLLM.

## Fase 5 — Obsidian Integration
Export curated knowledge to personal vault.
- Implement "Save to Obsidian" logic.
- Mapping categories to Obsidian folders.
- Integration with Obsidian Local REST API.

## Fase 6 — Vikunja Integration
Turn insights into action.
- Implement "Add to Vikunja" logic.
- Mapping insights to Vikunja tasks.
- Integration with Vikunja API.

## Fase 7 — Podcast Generation
The "Weekly Review" audio experience.
- Aggregator: Select saved insights for a given range (day/week/month).
- Scripting: LiteLLM generates a conversational script based on insights.
- TTS: Convert script to audio via Kokoro.
- Storage: Save result to `media/` folder for Nginx.

## Fase 8 — Frontend (Next.js PWA)
The visual interface based on the provided sketch.
- Main "Stream" view with filtering.
- Item detail view with insight management.
- "Spiegel" (Reflections) view for daily journaling.
- Podcast player and generator UI.

## Fase 9 — "Deeper" Chat
AI-powered exploration of a specific insight.
- Implement a chat interface for drilling down into a single insight.
- LLM context management (Insight + Item Summary + External Knowledge).

## Fase 10 — Final Polishing & Deployment
- Performance optimization.
- Final security hardening.
- Complete deployment to strongbad.
