"""DB-tests voor de decision-batch (services/decision_scorer.run_batch) tegen
een echte Postgres: welke items geselecteerd worden, de write-guards
(handmatige score, nieuwere summary), item-fouten en de ntfy-melding bij een
storing. De modelcall zelf is gemockt.

Draait alleen met STROOM_TEST_DB_URL, in schema `stroom_test`; zie
test_score_guards_db.py voor lokaal draaien met pgserver.
"""
import json
import os
import sys
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

sys.path.insert(0, "/app")

from services import decision_scorer as ds  # noqa: E402

pytestmark = pytest.mark.db

TEST_DB_URL = os.environ.get("STROOM_TEST_DB_URL", "")
SCHEMA = "stroom_test"
NOTES: list = []  # verstuurde ntfy-titels

_DDL = [
    f"""CREATE TABLE {SCHEMA}.items (
        id uuid PRIMARY KEY,
        title text,
        summary text,
        summary_generated_at timestamptz,
        quality_score smallint,
        quality_score_reason varchar,
        quality_score_updated_at timestamptz,
        quality_score_note text,
        quality_score_detail jsonb
    )""",
    f"""CREATE TABLE {SCHEMA}.lessons (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        item_id uuid NOT NULL,
        title text NOT NULL,
        rating smallint,
        rated_at timestamptz
    )""",
    f"""CREATE TABLE {SCHEMA}.app_settings (
        key text PRIMARY KEY,
        value jsonb NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now()
    )""",
]


class _FakeLLM:
    def __init__(self, text="Reader likes AI, Dutch politics and long-form analysis."):
        self.text = text
        self.calls = 0

    async def call_llm(self, **kwargs):
        self.calls += 1
        return self.text


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
    ds.state.update(last_run_at=None, last_result=None, outage_since=None,
                    outage_notified=False)
    NOTES.clear()

    async def fake_notify(title, body):
        NOTES.append(title)

    monkeypatch.setattr(ds, "notify", fake_notify)
    yield engine
    await engine.dispose()


def _maker(engine):
    return lambda: AsyncSession(engine)


async def _insert(engine, *, summary="Samenvatting", age_days=0, score=None, reason=None,
                  updated=False, detail=None) -> str:
    item_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO items (id, title, summary, summary_generated_at, quality_score, "
            "quality_score_reason, quality_score_updated_at, quality_score_detail) "
            "VALUES (CAST(:i AS uuid), 'Titel', :s, now() - make_interval(days => :a), :q, :r, "
            "CASE WHEN :u THEN now() END, CAST(:d AS jsonb))"
        ), {"i": item_id, "s": summary, "a": age_days, "q": score, "r": reason, "u": updated,
            "d": json.dumps(detail) if detail else None})
    return item_id


async def _set_profile(engine, text_="Reader likes AI."):
    async with AsyncSession(engine) as session:
        await ds.save_profile(session, text_, source="manual")


async def _row(engine, item_id):
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT quality_score, quality_score_reason, quality_score_detail "
            "FROM items WHERE id = CAST(:i AS uuid)"), {"i": item_id})
        return tuple(r.one())


def _fake_score(monkeypatch, score=7, during=None, error=None):
    seen = []

    async def fake(client, title, summary, profile):
        seen.append((summary, profile))
        if during is not None:
            await during()
        if error is not None:
            raise error
        return score, {"quality": {"score10": score}, "interest": None, "clickbait": 0.01}

    monkeypatch.setattr(ds, "score_item", fake)
    return seen


async def test_selects_only_recent_items_without_decision_score(db, monkeypatch):
    await _set_profile(db)
    never = await _insert(db)
    auto_null = await _insert(db, reason="auto", updated=True)
    legacy = await _insert(db, score=6, reason="auto", updated=True)   # oude cloud-score
    manual_neutral = await _insert(db, updated=True)               # PATCH null zonder reason
    manual = await _insert(db, score=3, reason="not_interesting", updated=True)
    old = await _insert(db, age_days=10)
    errored = await _insert(db, detail={"error": "400: te lang"})
    decided = await _insert(db, score=8, reason="auto", updated=True,
                            detail={"model": "nimble", "raw": 0.75})
    empty = await _insert(db, summary="")
    seen = _fake_score(monkeypatch)

    result = await ds.run_batch(_maker(db), _FakeLLM(), client=object())

    assert result["selected"] == 3 and result["scored"] == 3
    assert len(seen) == 3 and all(p == "Reader likes AI." for _, p in seen)
    for item_id in (never, auto_null, legacy):
        score, reason, detail = await _row(db, item_id)
        assert (score, reason) == (7, "auto")
        assert detail["model"] == ds.DECISION_MODEL
        assert detail["profile_version"] == ds.profile_version("Reader likes AI.")
    for item_id in (manual_neutral, old, errored, empty):
        assert (await _row(db, item_id))[0] is None
    assert (await _row(db, manual))[:2] == (3, "not_interesting")
    assert (await _row(db, decided))[0] == 8


