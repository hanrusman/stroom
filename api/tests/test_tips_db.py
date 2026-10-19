"""DB-tests voor tips-mining (services/tips_service.py + migratie 025) tegen een
echte Postgres, met een nep-LLM. Draait alleen met STROOM_TEST_DB_URL, in schema
`stroom_test`; zie test_score_guards_db.py voor lokaal draaien met pgserver.
"""
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

sys.path.insert(0, "/app")

from services import tips_service as ts  # noqa: E402
from services.tips_prompts import EXTRACT_SYSTEM  # noqa: E402

pytestmark = pytest.mark.db

TEST_DB_URL = os.environ.get("STROOM_TEST_DB_URL", "")
SCHEMA = "stroom_test"
MIGRATION = Path(__file__).resolve().parents[2] / "schema" / "migrations" / "025-tips.sql"
SOURCE = "00000000-0000-0000-0000-000000000001"

_DDL = f"""
CREATE SCHEMA {SCHEMA};
CREATE TYPE content_kind AS ENUM ('rss', 'podcast', 'youtube');
CREATE TABLE sources (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE items (id uuid PRIMARY KEY, source_id uuid NOT NULL REFERENCES sources(id),
                    type content_kind NOT NULL, title text NOT NULL, transcript text,
                    published_at timestamptz);
INSERT INTO sources VALUES ('{SOURCE}', 'Show A');
"""


def _asyncpg_dsn(url: str) -> str:
    return urlunsplit(urlsplit(url)._replace(scheme="postgresql"))


class FakeLLM:
    """Geeft per prompt-soort een vast antwoord en telt de aanroepen."""

    def __init__(self, tips=None, drop_titles=(), fail_status=None, extract_raw=None,
                 verify_raw=None):
        self.tips = tips if tips is not None else [
            {"title": "Dune", "category": "book", "creator": "Frank Herbert",
             "recommended_by": "Jan", "strength": "strong", "why": "Prachtig", "quote": "Lees Dune"}]
        self.drop_titles = set(drop_titles)
        self.fail_status = fail_status
        self.extract_raw = extract_raw  # vast ruw antwoord, bv. een verkeerd schema
        self.verify_raw = verify_raw
        self.extract_calls = 0
        self.verify_batches: list[list[dict]] = []

    async def call_llm(self, model, messages, temperature=0.7, response_format="text",
                       timeout=180.0, max_tokens=None):
        if self.fail_status:
            raise HTTPException(status_code=self.fail_status, detail="nep-fout")
        if messages[0]["content"] == EXTRACT_SYSTEM:
            self.extract_calls += 1
            return self.extract_raw if self.extract_raw is not None else json.dumps({"tips": self.tips})
        batch = [json.loads(line) for line in messages[1]["content"].splitlines()]
        self.verify_batches.append(batch)
        if self.verify_raw is not None:
            return self.verify_raw
        return json.dumps({"drop": [b["id"] for b in batch if b["title"] in self.drop_titles],
                           "fix": []})


@pytest.fixture
async def db():
    if not TEST_DB_URL:
        pytest.skip("STROOM_TEST_DB_URL niet gezet")
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL),
                                 server_settings={"search_path": f"{SCHEMA}, public"})
    try:
        await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await conn.execute(_DDL)
        await conn.execute(MIGRATION.read_text())
    finally:
        await conn.close()
    engine = create_async_engine(
        TEST_DB_URL, connect_args={"server_settings": {"search_path": f"{SCHEMA}, public"}})
    yield engine, sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _item(engine, *, kind="podcast", transcript="x" * 7000, days_ago=0) -> str:
    item_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO items (id, source_id, type, title, transcript, published_at) VALUES "
            "(CAST(:i AS uuid), CAST(:s AS uuid), CAST(:k AS content_kind), 'Aflevering', :t, "
            "now() - make_interval(days => :d))"
        ), {"i": item_id, "s": SOURCE, "k": kind, "t": transcript, "d": days_ago})
    return item_id


async def _scan_row(engine, item_id: str, status: str, attempts: int, hours_ago: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO tip_scans (item_id, status, attempts, scanned_at) VALUES "
            "(CAST(:i AS uuid), :st, :a, now() - make_interval(hours => :h))"
        ), {"i": item_id, "st": status, "a": attempts, "h": hours_ago})


async def _fetch(engine, sql: str, **params):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).all()


async def test_pick_items_selects_new_and_retryable(db):
    engine, maker = db
    new = await _item(engine, days_ago=1)
    newest = await _item(engine, kind="youtube", days_ago=0)
    await _item(engine, kind="rss")
    await _item(engine, transcript="kort")
    done = await _item(engine)
    retry = await _item(engine, days_ago=5)
    too_soon = await _item(engine)
    gave_up = await _item(engine)
    await _scan_row(engine, done, "done", 1, 48)
    await _scan_row(engine, retry, "failed", 2, 25)
    await _scan_row(engine, too_soon, "failed", 1, 2)
    await _scan_row(engine, gave_up, "failed", 3, 48)
    async with maker() as s:
        assert await ts.pick_items(s, 10) == [newest, new, retry]
        assert await ts.pick_items(s, 1) == [newest]


