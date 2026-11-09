"""DB-tests voor dossiers (services/research_service.py + migratie 028) tegen een
echte Postgres: DbStore, Corpus.meta/content en een volledige run met nep-LLM.
Draait alleen met STROOM_TEST_DB_URL, in schema `stroom_test`; zie
test_score_guards_db.py voor lokaal draaien met pgserver.
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

sys.path.insert(0, "/app")

from services import research_service as rs  # noqa: E402
from tests.test_research_pure import FakeLLM  # noqa: E402

pytestmark = pytest.mark.db

TEST_DB_URL = os.environ.get("STROOM_TEST_DB_URL", "")
SCHEMA = "stroom_test"
MIGRATION = Path(__file__).resolve().parents[2] / "schema" / "migrations" / "028-research.sql"
MIGRATION_MOMENTS = MIGRATION.with_name("030-research-moments.sql")
SOURCE = "00000000-0000-0000-0000-000000000001"

_DDL = f"""
CREATE SCHEMA {SCHEMA};
CREATE TABLE users (id uuid PRIMARY KEY);
CREATE TABLE sources (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE items (id uuid PRIMARY KEY, source_id uuid NOT NULL REFERENCES sources(id),
                    title text NOT NULL, format text, summary text, transcript text,
                    description text, author text, media_url text, external_id text,
                    published_at timestamptz, thumbnail_url text, transcript_segments jsonb,
                    duration_seconds int);
CREATE TABLE lessons (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), item_id uuid NOT NULL,
                      idx int NOT NULL, title text NOT NULL, body text NOT NULL);
INSERT INTO sources VALUES ('{SOURCE}', 'Show A');
"""


def _asyncpg_dsn(url: str) -> str:
    return urlunsplit(urlsplit(url)._replace(scheme="postgresql"))


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
        await conn.execute(MIGRATION.read_text())  # idempotent
        await conn.execute(MIGRATION_MOMENTS.read_text())
        await conn.execute(MIGRATION_MOMENTS.read_text())  # idempotent
    finally:
        await conn.close()
    engine = create_async_engine(
        TEST_DB_URL, connect_args={"server_settings": {"search_path": f"{SCHEMA}, public"}})
    yield engine, sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _item(engine, title: str, days_ago: int = 0) -> str:
    iid = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO items (id, source_id, title, format, summary, external_id, published_at)
            VALUES (CAST(:i AS uuid), CAST(:s AS uuid), :t, 'podcast', :sum, 'https://x/' || :t,
                    now() - make_interval(days => :d))"""),
            {"i": iid, "s": SOURCE, "t": title, "sum": f"## Key takeaways\n{title} " + "x" * 3000,
             "d": days_ago})
        await conn.execute(text(
            "INSERT INTO lessons (item_id, idx, title, body) VALUES (CAST(:i AS uuid), 0, 'Les', 'Inhoud')"),
            {"i": iid})
    return iid


async def _run_row(engine, question="Hoe verandert software-inkoop?", parent=None) -> str:
    async with engine.begin() as conn:
        return (await conn.execute(text("""
            INSERT INTO research_runs (question, parent_id) VALUES (:q, CAST(:p AS uuid))
            RETURNING id::text"""), {"q": question, "p": parent})).scalar()


class PatchedCorpus(rs.Corpus):
    """Echte meta/content uit de DB; recall vast (geen FTS/vectoren in de test-DB)."""

    def __init__(self, maker, first, deeper):
        super().__init__(maker, None)
        self.first, self.deeper = first, deeper

    async def recall(self, queries):
        ids = self.first + (self.deeper if any("gat" in q for q in queries) else [])
        return [{"item_id": i, "recall_score": 1.0 / (k + 1), "queries": queries[:1]}
                for k, i in enumerate(ids)]


@pytest.fixture(autouse=True)
def _models(monkeypatch):
    monkeypatch.setattr(rs, "PLAN_MODELS", ["p1"])
    monkeypatch.setattr(rs, "SCREEN_MODELS", ["cloud-s"])
    monkeypatch.setattr(rs, "EXTRACT_MODELS", ["cloud-e"])
    monkeypatch.setattr(rs, "WRITE_MODELS", ["w1"])
    monkeypatch.setattr(rs, "CRITIQUE_MODELS", ["c1"])


