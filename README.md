# Stroom

Personal content curation: YouTube / RSS / podcast → Qwen summaries → Postgres+pgvector → Obsidian notes, Vikunja todos, Kokoro-generated podcasts.

**Deployment target:** `strongbad` (Coloclue VPS), accessed over Tailscale.

## Stack

| Component       | Image / tool                    | Purpose                                          |
| --------------- | ------------------------------- | ------------------------------------------------ |
| `stroom-db`     | `pgvector/pgvector:pg16`        | Source of truth — tables, views, embeddings     |
| `litellm`       | `ghcr.io/berriai/litellm`       | OpenAI-compatible gateway to all models          |
| `kokoro`        | `ghcr.io/remsky/kokoro-fastapi` | TTS for generated podcast episodes               |
| `stroom-media`  | `nginx:alpine`                  | Serves the mp3 directory                         |
| Ollama          | external                         | Runs `qwen3.6` + `nomic-embed-text`              |

## Getting started

See [TASKS.md](./TASKS.md) for Fase 0 + 1 (infra + schema).

The full 10-phase build plan lives in the design doc (not in this repo).

## Layout

```
docker-compose.yml          top-level stack
litellm/config.yaml         model routing (4 aliases)
schema/stroom-schema.sql    database schema (8 tables, 3 views)
schema/seeds/               starter data
media/                      nginx-served mp3 directory
api/                        FastAPI app — Fase 4
web/                        Next.js PWA — Fase 8
```

## Ports (all bound to 127.0.0.1)

- `5433` — Postgres
- `4000` — LiteLLM proxy
- `8880` — Kokoro TTS
- `8090` — nginx media

Access remotely over Tailscale SSH with local port-forwarding.