async def test_scan_item_stores_mentions_and_rescan_replaces(db):
    engine, maker = db
    item = await _item(engine, transcript="y" * 7000)  # 2 vensters
    llm = FakeLLM()
    res = await ts.scan_item(maker, llm, item, "nep-model")
    assert res == {"item_id": item, "status": "done", "windows": 2, "tips": 2}
    rows = await _fetch(engine, "SELECT window_offset, title_key, model FROM tip_mentions ORDER BY 1")
    assert [tuple(r) for r in rows] == [(0, "dune", "nep-model"), (ts.windows("y" * 7000)[1][0], "dune", "nep-model")]
    await ts.scan_item(maker, llm, item, "nep-model")
    assert (await _fetch(engine, "SELECT count(*) FROM tip_mentions"))[0][0] == 2
    scan = (await _fetch(engine, "SELECT status, windows, attempts, error FROM tip_scans"))[0]
    assert tuple(scan) == ("done", 2, 2, None)


async def test_scan_item_failure_marks_failed_without_mentions(db):
    engine, maker = db
    item = await _item(engine)
    res = await ts.scan_item(maker, FakeLLM(fail_status=400), item, "nep-model")
    assert res["status"] == "failed"
    scan = (await _fetch(engine, "SELECT status, attempts, error FROM tip_scans"))[0]
    assert scan[0] == "failed" and scan[1] == 1 and "HTTPException" in scan[2]
    assert (await _fetch(engine, "SELECT count(*) FROM tip_mentions"))[0][0] == 0


async def test_verify_new_works_only_scored_candidates_and_once(db):
    engine, maker = db
    tips = [{"title": "Dune", "category": "book", "strength": "strong"},
            {"title": "Muse", "category": "software", "strength": "medium"},
            {"title": "Terloops", "category": "book", "strength": "weak"}]
    item = await _item(engine, transcript="z" * 300)
    llm = FakeLLM(tips=tips, drop_titles={"Muse"})
    await ts.scan_item(maker, llm, item, "nep-model")
    assert await ts.verify_new_works(maker, llm, "verify-model") == 2
    assert {b["title"] for b in llm.verify_batches[0]} == {"Dune", "Muse"}  # Terloops: score 1
    works = await _fetch(engine, "SELECT category, title_key, keep, model FROM tip_works ORDER BY 1")
    assert [tuple(r) for r in works] == [("book", "dune", True, "verify-model"),
                                         ("software", "muse", False, "verify-model")]
    assert await ts.verify_new_works(maker, llm, "verify-model") == 0


async def test_run_tips_job_end_to_end(db, monkeypatch):
    engine, maker = db
    monkeypatch.setenv("TIPS_MODEL", "nep-model")
    a = await _item(engine, transcript="a" * 300)
    b = await _item(engine, transcript="b" * 300)
    res = await ts.run_tips_job(maker, FakeLLM(), max_items=10)
    assert res["ok"] is True and res["items"] == 2 and res["done"] == 2 and res["tips"] == 2
    assert res["verified"] == 1 and res["finished_at"] and res["model"] == "nep-model"
    assert ts.last_result["done"] == 2
    async with maker() as s:
        works = ts.aggregate(await ts.load_mentions(s), await ts.load_works(s))
    (w,) = works
    assert w["title"] == "Dune" and w["episodes"] == 2 and w["creator"] == "Frank Herbert"
    assert {m["item_id"] for m in w["mentions"]} == {a, b}
    assert w["who"] == ["Jan (Show A)"]
    again = await ts.run_tips_job(maker, FakeLLM(), max_items=10)
    assert again["items"] == 0


async def test_scan_item_invalid_schema_is_failed_not_done(db):
    """Review #79 punt 2: een JSON-object zonder tips-lijst is een mislukte scan, geen lege."""
    engine, maker = db
    item = await _item(engine, transcript="q" * 300)
    llm = FakeLLM(extract_raw='{"foo": 1}')
    res = await ts.scan_item(maker, llm, item, "nep-model")
    assert res["status"] == "failed"
    assert llm.extract_calls == 2  # één nieuwe poging, daarna opgeven
    scan = (await _fetch(engine, "SELECT status, attempts, error FROM tip_scans"))[0]
    assert scan[0] == "failed" and scan[1] == 1 and "tips" in scan[2]
    assert (await _fetch(engine, "SELECT count(*) FROM tip_mentions"))[0][0] == 0