async def test_store_roundtrip_and_unknown_run(db):
    engine, maker = db
    store = rs.DbStore(maker)
    rid = await _run_row(engine)
    await store.update_run(rid, status="planning", plan={"title": "T", "aspects": []},
                           progress={"stage": "planning"}, finished_at=False)
    run = await store.get_run(rid)
    assert run["status"] == "planning" and run["plan"]["title"] == "T" and run["followups"] == []
    with pytest.raises(KeyError):
        await store.get_run(str(uuid.uuid4()))


async def test_full_run_persists_every_stage_and_refresh_reuses(db):
    engine, maker = db
    first = [await _item(engine, f"Item {k}", days_ago=k) for k in range(1, 6)]
    deeper = [await _item(engine, "Extra 1")]
    store = rs.DbStore(maker)
    rid = await _run_row(engine)
    ctx = rs.Ctx(store=store, corpus=PatchedCorpus(maker, first, deeper), llm=FakeLLM(irrelevant=()))
    await rs.run_pipeline(ctx, rid)
    run = await store.get_run(rid)
    assert run["status"] == "done", run["error"]
    assert run["finished_at"] is not None and run["report"].startswith("# Dossier")
    assert run["models"]["write"] == "w1" and run["plan"]["deepen"]["queries"]
    cands = await store.load_candidates(rid)
    assert sorted(c["round"] for c in cands) == [0] * 5 + [1]
    assert all(c["screen_score"] == 3 for c in cands)
    finds = await store.load_findings(rid)
    assert len(finds) == 6
    # Bronnen op datum, met url uit external_id
    assert [s["date"] for s in run["sources"]] == sorted(s["date"] for s in run["sources"])
    assert run["sources"][0]["url"].startswith("https://x/")

    # Vernieuwing met één nieuw item: alleen dat wordt gescreend en gelezen.
    new = await _item(engine, "Item 9")
    rid2 = await _run_row(engine, parent=rid)
    llm2 = FakeLLM(irrelevant=())
    await rs.run_pipeline(rs.Ctx(store=store, corpus=PatchedCorpus(maker, first + [new], deeper),
                                 llm=llm2), rid2)
    run2 = await store.get_run(rid2)
    assert run2["status"] == "done"
    roles = [r for r, _ in llm2.calls]
    assert roles.count("extract") == 1 and "plan" not in roles and "deepen" not in roles
    assert len(await store.load_findings(rid2)) == 7

    # Verwijderen ruimt kandidaten en bevindingen op; de vernieuwing blijft bestaan.
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM research_runs WHERE id = CAST(:i AS uuid)"), {"i": rid})
        left = (await conn.execute(text(
            "SELECT count(*) FROM research_findings WHERE run_id = CAST(:i AS uuid)"), {"i": rid})).scalar()
        parent = (await conn.execute(text(
            "SELECT parent_id FROM research_runs WHERE id = CAST(:i AS uuid)"), {"i": rid2})).scalar()
    assert left == 0 and parent is None


async def test_corpus_content_includes_lessons(db):
    engine, maker = db
    iid = await _item(engine, "Met les")
    c = await rs.Corpus(maker, None).content(iid)
    assert c["lessons"] == [("Les", "Inhoud")] and c["format"] == "podcast"
    meta = await rs.Corpus(maker, None).meta([iid])
    assert meta[iid]["teaser"].startswith("Met les")


