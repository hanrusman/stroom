# stroom-api tests

Tests run **inside the live `stroom-api` container** — there is no separate
test database. Unit tests are pure Python; integration tests hit the real
running API on `localhost:8000` inside the container.

## Eerste keer setup

`pytest` zit niet in de production image. Installeer dev-deps eenmalig in
de draaiende container:

```bash
docker exec -u root stroom-api pip install -r /app/requirements-dev.txt
```

(Bij container-rebuild verdwijnt dit. Pas de Dockerfile aan met een dev-stage
als dit te vaak terugkomt.)

## Tests draaien

```bash
# Alle tests
docker exec -w /app stroom-api pytest tests -v

# Alleen unit (snel, ~1s)
docker exec -w /app stroom-api pytest tests -v -m unit

# Alleen integratie (~3-5 min, hit live API + refresht 86 sources)
docker exec -w /app stroom-api pytest tests -v -m integration
```

## Test-types

### `test_pure.py` — unit
Pure helper-functies (`_feed_media_url`, `_feed_thumb_url`,
`_feed_first_text`). Geen DB, geen netwerk. Snel.

### `test_cron_nightly.py` — integration
Hit `POST /admin/cron/nightly` op de draaiende API.

**Side effect:** elke run refresht alle 86 actieve sources (~60s/aanroep) en
kan items in de transcribe-queue zetten. Veilig om te re-runnen — het
endpoint is idempotent op de filter (alleen items die nog niet
queued/transcribing/summarizing zijn worden opgepakt).

## Wat is hier nog niet getest

Laag 2 (in PLAN.md gepland):
- DB-fixture-based tests voor `_refresh_one`, `_process_next_queued`, queue-statemachine
- Auth-flow (login, session, CSRF)
- Volledige summarize-flow (LLM mocked)

## Conventies

- Marker `@pytest.mark.unit` of `@pytest.mark.integration` op elke test
- Geen wijzigingen aan productie-data zonder rollback in fixtures
- Timeouts: 5 min default voor cron-calls, 30s voor andere endpoints
