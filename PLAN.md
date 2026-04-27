# Stroom — Huygens werkplan

Living plan voor de Stroom-suite (Huygens viewer + Spinoza/Leeuwenhoek/Hertz). Lees dit eerst bij elke nieuwe sessie. Update bij elke grote stap.

## Concept (4 apps, één DB)

| App | Rol | Status |
|---|---|---|
| **Huygens** | Topic-aggregatie viewer (artikelen / podcasts / videos / short-form per thema) | **In aanbouw** |
| **Spinoza** | Reflectie & geleerde lessen | Schema klaar (`reflections`), UI nog niet |
| **Leeuwenhoek** | Inzichten extraheren uit items (= samenvat-skill) | Schema klaar (`insights`), samenvat-agent draait standalone |
| **Hertz** | Gecureerde content → podcast (TTS) | Schema klaar (`episodes`), services/podcast_service.py heeft Kokoro |

Eén Postgres-DB onder alle vier. Obsidian blijft archief-truth, DB is queryable index.

## Stack overzicht

| Component | Locatie | Status | Bereikbaar via |
|---|---|---|---|
| `stroom-db` | `/opt/stacks/vps-stacks/stroom/` (compose) | Up, pg16 + pgvector + pg_trgm | `127.0.0.1:5433` (intern) |
| `stroom-litellm` | idem | Up, unhealthy maar functioneel | `127.0.0.1:4000` |
| `stroom-media` | idem | Up (nginx static) | `127.0.0.1:8090` |
| `stroom-api` | idem (toegevoegd) — code in `stroom-src/api` | Up | `127.0.0.1:8100` |
| Frontend (vite dev) | `stroom2/prototype/` | Draait handmatig op 0.0.0.0:8101 | `https://stroom.c4w.nl` (NPM) of `http://10.100.0.252:8101` |
| `samenvat-agent` | `samenvat-agent/` | Up (FastAPI GPU pipeline) | `samenvat-agent:8080` op personal_net |

## Wat is af

### Schema
- 11 tabellen (8 origineel + 3 toegevoegd voor Huygens)
- Toevoegingen: `topics`, `item_topics`, `source_topics`, `items.format` enum, `sources.image_url`
- Migrations: `stroom-src/schema/migrations/002-...`, `003-source-image.sql`
- Seeds: `stroom-src/schema/seeds/002-topics-and-sources.sql`, `003-ingest-recent-items.py`, `004-fill-source-images.py`, `005-more-sources.sql`

### API (FastAPI op port 8100)
- `GET /topics` — alle topics + item-counts
- `GET /huygens/{slug}` — topic met 4 rails (article/podcast/video/short), top-N per rail
- `GET /huygens/items/{id}` — volledig item (incl. status, processing_status, transcript, summary, topics)
- `POST /huygens/items/{id}/status` — pin/later/archive/new (schrijft ook `feed_events`)
- `POST /huygens/items/{id}/summarize` — LiteLLM op transcript-of-description, schrijft `summary`
- `POST /huygens/items/{id}/transcribe` — POST naar samenvat-agent `/process`
- Plus de bestaande endpoints uit pre-Huygens fase: `/stream`, `/items/{id}/regenerate`, `/insights/{id}/explore`, `/saves`, `/todos`, `/episodes`

Belangrijk: nieuwe endpoints gebruiken raw SQL via `sa_text` om de SQLModel-enum-mismatch te omzeilen (DB-waarde lowercase vs SQLAlchemy enum-name uppercase).

### Frontend (`stroom2/prototype/`)
- Vite + React 19 + Tailwind v4
- Fonts: Fraunces (display), Newsreader (serif body), Inter Tight (sans/UI), JetBrains Mono (metadata)
- **Topic-pagina**: chips voor topic-switching, 4 rails (Articles tekst-only, Podcasts square+art, Videos 16:9, Short-form leeg)
- **Detailpagina** (URL `?item=<uuid>`):
  - Back button (browser-back werkt)
  - Action toolbar: pin / later / archive / summarize / transcribe (laatste alleen voor podcast/video)
  - Format-badge + topic-tags
  - Hero-image voor podcast/video (article tekst-only)
  - Author + source + datum, channel-image
  - Summary highlight (italic, accent line) als gevuld
  - Description als HTML gerenderd via `dangerouslySetInnerHTML` met custom prose-stroom CSS
  - Transcript onder `<details>` als aanwezig
  - "View original at [source]" link
