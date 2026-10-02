"""Regressietests voor de score-guards, tegen een echte Postgres.

Dekt de races rond auto-scoring: handmatige feedback zonder reason, een
handmatige wijziging tussen backfill-select en -write of tijdens de
summarize-worker, en een nieuwere summary vóórdat de background-scorer of
de backfill schrijft.

Draait alleen met STROOM_TEST_DB_URL (asyncpg-URL naar een wegwerp-database),
anders skip. Alles gebeurt in schema `stroom_test`, dus ook een verkeerd
gezette URL raakt geen echte `items`. Lokaal kan het met embedded Postgres:

    pip install pgserver
    python -c "import pgserver; print(pgserver.get_server('/tmp/pg').get_uri())"
    STROOM_TEST_DB_URL='postgresql+asyncpg://postgres@/postgres?host=<socket-dir>' \\
        pytest -m db
"""
import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

sys.path.insert(0, "/app")

import main  # noqa: E402

pytestmark = pytest.mark.db

TEST_DB_URL = os.environ.get("STROOM_TEST_DB_URL", "")
SCHEMA = "stroom_test"

# Subset van `items` (+ `sources` voor de JOIN van de summarize-worker): alleen
# de kolommen die summarize, scoring en backfill raken.
_DDL = [
    f"CREATE TYPE {SCHEMA}.processing_status AS ENUM "
    "('pending','summarize_queued','summarizing','ready','failed')",
    f"CREATE TABLE {SCHEMA}.sources (id uuid PRIMARY KEY, name text NOT NULL)",
    f"""
CREATE TABLE {SCHEMA}.items (
    id uuid PRIMARY KEY,
    source_id uuid REFERENCES {SCHEMA}.sources(id),
    type varchar NOT NULL DEFAULT 'podcast',
    title text,
    summary text,
    summary_model text,
    summary_generated_at timestamptz,
    transcript text,
    description text,
    duration_seconds int,
    processing_status {SCHEMA}.processing_status NOT NULL DEFAULT 'pending',
    processing_error text,
    queued_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    quality_score smallint,
    quality_score_reason varchar,
    quality_score_updated_at timestamptz,
    quality_score_note text
)
""",
]


@pytest.fixture
async def db(monkeypatch):
    if not TEST_DB_URL:
        pytest.skip("STROOM_TEST_DB_URL niet gezet")
    engine = create_async_engine(
        TEST_DB_URL, connect_args={"server_settings": {"search_path": SCHEMA}})
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        for ddl in _DDL:
            await conn.execute(text(ddl))
    import core.db
    monkeypatch.setattr(core.db, "async_session_maker", lambda: AsyncSession(engine))
    monkeypatch.setattr(main.app.state, "http_client", None, raising=False)
    yield engine
    await engine.dispose()


async def _insert(engine, *, summary="Samenvatting", score=None, reason=None,
                  updated=False) -> str:
    item_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO items (id, title, summary, quality_score, quality_score_reason, "
            "quality_score_updated_at) "
            "VALUES (CAST(:i AS uuid), 'Titel', :s, :q, :r, CASE WHEN :u THEN now() END)"
        ), {"i": item_id, "s": summary, "q": score, "r": reason, "u": updated})
    return item_id