async def test_unscored_items_go_before_legacy_scores(db, monkeypatch):
    await _set_profile(db)
    monkeypatch.setattr(ds, "BATCH_SIZE", 1)
    legacy = await _insert(db, score=6, reason="auto", updated=True, age_days=0)
    never = await _insert(db, age_days=1)
    _fake_score(monkeypatch)
    await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    assert (await _row(db, never))[0] == 7
    assert (await _row(db, legacy))[2] is None  # nog niet aan de beurt


async def test_newer_summary_during_scoring_is_not_overwritten(db, monkeypatch):
    await _set_profile(db)
    item_id = await _insert(db, summary="Oud")

    async def newer_summary():
        async with db.begin() as conn:
            await conn.execute(text("UPDATE items SET summary = 'Nieuw' WHERE id = CAST(:i AS uuid)"),
                               {"i": item_id})

    _fake_score(monkeypatch, during=newer_summary)
    result = await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    assert result["scored"] == 0 and result["skipped"] == 1
    assert (await _row(db, item_id))[0] is None


async def test_manual_patch_during_scoring_wins(db, monkeypatch):
    await _set_profile(db)
    item_id = await _insert(db)

    async def user_patches():
        async with db.begin() as conn:
            await conn.execute(text(
                "UPDATE items SET quality_score = 3, quality_score_updated_at = now() "
                "WHERE id = CAST(:i AS uuid)"), {"i": item_id})

    _fake_score(monkeypatch, during=user_patches)
    await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    assert (await _row(db, item_id))[:2] == (3, None)


async def test_item_error_is_marked_and_not_retried(db, monkeypatch):
    await _set_profile(db)
    item_id = await _insert(db)
    _fake_score(monkeypatch, error=ds.DecisionItemError("400: te lang"))
    result = await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    assert result["item_errors"] == 1
    score, _, detail = await _row(db, item_id)
    assert score is None and detail["error"].startswith("400")

    seen = _fake_score(monkeypatch)
    result = await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    assert result["selected"] == 0 and seen == []


async def test_outage_notifies_once_and_resets_after_success(db, monkeypatch):
    await _set_profile(db)
    for _ in range(4):
        await _insert(db)
    _fake_score(monkeypatch, error=ds.DecisionUnavailable("ConnectError"))

    r1 = await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    r2 = await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    assert r1["error"] and r2["error"] and r1["scored"] == 0
    assert NOTES == ["Stroom: classificatie lukte even niet"]  # één melding per storing

    _fake_score(monkeypatch)
    r3 = await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    assert r3["scored"] == 4 and ds.state["outage_notified"] is False

    await _insert(db)
    _fake_score(monkeypatch, error=ds.DecisionUnavailable("ConnectError"))
    await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    assert len(NOTES) == 2  # nieuwe storing, nieuwe melding


async def test_repeated_item_failures_become_an_outage(db, monkeypatch):
    await _set_profile(db)
    for _ in range(5):
        await _insert(db)
    _fake_score(monkeypatch, error=ds.DecisionItemFailed("500 EOF"))
    result = await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    assert result["skipped"] == ds.MAX_CONSECUTIVE_FAILURES - 1
    assert "op rij mislukt" in result["error"]
    assert NOTES == ["Stroom: classificatie lukte even niet"]


async def test_single_failure_skips_item_without_aborting(db, monkeypatch):
    await _set_profile(db)
    first = await _insert(db, age_days=0)
    second = await _insert(db, age_days=1)
    calls = []

    async def flaky(client, title, summary, profile):
        calls.append(1)
        if len(calls) == 1:
            raise ds.DecisionItemFailed("500 EOF")
        return 7, {"quality": {"score10": 7}}

    monkeypatch.setattr(ds, "score_item", flaky)
    result = await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    result.pop("calibration")
    assert result == {"selected": 2, "scored": 1, "skipped": 1, "item_errors": 0, "error": None}
    assert (await _row(db, first))[0] is None and (await _row(db, second))[0] == 7
    assert NOTES == []