- URL state: `?topic=ai&item=<uuid>` — refreshen + back/forward werken

### Data
- 9 topics: AI, Tech, NL News, Politics NL, International News, Health, Sports, HR-tech, Misc
- 19 sources actief, 7 zonder topic (Craig Mod, Stroom-inbox + ?)
- ~210 items, alle 7 niet-lege topics gevuld
- Channel-images aanwezig waar feed ze exposed (Latent Space, Hard Fork, Huberman, Hard Fork, Pragmatic Engineer, Tweakers, Stratechery, CNN, HR Tech Feed, WorkLife)

## Wat nog open staat

### Bronnen die we nog niet konden toevoegen — RSS-URL niet vindbaar zonder login
Voeg toe zodra je de feed-URL uit je podcast-app (Pocket Casts, Overcast etc.) hebt:
- **AI**: AI Report (welke?), AI Engineer (YouTube channel-id niet via scrape gevonden)
- **Tech**: Met Nerds om Tafel
- **NL News**: FD Dagkoers, Dit is de Dag (NPO Radio 1)
- **Politics NL**: Jesse Frederik podcast (welke specifiek? "Jesse vs het Grote Geld"?)
- **International News**: The Rest is Politics, Wereldzaken (NRC), Veldheren
- **Sports**: WielerOrakel, Tweewielers
- **HR-tech**: Recruiting Future with Matt Alder
- **Misc**: People Fixing the World (BBC) — programme-id correct opzoeken

### X / Twitter (short-form rail)
- 10 accounts staan klaar in plan: Erik Brynjolfsson, Garry Tan, Ethan Mollick, Demis Hassabis, Ian Goodfellow, Ilya Sutskever, Andrej Karpathy, Andrew Ng, Jeff Dean, Kevin Kelly
- Stack `twitter-scraper/` met `twscrape` is gescaffold, niet geconfigureerd
- **Blokkade**: twscrape vereist een sock-puppet X-login (`twscrape add_accounts`). Pas daarna kunnen we:
  1. `content_kind` enum uitbreiden met `x`
  2. 10 sources toevoegen (kind=x, format=short)
  3. `twitter_sync.py` herschrijven om naar Postgres `items` te schrijven ipv queue-file
  4. Scraper op cron zetten