async def test_verify_invalid_schema_saves_nothing(db):
    """Review #79 punt 2: {"error": ...} mag niet leiden tot keep=True voor de hele batch."""
    engine, maker = db
    item = await _item(engine, transcript="v" * 300)
    llm = FakeLLM(verify_raw='{"error": "cannot verify"}')
    await ts.scan_item(maker, llm, item, "nep-model")
    assert await ts.verify_new_works(maker, llm, "verify-model") == 0
    assert (await _fetch(engine, "SELECT count(*) FROM tip_works"))[0][0] == 0
    # De volgende run probeert het opnieuw.
    llm.verify_raw = None
    assert await ts.verify_new_works(maker, llm, "verify-model") == 1


async def test_same_title_different_category_are_separate_works(db):
    """Review #79 punt 1: boek Dune en film Dune, ook binnen één aflevering, blijven twee werken."""
    engine, maker = db
    tips = [{"title": "Dune", "category": "book", "creator": "Frank Herbert", "strength": "strong"},
            {"title": "Dune", "category": "film", "creator": "Denis Villeneuve", "strength": "strong"}]
    item = await _item(engine, transcript="d" * 300)
    llm = FakeLLM(tips=tips)
    await ts.scan_item(maker, llm, item, "nep-model")
    assert await ts.verify_new_works(maker, llm, "verify-model") == 2
    works = await _fetch(engine, "SELECT category, title_key FROM tip_works ORDER BY 1")
    assert [tuple(r) for r in works] == [("book", "dune"), ("film", "dune")]
    async with maker() as s:
        agg = ts.aggregate(await ts.load_mentions(s), await ts.load_works(s))
    assert sorted((w["category"], w["creator"], w["episodes"]) for w in agg) == [
        ("book", "Frank Herbert", 1), ("film", "Denis Villeneuve", 1)]


def _import_script():
    """api/scripts/import_tips.py als module (scripts/ is geen package)."""
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "import_tips.py"
    spec = importlib.util.spec_from_file_location("import_tips", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_DUNE_BOTH = [{"title": "Dune", "category": "book", "creator": "Frank Herbert", "strength": "strong"},
              {"title": "Dune", "category": "film", "creator": "Denis Villeneuve", "strength": "strong"}]
_DUNE_VERDICT = {"tk": "dune", "keep": True, "title": "Dune", "creator": "Frank Herbert",
                 "canon": "book", "conf": "high", "model": "import-2026-10"}


async def test_import_keeps_book_and_film_from_one_window(db):
    """Review #79 ronde 2, punt 1: boek én film Dune in één venster blijven twee vermeldingen."""
    engine, _ = db
    item = await _item(engine)
    imp = _import_script()
    rows = imp.mention_rows(item, [{"offset": 0, "model": "gemma", "tips": _DUNE_BOTH}])
    assert sorted(r["cat"] for r in rows) == ["book", "film"]
    async with engine.connect() as conn:
        n = await imp.run_import(conn, {item: [{"offset": 0, "model": "gemma", "tips": _DUNE_BOTH}]},
                                 [_DUNE_VERDICT])
    assert n["mentions"] == 2
    cats = await _fetch(engine, "SELECT category FROM tip_mentions ORDER BY 1")
    assert [r[0] for r in cats] == ["book", "film"]
    # Het batch-oordeel (over het boek) geldt alleen voor het boek; de film verifieert de job.
    works = await _fetch(engine, "SELECT category, title_key, canon_category FROM tip_works")
    assert [tuple(r) for r in works] == [("book", "dune", "book")]


async def test_import_restart_restores_missing_verifications(db):
    """Review #79 ronde 2, punt 2: een import die stopte vóór de verificaties, maakt een
    herstart af, ook al zijn de items dan al gescand."""
    engine, _ = db
    item = await _item(engine)
    windows = {item: [{"offset": 0, "model": "gemma", "tips": _DUNE_BOTH}]}
    imp = _import_script()
    async with engine.connect() as conn:  # onderbroken: mentions/scans vastgelegd, geen verificaties
        first = await imp.run_import(conn, windows, [])
    assert first["items"] == 1 and first["works"] == 0
    async with engine.connect() as conn:
        again = await imp.run_import(conn, windows, [_DUNE_VERDICT])
    assert again["items"] == 0 and again["scanned"] == 1 and again["works"] == 1
    assert (await _fetch(engine, "SELECT count(*) FROM tip_works"))[0][0] == 1
    assert (await _fetch(engine, "SELECT count(*) FROM tip_mentions"))[0][0] == 2  # niet dubbel


async def test_import_dry_run_counts_without_writing(db):
    engine, _ = db
    item = await _item(engine)
    imp = _import_script()
    async with engine.connect() as conn:
        n = await imp.run_import(conn, {item: [{"offset": 0, "model": "gemma", "tips": _DUNE_BOTH}]},
                                 [_DUNE_VERDICT], dry_run=True)
    assert n == {"items": 1, "missing": 0, "scanned": 0, "mentions": 2, "works": 1}
    for table in ("tip_mentions", "tip_scans", "tip_works"):
        assert (await _fetch(engine, f"SELECT count(*) FROM {table}"))[0][0] == 0
