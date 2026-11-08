"""DB-tests voor dossiers (services/research_service.py + migratie 028) tegen een
echte Postgres: DbStore, Corpus.meta/content en een volledige run met nep-LLM.
Draait alleen met STROOM_TEST_DB_URL, in schema `stroom_test`; zie
test_score_guards_db.py voor lokaal draaien met pgserver.
"""
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
SOURCE = "00000000-0000-0000-0000-000000000001"

_DDL = f"""
CREATE SCHEMA {SCHEMA};
CREATE TABLE users (id uuid PRIMARY KEY);
CREATE TABLE sources (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE items (id uuid PRIMARY KEY, source_id uuid NOT NULL REFERENCES sources(id),
                    title text NOT NULL, format text, summary text, transcript text,
                    description text, author text, media_url text, external_id text,
                    published_at timestamptz);
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