async def _manual_patch(engine, item_id: str, score, reason=None) -> None:
    """Dezelfde UPDATE als PATCH /huygens/items/{id}/quality-score: reason is
    daar optioneel, updated_at wordt altijd gezet."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE items SET quality_score = :q, quality_score_updated_at = NOW(), "
            "quality_score_reason = :r, quality_score_note = NULL "
            "WHERE id = CAST(:i AS uuid)"
        ), {"q": score, "r": reason, "i": item_id})


async def _score_row(engine, item_id: str) -> tuple:
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT quality_score, quality_score_reason FROM items WHERE id = CAST(:i AS uuid)"
        ), {"i": item_id})
        return tuple(r.one())


def _fake_scorer(monkeypatch, score, during=None):
    """Vervangt de LLM-scorer; `during` simuleert wat er tijdens de call gebeurt."""
    async def fake(http_client, text_, title=None):
        if during is not None:
            await during()
        return score

    monkeypatch.setattr(main, "_score_with_quality_scorer", fake)


# --- _score_item_after_summary (transcribe-callback, /summarize) ---

@pytest.mark.parametrize("score,reason,updated,expected", [
    (None, None, False, (8, "auto")),
    (5, None, False, (8, "auto")),
    (6, "auto", True, (8, "auto")),
    (None, "auto", True, (8, "auto")),
    (3, "personal_interest", True, (3, "personal_interest")),
    (3, None, True, (3, None)),
    (None, None, True, (None, None)),
], ids=[
    "nooit-gescoord",
    "oude-default-5",
    "eerdere-auto-score",
    "auto-score-gefaald",
    "handmatig-met-reason",
    "handmatig-zonder-reason",
    "handmatig-neutraal-zonder-reason",
])
async def test_background_score_only_overwrites_system_scores(
        db, monkeypatch, score, reason, updated, expected):
    item_id = await _insert(db, score=score, reason=reason, updated=updated)
    _fake_scorer(monkeypatch, 8)
    await main._score_item_after_summary(item_id, "Samenvatting", "Titel")
    assert await _score_row(db, item_id) == expected


async def test_manual_patch_during_background_scoring_wins(db, monkeypatch):
    item_id = await _insert(db)

    async def user_patches_without_reason():
        await _manual_patch(db, item_id, 2)

    _fake_scorer(monkeypatch, 8, during=user_patches_without_reason)
    await main._score_item_after_summary(item_id, "Samenvatting", "Titel")
    assert await _score_row(db, item_id) == (2, None)


async def test_score_for_outdated_summary_is_dropped(db, monkeypatch):
    item_id = await _insert(db, summary="Oude samenvatting")

    async def newer_summary_is_stored():
        async with db.begin() as conn:
            await conn.execute(text(
                "UPDATE items SET summary = 'Nieuwe samenvatting' WHERE id = CAST(:i AS uuid)"
            ), {"i": item_id})

    _fake_scorer(monkeypatch, 8, during=newer_summary_is_stored)
    await main._score_item_after_summary(item_id, "Oude samenvatting", "Titel")
    assert await _score_row(db, item_id) == (None, None)


# --- summarize-worker (_summarize_single_item) ---

class _FakeLLM:
    async def call_llm(self, model, messages, *, temperature, timeout):
        return "Nieuwe samenvatting"


async def _queue_for_summarize(engine, item_id: str) -> None:
    """Zet een _insert-item klaar zoals de summarize-queue het oppakt."""
    source_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO sources (id, name) VALUES (CAST(:src AS uuid), 'Bron')"
        ), {"src": source_id})
        await conn.execute(text(
            "UPDATE items SET source_id = CAST(:src AS uuid), transcript = 'Korte transcriptie', "
            "processing_status = 'summarizing', queued_at = now() "
            "WHERE id = CAST(:i AS uuid)"
        ), {"src": source_id, "i": item_id})


async def _run_worker(engine, item_id: str) -> None:
    ok = await main._summarize_single_item(
        item_id, _FakeLLM(), lambda: AsyncSession(engine), http_client=object())
    assert ok is True


async def _summary_row(engine, item_id: str) -> tuple:
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT summary, processing_status::text, queued_at IS NULL "
            "FROM items WHERE id = CAST(:i AS uuid)"
        ), {"i": item_id})
        return tuple(r.one())


async def test_worker_scores_never_scored_item(db, monkeypatch):
    item_id = await _insert(db, summary=None)
    await _queue_for_summarize(db, item_id)
    _fake_scorer(monkeypatch, 8)
    await _run_worker(db, item_id)
    assert await _summary_row(db, item_id) == ("Nieuwe samenvatting", "ready", True)
    assert await _score_row(db, item_id) == (8, "auto")


async def test_manual_patch_during_worker_scoring_wins(db, monkeypatch):
    item_id = await _insert(db, summary=None)
    await _queue_for_summarize(db, item_id)

    async def user_patches_without_reason():
        await _manual_patch(db, item_id, 2)

    _fake_scorer(monkeypatch, 8, during=user_patches_without_reason)
    await _run_worker(db, item_id)
    # Summary en status gaan gewoon door, de handmatige score blijft staan.
    assert await _summary_row(db, item_id) == ("Nieuwe samenvatting", "ready", True)
    assert await _score_row(db, item_id) == (2, None)


# --- /admin/quality-backfill ---

async def test_backfill_only_null_skips_manual_neutral(db):
    never_scored = await _insert(db)
    auto_failed = await _insert(db, reason="auto", updated=True)
    await _insert(db, updated=True)                              # handmatig neutraal, geen reason
    await _insert(db, reason="not_interesting", updated=True)    # handmatig neutraal, met reason
    await _insert(db, score=7, reason="auto", updated=True)      # al gescoord

    background_tasks = BackgroundTasks()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(http_client=None)))
    async with AsyncSession(db) as session:
        await main.admin_quality_backfill(
            request=request,
            body=main.QualityBackfillRequest(limit=100, only_null=True),
            background_tasks=background_tasks,
            session=session,
        )

    (task,) = background_tasks.tasks
    assert {it["id"] for it in task.args[0]} == {never_scored, auto_failed}
    # De geselecteerde summary gaat mee, voor de stale-summary-check bij de write.
    assert {it["summary"] for it in task.args[0]} == {"Samenvatting"}
    assert task.args[2] is True  # only_null gaat mee naar de write


def _backfill_items(*item_ids: str) -> list[dict]:
    """Zoals admin_quality_backfill ze aanlevert, met de summary van _insert."""
    return [{"id": i, "text": "Samenvatting", "title": "Titel", "summary": "Samenvatting"}
            for i in item_ids]


async def test_backfill_keeps_manual_change_made_after_select(db, monkeypatch):
    patched = await _insert(db)
    untouched = await _insert(db)

    async def fake_batch(http_client, items):
        # Gebruiker corrigeert handmatig terwijl de batch nog loopt.
        await _manual_patch(db, patched, 2)
        return {patched: 9, untouched: 7}

    monkeypatch.setattr(main, "_score_batch_with_quality_scorer", fake_batch)
    await main._run_quality_backfill(_backfill_items(patched, untouched), None, only_null=True)

    assert await _score_row(db, patched) == (2, None)
    assert await _score_row(db, untouched) == (7, "auto")


@pytest.mark.parametrize("only_null", [True, False])
async def test_backfill_drops_score_for_outdated_summary(db, monkeypatch, only_null):
    resummarized = await _insert(db)
    untouched = await _insert(db)

    async def fake_batch(http_client, items):
        # Een andere flow (worker, callback) slaat intussen een nieuwe summary op.
        async with db.begin() as conn:
            await conn.execute(text(
                "UPDATE items SET summary = 'Nieuwe samenvatting' WHERE id = CAST(:i AS uuid)"
            ), {"i": resummarized})
        return {resummarized: 9, untouched: 7}

    monkeypatch.setattr(main, "_score_batch_with_quality_scorer", fake_batch)
    await main._run_quality_backfill(_backfill_items(resummarized, untouched), None,
                                     only_null=only_null)

    assert await _score_row(db, resummarized) == (None, None)
    assert await _score_row(db, untouched) == (7, "auto")