### Productie-rijp maken (niet vandaag)
- Vite-frontend dockerizen + in `/stroom/docker-compose.yml` toevoegen op port 8101 (nu draait 'ie als ad-hoc proces)
- DOMPurify toevoegen vóór `dangerouslySetInnerHTML` als je ooit user-submitted of niet-gecureerde feeds toevoegt
- Cron voor periodieke ingest (nu eenmalig handmatig via `003-ingest-recent-items.py`)

### Backlog
- **Podcast transcript-link detectie**: voor podcasts met host-geleverd transcript (TED, Anchor, etc.) — scrape description voor "transcript URL" patterns → trafilatura → skip Whisper. Bespaart GPU-tijd.
- **Admin-scherm voor sources** (met weights) — eerstvolgende grote feature
- **Authentik** ervoor als je 'm extern wil openen voor meer mensen dan jezelf

### SQLModel-enum bug
- `models/base.py` heeft `class ContentKind(str, Enum): RSS = "rss"` — SQLAlchemy slaat by-name op (RSS) maar DB heeft 'rss'.
- Voor het pre-Huygens deel van de API was dit waarschijnlijk al kapot. Bij gebruik van `await session.get(Item, id)` crasht 'ie met `LookupError: 'rss' is not among the defined enum values`.
- Workaround in nieuwe endpoints: raw SQL via `sa_text`.
- Schoner: alle enum-defs verbouwen met `values_callable=lambda x: [e.value for e in x]` op de SA Enum, of de oude endpoints ook ombouwen naar raw SQL.

### Nice-to-haves voor Huygens UI
- **Saved/pinned overzichtspagina** — apart endpoint `/huygens/saved?status=pinned` plus filter in topic-chips ("Pinned only")
- **Search** (zoekicoon staat al in nav) — full-text op title/description met `pg_trgm`, of pgvector embeddings
- **Filter binnen topic**: format-chips ("Only podcasts", "Only articles")
- **Pagina /spinoza** als losse view voor reflections
- **Mobiel**: nav weggevallen in nieuwe versie, mobile bottom-bar verwijderd. Of terug erin.

### Samenvat-agent → DB write-back (KLAAR 2026-04-26)
- `ProcessRequest.stroom_item_id` (optioneel) toegevoegd aan samenvat-agent
- `process.py` print `STROOM_TRANSCRIPT_FILE=` en `STROOM_SUMMARY_FILE=` markers
- Na pipeline: samenvat-agent POST naar `stroom-api:8000/huygens/items/{id}/transcribe-callback` met `{transcript, summary}` (of `{error}`)
- Callback is afgeschermd met `X-Stroom-Internal-Token` header (gegenereerd in `.env`, gedeeld tussen stroom-api en samenvat-agent)
- Stroom-api callback-endpoint zet `transcript`, `summary`, `summary_model='samenvat-agent'`, `processing_status='ready'`
- `transcribe_item` geeft `stroom_item_id` mee aan upstream call
- Frontend Detail-view polt `fetchItem` elke 8s zolang `processing_status` `transcribing`/`summarizing` is

### Taal-bewuste samenvatting (KLAAR 2026-04-26)
- `summarize.py` detecteert Nederlands vs niet-Nederlands via stopwoord-frequentie
- NL → bestaande NL-prompt; alle andere talen → mirror-EN-prompt
- Whisper transcribeert al in brontaal → samenvatting volgt nu ook brontaal (NL→NL, EN→EN)

### App-level login (KLAAR 2026-04-26)
- `users` + `sessions` tabellen (migration `004-users-sessions.sql`)
- scrypt-hashed wachtwoorden, 30-dagen sessions in httpOnly + SameSite=Lax cookie `stroom_session`
- Routes: `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- AuthMiddleware schermt alles af behalve `/health`, `/auth/*`, en `*/transcribe-callback` (interne token)
- Login rate-limit: 5 pogingen / 15 min per IP
- CSRF: Origin moet in CORS-allowlist staan
- Seed-script `schema/seeds/006-create-user.py`
- Frontend: `LoginScreen` als `/auth/me` 401 geeft, anders gewone app; Uitlog-knop in nav

### Transcribe rate-limit (KLAAR 2026-04-26)
- Max 1 actieve transcribe-job tegelijk (single GPU): 429 als al een item `processing_status='transcribing'` heeft
- Max 5 transcribes/uur per user: in-memory teller per user-id

### Transcribe queue (KLAAR 2026-04-26)
- Migration `005-transcribe-queue.sql`: `queued` enum-value + `items.queued_at`
- Bij Transcribe-klik: GPU vrij → direct `transcribing`; GPU bezig → `queued` met `queued_at=now()`
- `_process_next_queued()`: bij elke callback (ready/failed) wordt FIFO de volgende `queued` opgepakt
- `HuygensItemDetail.queue_position` (1-based) berekend on-the-fly
- UI-knop labels: `Transcribed` / `Queued #N` / `Transcribing…` / `Transcribe`
- Polling triggert ook op `queued` zodat nummer real-time zakt
- Cap: 50 transcribes/uur per user (was 5)

### Source weights + admin-API (KLAAR 2026-04-26)
- Migration `006-source-weights.sql`: `sources.weight` (1-10, default 5), `sources.max_per_rail` (nullable), `sources.active` (default true)
- Huygens-query: ranking-score = `epoch(published_at) + weight × 7d`, ROW_NUMBER per (source, format) ≤ max_per_rail, filtert `active=false` weg
- Endpoints: `GET /admin/sources`, `POST /admin/sources`, `PATCH /admin/sources/{id}`, `DELETE /admin/sources/{id}` — allemaal achter login
- AdminSource-payload bevat o.a. topic_slugs en item_count

## Recap 2026-04-26

Vandaag in volgorde gebouwd:
1. **samenvat-agent → DB write-back** met internal-token header
2. **Polling** op processing_status in detail-view
3. **Taal-detectie** in summarize.py (NL/EN)
4. **App-level login** (users, sessions, scrypt, cookies, middleware, login-screen)
5. **Transcribe rate-limit** (1 concurrent + 50/uur per user)
6. **Transcribe queue** (FIFO, queue_position, auto-pickup na callback)
7. **Source weights + admin-API** (weight, max_per_rail, active)

In aanbouw: **admin UI** (sources beheren). Server-side klaar; frontend nog te bouwen.

## Snelle commando's

```bash
# DB inspecteren
docker exec -it stroom-db psql -U stroom -d stroom

# Nieuwe ingest (haalt 10 recente items per source op)
docker run --rm --network personal_net \
  -v /opt/stacks/vps-stacks/stroom-src/schema/seeds:/seeds:ro \
  -e PGHOST=stroom-db -e PGUSER=stroom -e PGDATABASE=stroom \
  -e PGPASSWORD=$STROOM_DB_PASSWORD \
  python:3.12-slim sh -c "pip install -q feedparser 'psycopg[binary]' && python /seeds/003-ingest-recent-items.py"

# API restart na code-change
cd /opt/stacks/vps-stacks && docker compose up -d --build stroom-api

# Vite-frontend (huidige proces draait via Bash background-task; bij reboot opnieuw starten)
cd /opt/stacks/vps-stacks/stroom2/prototype && DISABLE_HMR=true npx vite --port=8101 --host=0.0.0.0

# User aanmaken / wachtwoord rouleren
export $(grep -E '^STROOM_DB_PASSWORD=' /opt/stacks/vps-stacks/.env)
docker run --rm --network personal_net \
  -v /opt/stacks/vps-stacks/stroom-src/schema/seeds:/seeds:ro \
  -e PGHOST=stroom-db -e PGUSER=stroom -e PGDATABASE=stroom \
  -e PGPASSWORD="$STROOM_DB_PASSWORD" \
  -e SEED_EMAIL=han@hanrusman.nl -e SEED_PASSWORD='NIEUW' \
  python:3.12-slim sh -c "pip install -q 'psycopg[binary]' && python /seeds/006-create-user.py"
```

## Huidige open vraag voor de gebruiker

Eén ding waar we op wachten: lijst van **echte feed-URL's** uit jouw podcast-app voor de 11 NL/EU podcasts hierboven, óf bevestiging dat we die voorlopig laten rusten en eerst andere features afronden (samenvat-agent integratie, search, mobile layout).

---

## Update 2026-04-26 (avond) — nightly cron + tests + docs

### Nightly cron toegevoegd
- **Endpoint:** `POST /admin/cron/nightly` (achter `STROOM_INTERNAL_TOKEN`).
  Refresht alle actieve sources, queue't items van laatste 48u die `kind ∈ {podcast, youtube}` zijn, geen transcript hebben, met media_url, en niet al in queue/transcribing/summarizing zitten. Triggert vervolgens `_process_next_queued`; de transcribe-callback drained de rest.
- **Bug gevonden + gefixt tijdens testen:** eerste implementatie filterde niet op `kind` → RSS-artikelen (NU.nl, Wielerflits, Hacker News) belandden in de transcribe-queue omdat hun `media_url` terugviel op de artikel-link. Nu beperkt tot podcast + youtube.
- **Cron in host-crontab:** `0 3 * * * docker exec stroom-api sh -c '…' >> /opt/stacks/vps-stacks/stroom/cron-nightly.log 2>&1`.

### Source-migratie weg van FreshRSS
- 5 nieuwe sources in Stroom (AI Report, Lang verhaal kort, MIT News - AI, Nate's Newsletter, Google Research / Jeff Dean) met topic-mappings. AI Report stond per ongeluk in FreshRSS — verwijderd daar.
- `freshrss_sync.py` cron uitgecommentariëerd. FreshRSS container blijft draaien voor Reader-style artikel-bladeren.

### Tests (Laag 1)
- Pytest-foundation in `stroom-src/api/tests/` (`pytest.ini`, `conftest.py`, `requirements-dev.txt`)
- `test_pure.py` (unit) — `_feed_media_url`, `_feed_thumb_url`, `_feed_first_text`
- `test_cron_nightly.py` (integration) — auth, response-shape, idempotency-invariant, error-bounds
- `samenvat-agent/tests/test_summarize.py` — `detect_language`, prompt-shape voor alle (lang × source_type) combinaties
- Run: `docker exec -w /app stroom-api pytest tests -v`. Zie `tests/README.md`.

### Documentatie
- `vps-stacks/ARCHITECTURE.md` — rolverdeling van alle services (Stroom, samenvat-agent, Talon, FreshRSS, Obsidian, LiteLLM, Authentik, etc.) + service-contracten + data-eigendom.

### Open / volgende sessie
- Tests Laag 2: DB-fixture-based tests voor `_refresh_one`, `_process_next_queued`, queue-statemachine, auth-flow.
- `requirements-dev.txt` permanent in Dockerfile zetten zodat pytest na rebuild niet weg is.
- Feed-summary stijl-keuze (zie hieronder, nog open).

---

## Update 2026-04-26 — opruimsessie + features

### Tech debt opgeruimd
- `/opt/stacks/stroom-src/` (oude losstaande checkout, 19 apr) → `stroom-src.archive-20260426-101202`
- Shadow compose-files met kapotte `../../stroom-src/api` paden gearchiveerd:
  - `vps-stacks/stroom-src/docker-compose.yml.archive-…`
  - `vps-stacks/stroom2/docker-compose.yml.archive-…`
- Hele `vps-stacks/stroom2/` → `stroom2.archive-20260426-101202` (prototype was af)
- `stroom2/prototype/` gepromoveerd naar canonical `stroom-src/web/`; oude Next.js `stroom-src/web/` is gearchiveerd
- Vite dev-server draait nu vanuit `stroom-src/web/` op `:8101`

### Compose: bind-mount voor live edits
- Actieve compose: `vps-stacks/stroom/docker-compose.yml` (via top-level `include:` in `vps-stacks/docker-compose.yml`)
- `stroom-api` heeft nu `../stroom-src/api:/app:ro` bind-mount → Python-edits zijn live na `docker restart stroom-api`, geen rebuild meer nodig

### Branding fix
- `stroom-src/web/index.html`: titel `My Google AI Studio App` → `Stroom`, inline-SVG favicon (donkerblauwe golfjes), `lang="nl"`, `theme-color`

### Admin features (frontend + backend)
- **Per-source refresh-knop** in tabel — POST `/admin/sources/{id}/refresh` (feedparser haalt laatste 20 entries, idempotent op `(source_id, external_id)`, koppelt nieuwe items via `source_topics` aan topics)
- **"Refresh alle"-knop** naast "Toon queue" — POST `/admin/sources/refresh-all`. Loopt door alle `active=true` sources, commit per source zodat één kapotte feed de rest niet sloopt. Returnt `{sources, errors, inserted, checked}`. Bij feed-fail: `last_poll_status='error: ...'`. Helper `_refresh_one()` gedeeld met per-source endpoint.
- **Toon queue-paneel** — modal met live-polling van `/admin/queue` (5s interval), toont items met `processing_status` ∈ {queued, transcribing} en queue-positie

### Summarize-flow uitbreiding
- `POST /huygens/items/{id}/summarize` doet nu:
  1. **Heeft transcript** → samenvatten met `stroom-bulk` LLM (zoals voorheen)
  2. **Geen transcript, wel media_url** → automatisch in transcribe-queue zetten (of direct starten als GPU vrij). Samenvat-agent levert via callback **zowel transcript als summary** (`summary_model='samenvat-agent'`)
  3. **Geen transcript, geen media_url** → fallback op show-notes / description
  4. **Niets** → `400 Geen transcript, media_url of beschrijving`
- Endpoint vereist nu `require_user` (i.v.m. transcribe-quota van 50/uur)
- Statussen `queued` / `transcribing` / `summarizing` worden gerespecteerd (no-op bij dubbele click)
- Bug-fix: `_fetch_item_row` returnde `processing_status` niet → `KeyError` op summarize-call. SELECT uitgebreid met `processing_status::text`.

### Auth / origin fixes
- `_ALLOWED_ORIGINS` is nu env-configurabel via `STROOM_ALLOWED_ORIGINS` (comma-separated, voegt toe aan defaults)
- `http://stroom.c4w.nl` toegevoegd aan defaults — proxy stuurt Origin als http ondanks dat browser https ziet (iPhone Safari ondervond dit)
- Login werkt nu vanaf iPhone/Boox via `https://stroom.c4w.nl` en `https://stroom.c4w.nl/admin`
- CSRF-guard logt geweigerde origins (`[csrf] rejected origin=...`); `require_user` logt 401's met cookie-aanwezigheid en UA — handig voor toekomstige device-issues

### Podcast-import (60+ feeds)
- 4 nieuwe topics: `vandaag`, `kids`, `economics`, `science`
- 57 nieuwe podcast-sources ingevoegd (transactional via `/tmp/import_podcasts.sql`)
- 6 reeds bestaande URLs hernoemd naar user's gewenste display-name + weight bijgesteld + topics opnieuw gemapt
- Verdeling per topic: misc 16, tech 9, international-news 9, ai 6, politics-nl 6, economics 4, health 4, vandaag 4, sports 3, hr-tech/kids/nl-news/science elk 1
- 65 podcast-sources totaal, 81 sources totaal in DB

### Bekende issues / open
- Mobile layout van AdminPage: brede tabel scrollt horizontaal binnen `overflow-x-auto`. Wel bedienbaar, niet mooi. Open vraag of we naar een card-layout per source moeten op mobiel.
- Summary-stijl-consistentie: na transcribe wordt `summary_model='samenvat-agent'` gezet, niet `stroom-bulk`. Wil de gebruiker uniformiteit, dan na transcribe-callback opnieuw door stroom-bulk halen, óf de samenvat-agent prompt gelijktrekken. Nog te beslissen.

  **Achtergrond (2026-04-26):** beide paden draaien op **dezelfde lokale Qwen3.6** via LiteLLM-alias `stroom-bulk`. Geen kosten/model-verschil. Het verschil zit puur in de **prompt + output-vorm**:

  | | Stroom-API `/summarize` | Samenvat-agent (na transcribe) |
  |---|---|---|
  | Prompt-stijl | "Curator… NL, zakelijk maar warm, **max 3 zinnen**" | "Personal Knowledge Manager", volledige Obsidian-note: `# Title`, `## Metadata`, `## Summary` (multi-H3 prose), `## Key takeaways`, `## Connections` met `[[wiki-links]]` |
  | Lengte | ~70 woorden, 3 zinnen | "~3 pages per hour", meerdere alinea's |
  | Taal | NL altijd | EN default, taal van transcript |
  | Doel | Korte teaser in feed-card | Naslag-document |

  De lange Obsidian-note wordt door samenvat-agent **al naar Obsidian gepusht** (`process.py:158 push_to_obsidian`). Hij heeft dus al een thuis los van Stroom's `summary`-veld.

  **Voorgestelde fix (akkoord van user, nog niet uitgevoerd — kiezen lengte eerst):**
  - In `/huygens/items/{id}/transcribe-callback`: alleen `transcript` opslaan, **agent's `body.summary` negeren**
  - Daarna in Stroom een korte stroom-bulk-call op het transcript draaien → vult `summary` met consistente 3-zinner-stijl
  - Obsidian behoudt de uitgebreide note (ongewijzigd), Stroom-feed wordt overal consistent
  - Kosten: 1 extra korte Qwen-call per transcriptie, lokaal/gratis

  **Open keuze voor user — lengte van de feed-summary:**
  - 2 zinnen (~50 woorden) — strakker, scant sneller
  - **3 zinnen (~70 woorden) — huidige, evenwicht tussen context en leesbaarheid**
  - 5 zinnen / kort paragraafje (~120 woorden) — meer body, je begint te scrollen
  - 3-4 bullets met takeaways — feitelijker, minder verhalend

  Wanneer user kiest: prompt aanpassen + callback-handler omzetten. Klein werk (~15 min).
- `/opt/stacks/vps-stacks/claude/.claude/settings.local.json` heeft nog stale grants naar `/opt/stacks/stroom-src/...` — geen werking, alleen rommel.

---

## Update 2026-04-27 — topic-digest + thumbnails + async-fixes

Branch: `feat/topic-digest`. Alles op `stroom-src` repo. Niet gemerged naar `main` (af te ronden in volgende sessie).

### Per-topic dagdigest (KLAAR — werkt na 500-fix)
- **Schema:** migration `008-topic-digests.sql` (één rij per topic) + `009-topic-digest-async.sql` (kolommen `is_generating`, `generation_started_at`, `error`; `markdown`/`item_count` nullable).
- **Endpoints:**
  - `GET /huygens/{slug}/digest` → opgeslagen digest (404 als nog geen rij of `markdown=null`).
  - `POST /huygens/{slug}/digest?model=qwen|sonnet|opus` → start async generatie via `BackgroundTasks`, return direct met `is_generating=true`. **Geen 504 meer.**
  - `409` als al `is_generating=true` én `< DIGEST_GENERATION_STALE_MIN` (10 min) geleden gestart — voorkomt dubbele runs. Stale lock wordt overschreven.
- **LLM-aliases (`DIGEST_MODEL_MAP`):**
  - `qwen` → `stroom-bulk` (lokaal Qwen3.6, gratis)
  - `sonnet` → `stroom-sonnet` (LiteLLM-alias, betaald)
  - `opus` → `stroom-opus` (idem)
- **Window:** 24u (`DIGEST_WINDOW_HOURS`). Pakt items van actieve sources met published_at >= now()-24h, ORDER BY published_at DESC, max ~30 items.
- **Prompt:** "Schrijf een markdown-digest in het Nederlands…" — output is markdown met `[verder lezen](item://<uuid>)` links.
- **Frontend:**
  - Digest-paneel boven topic-rails, klapt open bij klik.
  - Knop "Genereer/Ververs" met model-selector (Qwen/Sonnet/Opus).
  - Tijdens generatie: knop grijs + spinner + label "Bezig met genereren…".
  - Polling elke 4s zolang `is_generating=true`. Zodra klaar → markdown rendered (markdown→HTML lib), panel klapt automatisch open.
  - `item://<uuid>` links worden afgevangen → opent detailpagina (URL `?item=<uuid>`).
  - Error-message wordt netjes getoond als `error` is gezet.
- **Bug-historie deze sessie:**
  1. **504 timeout** bij Qwen-runs >2 min → opgelost door `BackgroundTasks` + UI-polling (commit `8ab0c24`).
  2. **500 Internal Server Error** na async-omzetting → SQLAlchemy lazy-load van `topic.id` werd pas in `BackgroundTasks.add_task` opgevraagd, ná sessie-close → `MissingGreenlet`. Fix: `topic_id = str(topic.id)` en `topic_name = topic.name` capturen vóór commit; alle SQL-binds gebruiken nu `CAST(:tid AS uuid)` (commit `9f1fbe7`).
- **Recovery na crash:** vastgelopen rijen met `is_generating=true` resetten met:
  ```sql
  UPDATE topic_digests SET is_generating=false WHERE is_generating=true;
  ```

### Filters gekoppeld aan topic + datumvenster (commit `c519406`)
- Topic-chip-filters werken nu mét datumvenster (24h/7d/etc.) — voorheen reset bij topic-switch.

### Thumbnails (commits `0ef3141`, `338b85c`, `1a07b8a`, `b59c42c`)
- **Ingest** scrape't `og:image` voor RSS-artikelen + per-episode `itunes:image` voor podcasts.
- **Seed `008-backfill-thumbnails`** voor historische items.
- **Refresh-all** backfilled missende thumbnails — async (commit `1035878`) zodat de admin-call niet meer 504't bij grote runs.
- Article-card valt terug op gradient als geen image.

### LessonsSection bovenaan in detail (commit `b16f022`)
- `summary` wordt als HTML gerendered.
- Lessons-blok wordt boven de description geplaatst, niet onderaan.

### LLM timeout 60→180s (commit `3d8bee6`)
- LiteLLM-call krijgt nu 180s timeout + duidelijke fout bij lege content.

### Open / volgende sessie
- **Branch mergen** naar `main` zodra alles getest is. Topic-digest werkt nu (na lazy-load fix); user moet bevestigen dat Qwen-genereren end-to-end goed gaat.
- **Auto-refresh van digest** bij nightly cron? Nu enkel handmatig via knop. Optie: nightly draait automatisch Qwen-digest voor elke topic met >5 items in laatste 24u.
- **Digest-history** — nu één rij per topic (UPDATE bij refresh). Eventueel naar `topic_digests_history` schrijven om eerdere versies te bekijken.
- **Web-archief opruimen:** `vps-stacks/stroom-src/web.archive-20260426-101202/` en `vps-stacks/stroom-src/docker-compose.yml.archive-20260426-101202` zijn untracked — kunnen weg of in git.