async def test_profile_is_bootstrapped_from_liked_lessons(db, monkeypatch):
    item_id = await _insert(db)
    async with db.begin() as conn:
        await conn.execute(text(
            "INSERT INTO lessons (item_id, title, rating, rated_at) "
            "VALUES (CAST(:i AS uuid), 'Les over AI-beleid', 1, now())"), {"i": item_id})
    llm = _FakeLLM("Reader cares about AI policy.")
    seen = _fake_score(monkeypatch)

    await ds.run_batch(_maker(db), llm, client=object())

    assert llm.calls == 1 and seen[0][1] == "Reader cares about AI policy."
    async with AsyncSession(db) as session:
        profile = await ds.load_profile(session)
    assert profile["source"] == "auto" and profile["n_lessons"] == 1

    # Tweede ronde: profiel bestaat, geen nieuwe LLM-call.
    await _insert(db)
    await ds.run_batch(_maker(db), llm, client=object())
    assert llm.calls == 1


async def test_no_candidates_does_not_touch_profile_or_model(db, monkeypatch):
    llm = _FakeLLM()
    seen = _fake_score(monkeypatch)
    result = await ds.run_batch(_maker(db), llm, client=object())
    assert result["selected"] == 0 and llm.calls == 0 and seen == []


# --- Percentiel-ijking ---

async def _insert_decided(engine, raw: float, *, score=5, reason="auto", days_ago=0) -> str:
    detail = {"model": "nimble", "raw": raw, "quality": {"fraction": raw},
              "scored_at": f"{_iso_days_ago(days_ago)}"}
    item_id = await _insert(engine, score=score, reason=reason, updated=True, detail=detail)
    return item_id


def _iso_days_ago(days: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def _updated_at(engine, item_id):
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT quality_score_updated_at FROM items WHERE id = CAST(:i AS uuid)"), {"i": item_id})
        return r.scalar_one()


async def test_recalibrate_spreads_scores_over_1_to_10(db, monkeypatch):
    monkeypatch.setattr(ds, "CALIBRATION_MIN", 20)
    ids = [await _insert_decided(db, raw=0.60 + i * 0.002) for i in range(100)]  # 0.600..0.798
    manual = await _insert_decided(db, raw=0.99, score=2, reason="not_interesting")
    stale = await _insert_decided(db, raw=0.99, days_ago=60)   # buiten het venster
    before = await _updated_at(db, ids[-1])

    result = await ds.run_batch(_maker(db), _FakeLLM(), client=object())

    cal = result["calibration"]
    assert cal["method"] == "percentile" and cal["n"] == 101  # incl. handmatig, excl. oud
    top, _, top_detail = await _row(db, ids[-1])
    assert top == 10  # 0.798 zit boven 100 van de 101 referentiewaarden
    assert top_detail["calibration"]["method"] == "percentile"
    assert top_detail["calibration"]["n"] == 101
    assert (await _row(db, ids[0]))[0] == 1
    scores = [(await _row(db, i))[0] for i in ids]
    assert set(scores) == set(range(1, 11)) and scores == sorted(scores)
    assert (await _row(db, manual))[:2] == (2, "not_interesting")   # niet aangeraakt
    assert (await _row(db, stale))[0] == 5                           # niet aangeraakt
    assert await _updated_at(db, ids[-1]) == before                  # geen nieuwe beoordeling

    again = await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    assert again["calibration"]["updated"] == 0  # idempotent


async def test_top_5_percent_gets_a_10(db, monkeypatch):
    monkeypatch.setattr(ds, "CALIBRATION_MIN", 20)
    ids = [await _insert_decided(db, raw=i / 100) for i in range(100)]
    await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    scores = [(await _row(db, i))[0] for i in ids]
    assert scores.count(10) == 6 and scores.count(9) == 10  # pct >= .95 en >= .85


async def test_below_minimum_keeps_linear_scores(db, monkeypatch):
    monkeypatch.setattr(ds, "CALIBRATION_MIN", 200)
    ids = [await _insert_decided(db, raw=0.5 + i * 0.01, score=7) for i in range(10)]
    result = await ds.run_batch(_maker(db), _FakeLLM(), client=object())
    assert result["calibration"] == {"method": "linear", "n": 10, "updated": 0}
    assert [(await _row(db, i))[0] for i in ids] == [7] * 10
