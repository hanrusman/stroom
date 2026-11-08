# Dossiers: brede onderzoeksvragen over het hele archief

Een vraag als *"hoe verandert het inkopen van software, en waar kiezen
organisaties voor zelf bouwen?"* raakt honderden items. Een chat-LLM met
zoektools (Okavango) verdrinkt daarin: twintig zoekhits, elk met een
samenvatting van tientallen KB, past niet in één context. Het leest er dan
drie en generaliseert.

Een dossier doet wat een onderzoeksteam zou doen. Elke stap gebruikt het model
dat erbij past, en slaat zijn resultaat op voordat de volgende stap begint.

| # | Stap | Model (default, met fallback) | Wat |
|---|------|------------------------------|-----|
| 1 | plan | `stroom-sonnet` → `cloud-kimi` → `cloud-deepseek` | Vraag → 4-7 aspecten (deelvragen, incl. tegengeluid) + 18-28 zoekvragen NL/EN |
| 2 | recall | — | Per zoekvraag FTS (NL+EN-stemming) én e5-vectoren, 40 per lijst; Reciprocal Rank Fusion over alle lijsten. Gearchiveerde (= gelezen) items tellen mee |
| 3 | screen | `cloud-gemma` → `cloud-gpt-120b` | Top 650 op titel + teaser, batches van 25, score 0-3 |
| 4 | extract | `cloud-gemma` → `cloud-deepseek` | Per bron (max 160: eerst score ≥ 2, dan max 40 twijfelgevallen) specifieke beweringen met aspect, richting, actoren, sector, regio, bewijssoort, spreker en citaat. Citaten die niet letterlijk in de bron staan worden gewist |
| 5 | deepen | plan-modellen | Ziet de opbrengst per aspect (aantallen, actoren, regio's, bewijs) en zoekt 8-14 nieuwe zoekvragen voor de gaten. Daarna recall → screen → extract op max 160 nieuwe kandidaten (max 60 gelezen) |
| 6 | write | `stroom-deep` (Opus) → `stroom-sonnet` → `cloud-kimi` | Dossier in markdown met `[S12]`-verwijzingen; bronnen genummerd op datum |
| 7 | critique | `cloud-deepseek` → `cloud-kimi` (Gemini `stroom-long-context` kan via env terug) | Andere modelfamilie toetst het concept aan de bevindingen: onderbouwing, citaten, overgeneralisatie, gemist tegengeluid. JSON, met tekst als fallback |
| 8 | revise | schrijfmodellen | Verwerkt de kritiek; ongeldige `[S..]`-nummers worden daarna weggehaald |

Na afloop: **doorvragen** (`ask`) beantwoordt vragen over het dossier met álle
bevindingen, ook wat niet in het rapport kwam (`stroom-sonnet` → `stroom-deep`
→ `cloud-kimi`).

Een proefrun op de software-inkoopvraag (2026-11-08) duurde ~8 minuten:
~800 kandidaten, 650 gescreend, ~210 gelezen, ~700 bevindingen.

## Lessen uit de proefruns

- **Denktokens tellen mee in `max_tokens`.** Opus 4.7, Gemini 2.5, DeepSeek en
  Kimi verbruiken hun budget deels aan redeneren. Met 12k werd het dossier
  midden in een zin afgekapt, en de kritiek (5k) leverde bij alle drie de
  modellen lege JSON op. Nu: schrijven 32k, kritiek 24k, en `LLMService`
  geeft via `meta` de `finish_reason` terug. Is die `length`, dan laat de
  pijplijn het model tot twee keer doorschrijven (tekst), of telt het
  antwoord als kapot (JSON).
- **Sonnet gaf het JSON-sjabloon letterlijk terug** (`"title": "..."`) toen
  de prompt een voorbeeldobject met `...` bevatte. De prompt beschrijft de
  velden nu in woorden, en `parse_plan` weigert placeholders en te weinig
  zoekvragen. Daarna gaat het volgende model aan de slag.
- **Geen jaartallen in zoekvragen**: "build vs buy 2024" sluit de rest van
  het archief uit.
- **Modellen kennen de datum niet.** In de eerste live-run hield Gemini
  bronnen uit 2026 voor toekomst en liet het dossier het archief een
  "prospectief scenario-archief" noemen. Schrijven, kritiek, herziening en
  doorvragen krijgen nu de datum van vandaag vooraan, en kritiekpunten die de
  datering betwisten worden weggefilterd (`drop_date_disputes`).
- **Een herziening moet een dossier zijn.** In een vernieuwing gaf Opus zijn
  overwegingen als tekst ("De gebruiker vraagt me…"), twee keer doorgeschreven
  tot 46k woorden. `clean_revision` eist nu een titelkop en 0,5-1,6× de lengte
  van het concept; anders probeert het volgende schrijfmodel het, en anders
  blijft het concept staan.
- **De verdiepingsronde verdubbelde het aantal bruikbare bronnen** (112 → 206)
  en vulde vooral tegengeluid en NL/EU-casussen aan.

## Terugluisteren

In het bronpaneel (klik op een `[S12]`) staat bij podcasts een knop
*Luister* en per bevinding een tijd (`▶ 12:34`). Die start de sticky speler
op dat moment, met twee tellen aanloop; een tweede tijd in dezelfde
aflevering springt alleen. Bij YouTube-video's openen dezelfde knoppen
YouTube op die seconde.

Het moment komt uit het getimede transcript (`items.transcript_segments`),
zie `services/research_moments.py`:

1. **Letterlijk**: staat het citaat in het transcript (zes woorden op een
   rij), dan is dat het moment. Op het software-inkoopdossier gold dat voor
   94 van de 370 citaten; de rest komt uit samenvattingen en is parafrase.
2. **Bij benadering** (`≈ 12:30`): voor de overige bevindingen leest
   `cloud-gemma` (→ `cloud-gpt-120b`) het transcript in blokken van 30
   seconden en wijst per bevinding het blok aan. Eén aanroep per bron, pas
   als je die bron opent; het resultaat staat daarna in
   `research_runs.moments` (migratie 030), dus het model kijkt maar één keer.

Zonder getimed transcript (ongeveer de helft van de oudere podcasts) is er
alleen *Luister* vanaf het begin.

## Hervatten en vernieuwen

Elke stap kijkt eerst wat er al ligt: plan in `research_runs.plan`, kandidaten
(met `round` 0/1 en `screen_score`) in `research_candidates`, extracties in
`research_findings`, concept en kritiek in `draft`/`critique`. Daardoor:

- **Herstart van stroom-api**: `lifespan` pakt runs die niet `done`/`failed`/
  `cancelled` zijn opnieuw op, vanaf de laatste stap.
- **Mislukt** (bv. Anthropic-krediet op): knop *Verder vanaf laatste stap*.
- **Vernieuwen**: een nieuwe run met `parent_id` neemt plan, verdiepingsvragen,
  screening en extracties over. Alleen nieuwe items worden gescreend en
  gelezen; daarna wordt het dossier opnieuw geschreven.

Runs lopen één voor één (module-lock): ze delen het Ollama-Cloud-budget met
tips en scoring. Binnen een run maximaal 3 gelijktijdige Ollama-Cloud-calls
(`RESEARCH_CLOUD_CONCURRENCY`) en 4 naar Anthropic/Gemini. Dossiers hebben een
eigen httpx-client, zodat ze de pool van de samenvat-workers niet leegtrekken.

## API

Web (sessie):

- `GET/POST /research` — lijst / nieuwe vraag `{question}`
- `GET /research/{id}` — alles (plan, voortgang, rapport, bronnen met
  bevindingen, kritiek, modellen, statistiek, vervolgvragen)
- `GET /research/{id}/funnel` — alle kandidaten met recall, screening en opbrengst
- `POST /research/{id}/ask` `{question}` — vervolgvraag
- `POST /research/{id}/refresh | resume | cancel`, `DELETE /research/{id}`
- `GET /research/{id}/markdown`, `POST /research/{id}/obsidian` (→ `Dossiers/<titel>.md`)
- `GET /research/{id}/sources/{S12}/media` — media van een bron plus letterlijk
  gevonden momenten; `pending: true` als het model nog kan zoeken
- `POST /research/{id}/sources/{S12}/moments` — laat het model de overige
  momenten zoeken en bewaart ze

Okavango (internal token): `GET/POST /internal/research`,
`GET /internal/research/{id}` (compact; `source_ref=S12` voor één bron),
`POST /internal/research/{id}/ask`. Okavango heeft daarvoor de tools
`find_stroom_dossiers`, `get_stroom_dossier`, `ask_stroom_dossier` en
`start_stroom_dossier`. Starten gebeurt alleen na Han's akkoord: het kost
modelgebruik.

## Config (env)

`RESEARCH_{PLAN,SCREEN,EXTRACT,WRITE,CRITIQUE,ASK,MOMENT}_MODELS` (kommagescheiden
fallback-keten), `RESEARCH_SCREEN_MAX` (650), `RESEARCH_EXTRACT_MAX` (160),
`RESEARCH_RECALL_POOL` (40), `RESEARCH_CLOUD_CONCURRENCY` (3),
`STROOM_WEB_BASE_URL` (voor links in markdown-export).

## Datamodel

Migratie `028-research.sql`: `research_runs`, `research_candidates`,
`research_findings`. Verwijderen van een run cascadeert naar kandidaten en
bevindingen. Een vernieuwing blijft dan bestaan, met `parent_id` op NULL.

Toegang: de web-routes tonen alleen je eigen dossiers plus dossiers zonder
eigenaar (gestart via Okavango); een dossier van een ander geeft 404. Wordt een
gebruiker verwijderd, dan gaan diens dossiers mee (`ON DELETE CASCADE`).

## Uitrollen (Strongbad)

Additief: drie nieuwe tabellen, nieuwe routes, geen wijziging aan bestaande
tabellen. Volgorde:

1. Migratie (idempotent, `CREATE TABLE IF NOT EXISTS`):
   `docker exec -i stroom-db psql -U stroom -d stroom < schema/migrations/028-research.sql`
2. `stroom-src`: `git pull --ff-only` (main), dan `docker compose restart stroom-api`.
   Controleer vooraf dat er geen podcast-render of transcriptie loopt.
3. Web: dist bouwen in een schone worktree en via tar in-place kopiëren (zie
   de deploy-notities: inhoud vervangen, niet de map).
4. Optioneel `STROOM_WEB_BASE_URL=https://stroom.c4w.nl` in de stroom-api-env,
   zodat bronlinks in de markdown/Obsidian-export klikbaar zijn.
5. Okavango: nieuwe image met de vier dossiertools; er zijn geen nieuwe
   env-vars nodig (gebruikt het bestaande `STROOM_INTERNAL_TOKEN`).

Rook-test: `GET /api/research` → `[]`; in de UI een dossier starten en de
voortgang volgen (~8-10 minuten).
