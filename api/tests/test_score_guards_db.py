"""Regressietests voor de score-guards, tegen een echte Postgres.

Dekt de races rond auto-scoring: handmatige feedback zonder reason, een
handmatige wijziging tussen backfill-select en -write, en een nieuwere
summary vóórdat de background-scorer of de backfill schrijft.

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

# Subset van `items`: alleen de kolommen die scoring en backfill raken.
_DDL = f"""
CREATE TABLE {SCHEMA}.items (
    id uuid PRIMARY KEY,
    title text,
    summary text,
    transcript text,
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    quality_score smallint,
    quality_score_reason varchar,
    quality_score_updated_at timestamptz,
    quality_score_note text
)
"""


@pytest.fixture
async def db(monkeypatch):
    if not TEST_DB_URL:
        pytest.skip("STROOM_TEST_DB_URL niet gezet")
    engine = create_async_engine(
        TEST_DB_URL, connect_args={"server_settings": {"search_path": SCHEMA}})
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await conn.execute(text(_DDL))
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