async def test_web_routes_only_show_own_and_unowned_runs(db, monkeypatch):
    """Web-routes: eigen dossiers en dossiers zonder eigenaar (Okavango) wel,
    die van een andere gebruiker niet (404, ook bij verwijderen)."""
    from fastapi import HTTPException

    from routers import research as rr

    engine, maker = db
    monkeypatch.setattr(rr, "async_session_maker", maker)
    me, other = str(uuid.uuid4()), str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO users (id) VALUES (CAST(:a AS uuid)), (CAST(:b AS uuid))"),
                           {"a": me, "b": other})
        ids = {}
        for name, owner in (("mine", me), ("theirs", other), ("okavango", None)):
            ids[name] = (await conn.execute(text("""
                INSERT INTO research_runs (question, user_id, status)
                VALUES (:q, CAST(:u AS uuid), 'done') RETURNING id::text"""),
                {"q": f"Vraag {name} over inkoop", "u": owner})).scalar()
    user = {"id": me}

    async with maker() as s:
        listed = {r["id"] for r in await rr.list_runs(limit=50, session=s, user=user)}
    assert listed == {ids["mine"], ids["okavango"]}

    assert (await rr._get(ids["mine"], user))["id"] == ids["mine"]
    assert (await rr._get(ids["okavango"], user))["id"] == ids["okavango"]
    with pytest.raises(HTTPException) as e:
        await rr._get(ids["theirs"], user)
    assert e.value.status_code == 404
    assert (await rr._get(ids["theirs"]))["id"] == ids["theirs"]  # internal: geen user

    async with maker() as s:
        with pytest.raises(HTTPException):
            await rr.delete_run(ids["theirs"], session=s, user=user)
        with pytest.raises(HTTPException):
            await rr.funnel(ids["theirs"], session=s, user=user)
        assert (await rr.delete_run(ids["mine"], session=s, user=user)) == {"ok": True}
    async with engine.begin() as conn:
        left = {r[0] for r in await conn.execute(text("SELECT id::text FROM research_runs"))}
    assert left == {ids["theirs"], ids["okavango"]}


async def test_source_media_and_moments_are_located_and_cached(db, monkeypatch):
    import json as _json

    from fastapi import HTTPException

    from routers import research as rr
    from tests.test_research_moments import SEGS
    from tests.test_research_moments import FakeLLM as MomentLLM

    engine, maker = db
    monkeypatch.setattr(rr, "async_session_maker", maker)
    me, other = str(uuid.uuid4()), str(uuid.uuid4())
    iid = str(uuid.uuid4())
    findings = [{"claim": "Meta maakte serverontwerpen open source.",
                 "quote": "we took the designs for all of our servers and network switches"},
                {"claim": "Apple houdt zijn OS gesloten.", "quote": ""}]
    sources = [{"ref": "S1", "item_id": iid, "title": "Ep 1", "source": "Show A", "format": "podcast",
                "date": "2026-10-01", "url": None, "relevance": 3, "findings": findings}]
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO users (id) VALUES (CAST(:a AS uuid)), (CAST(:b AS uuid))"),
                           {"a": me, "b": other})
        await conn.execute(text("""
            INSERT INTO items (id, source_id, title, format, media_url, transcript_segments)
            VALUES (CAST(:i AS uuid), CAST(:s AS uuid), 'Ep 1', 'podcast', 'https://x/ep1.mp3',
                    CAST(:g AS jsonb))"""), {"i": iid, "s": SOURCE, "g": _json.dumps(SEGS)})
        rid = (await conn.execute(text("""
            INSERT INTO research_runs (question, user_id, status, sources)
            VALUES ('Vraag over inkoop', CAST(:u AS uuid), 'done', CAST(:src AS jsonb))
            RETURNING id::text"""), {"u": me, "src": _json.dumps(sources)})).scalar()

    first = await rr.source_media(rid, "S1", user={"id": me})
    assert first["media_url"] == "https://x/ep1.mp3" and first["has_times"]
    assert first["moments"] == [{"t": 31.5, "exact": True}, None] and first["pending"] is True

    llm = MomentLLM({"moments": [{"i": 1, "t": "1:05"}]})
    monkeypatch.setattr(rr, "_llm", lambda request: llm)
    # Twee panelen/tabbladen tegelijk: één modelaanroep, beide krijgen hetzelfde.
    done, twin = await asyncio.gather(
        rr.source_moments(rid, request=None, ref="S1", user={"id": me}),
        rr.source_moments(rid, request=None, ref="S1", user={"id": me}))
    assert done["moments"] == [{"t": 31.5, "exact": True}, {"t": 65.0, "exact": False}]
    assert twin == done and len(llm.prompts) == 1 and not rr._MOMENT_LOCKS

    again = await rr.source_media(rid, "S1", user={"id": me})
    assert again["moments"] == done["moments"] and again["pending"] is False
    await rr.source_moments(rid, request=None, ref="S1", user={"id": me})
    assert len(llm.prompts) == 1  # uit de cache, geen tweede modelaanroep

    for call in (rr.source_media(rid, "S1", user={"id": other}),
                 rr.source_media(rid, "S9", user={"id": me})):
        with pytest.raises(HTTPException) as e:
            await call
        assert e.value.status_code == 404
