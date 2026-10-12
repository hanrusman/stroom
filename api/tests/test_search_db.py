"""DB-tests voor zoeken (services/search_index + migratie 024) tegen een echte
Postgres met pgvector: NL/EN-stemming, de embed-batch (incl. her-embedden na
een nieuwe summary en de race-guard) en de hybride RRF-fusie. De sidecar is
gemockt met vaste vectoren per onderwerp.

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
from sqlmodel.ext.asyncio.session import AsyncSession

sys.path.insert(0, "/app")

from services import search_index as si  # noqa: E402

pytestmark = pytest.mark.db

TEST_DB_URL = os.environ.get("STROOM_TEST_DB_URL", "")
SCHEMA = "stroom_test"
MIGRATION = (Path(__file__).resolve().parents[2]
             / "schema" / "migrations" / "024-search-stemming-embeddings.sql")

# Subset van `items`/`sources` zoals vóór 024, incl. de oude 'simple'-kolom.
_DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;
CREATE SCHEMA {SCHEMA};
CREATE TYPE item_format AS ENUM ('article','podcast','video');
CREATE TYPE item_status AS ENUM ('new','pinned','later','archived');
CREATE TABLE sources (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE items (
    id uuid PRIMARY KEY,
    source_id uuid NOT NULL REFERENCES sources(id),
    title text NOT NULL,
    description text,
    summary text,
    summary_generated_at timestamptz,
    transcript text,
    format item_format,
    status item_status NOT NULL DEFAULT 'new',
    published_at timestamptz,
    search_tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(summary, ''))) STORED
);
CREATE INDEX idx_items_search_tsv ON items USING gin (search_tsv);
"""

# Nep-sidecar: één as per onderwerp, zodat afstanden voorspelbaar zijn.
_TOPICS = {"wielrennen": 0, "fiets": 0, "verkiezing": 1, "kabinet": 1, "koken": 2}


def _fake_vector(t: str) -> list[float]:
    v = [0.0] * 384
    hits = [ax for word, ax in _TOPICS.items() if word in t.lower()]
    for ax in hits:
        v[ax] = 1.0
    if not hits:
        v[383] = 1.0
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def _asyncpg_dsn(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(scheme="postgresql"))


@pytest.fixture
async def db(monkeypatch):
    if not TEST_DB_URL:
        pytest.skip("STROOM_TEST_DB_URL niet gezet")
    # Rauwe asyncpg-connectie: de migratie is een multi-statement script.
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL),
                                 server_settings={"search_path": f"{SCHEMA}, public"})
    try:
        await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await conn.execute(_DDL)
    finally:
        await conn.close()
    engine = create_async_engine(
        TEST_DB_URL, connect_args={"server_settings": {"search_path": f"{SCHEMA}, public"}})

    async def fake_embed(client, texts, prefix, timeout):
        fake_embed.calls.append((prefix, list(texts)))
        return [_fake_vector(t) for t in texts]
    fake_embed.calls = []
    monkeypatch.setattr(si, "embed", fake_embed)
    monkeypatch.setattr(si, "EMBED_SERVICE_URL", "http://fake-embed")
    yield engine, fake_embed
    await engine.dispose()


def _statements(sql: str) -> list[str]:
    """Splits zoals psql: op een ';' aan het regeleinde, niet binnen $$-blokken.
    Eén statement per execute, zodat de DO-backfill mag committen en
    CREATE INDEX CONCURRENTLY niet in een impliciete transactie valt."""
    out, cur, in_body = [], [], False
    for line in sql.splitlines():
        if line.lstrip().startswith("--"):
            continue
        cur.append(line)
        if line.count("$$") % 2:
            in_body = not in_body
        if not in_body and line.rstrip().endswith(";"):
            out.append("\n".join(cur))
            cur = []
    assert not "".join(cur).strip(), "migratie eindigt niet op ';'"
    return out


async def _migrate(engine) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL),
                                 server_settings={"search_path": f"{SCHEMA}, public"})
    try:
        for stmt in _statements(MIGRATION.read_text()):
            await conn.execute(stmt)
    finally:
        await conn.close()


async def _insert(engine, title, *, summary=None, fmt="article", status="new",
                  days_ago=0) -> str:
    item_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO sources (id, name) VALUES ('00000000-0000-0000-0000-000000000001', 'Bron') "
            "ON CONFLICT DO NOTHING"))
        await conn.execute(text(
            "INSERT INTO items (id, source_id, title, summary, summary_generated_at, format, "
            "status, published_at) VALUES (CAST(:i AS uuid), "
            "'00000000-0000-0000-0000-000000000001', :t, :s, "
            "CASE WHEN CAST(:s AS text) IS NOT NULL THEN now() END, CAST(:f AS item_format), "
            "CAST(:st AS item_status), now() - make_interval(days => :d))"
        ), {"i": item_id, "t": title, "s": summary, "f": fmt, "st": status, "d": days_ago})
    return item_id


def _maker(engine):
    return lambda: AsyncSession(engine)


async def _search(engine, q, mode="hybrid", fmt=None, limit=20):
    qvec = await si.embed_query(None, q) if mode != "keyword" else None
    async with AsyncSession(engine) as s:
        rows = await si.search(s, q, qvec, fmt, limit, mode)
    return [(r[1], r[7]) for r in rows]


async def _embed_all(engine) -> None:
    while await si.embed_batch(_maker(engine), None):
        pass


# --- stemming ---

async def test_stemming_vindt_nl_en_en_verbuigingen(db):
    engine, _ = db
    await _insert(engine, "De verkiezingen in Nederland")
    await _insert(engine, "Running the elections in Brazil")
    await _migrate(engine)

    assert [t for t, _ in await _search(engine, "verkiezing", mode="keyword")] == [
        "De verkiezingen in Nederland"]
    assert [t for t, _ in await _search(engine, "election", mode="keyword")] == [
        "Running the elections in Brazil"]
    assert [t for t, _ in await _search(engine, "run", mode="keyword")] == [
        "Running the elections in Brazil"]


async def test_backfill_loopt_over_meerdere_batches(db):
    engine, _ = db
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO sources (id, name) VALUES ('00000000-0000-0000-0000-000000000001', 'Bron')"))
        await conn.execute(text(
            "INSERT INTO items (id, source_id, title) SELECT gen_random_uuid(), "
            "'00000000-0000-0000-0000-000000000001', 'Verkiezingen ' || g "
            "FROM generate_series(1, 450) g"))
    await _migrate(engine)

    async with engine.connect() as conn:
        missing = (await conn.execute(text(
            "SELECT count(*) FROM items WHERE search_tsv IS NULL"))).scalar()
    assert missing == 0
    assert len(await _search(engine, "verkiezing", mode="keyword", limit=100)) == 100


async def test_trigger_houdt_nieuwe_en_gewijzigde_items_bij(db):
    engine, _ = db
    await _migrate(engine)
    item = await _insert(engine, "Nieuw item na de migratie")
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE items SET summary = 'Over de verkiezingen' WHERE id = CAST(:i AS uuid)"),
            {"i": item})

    assert [t for t, _ in await _search(engine, "verkiezing", mode="keyword")] == [
        "Nieuw item na de migratie"]
    async with engine.connect() as conn:
        cols = (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = 'items' AND column_name LIKE 'search_tsv%'"),
            {"s": SCHEMA})).scalars().all()
    assert cols == ["search_tsv"]


async def test_frase_en_uitsluiting_blijven_werken(db):
    engine, _ = db
    await _insert(engine, "Tour de France etappe", summary="Pogačar wint de bergetappe")
    await _insert(engine, "Tour van het kabinet", summary="Bezuinigingen op zorg")
    await _migrate(engine)

    assert [t for t, _ in await _search(engine, '"tour de france"', mode="keyword")] == [
        "Tour de France etappe"]
    assert [t for t, _ in await _search(engine, "tour -kabinet", mode="keyword")] == [
        "Tour de France etappe"]


async def test_uitsluiting_geldt_voor_beide_stemvarianten(db):
    engine, _ = db
    await _insert(engine, "Tour runs")
    await _insert(engine, "Tour de France")
    await _migrate(engine)

    assert "Tour runs" in [t for t, _ in await _search(engine, "running", mode="keyword")]
    assert [t for t, _ in await _search(engine, "tour -running", mode="keyword")] == [
        "Tour de France"]
    assert [t for t, _ in await _search(engine, 'tour -"tour runs"', mode="keyword")] == [
        "Tour de France"]


async def test_engelse_frase_matcht_achter_in_lang_transcript(db):
    engine, _ = db
    item = await _insert(engine, "Lange podcast")
    await _migrate(engine)
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE items SET transcript = repeat('woord ', 10000) || 'running elections' "
            "WHERE id = CAST(:i AS uuid)"), {"i": item})

    assert await _search(engine, '"run election"', mode="keyword") == [
        ("Lange podcast", "keyword")]


# --- embed-batch ---

async def _set(engine, item, **cols) -> None:
    sets = ", ".join(f"{c} = :{c}" for c in cols)
    async with engine.begin() as conn:
        await conn.execute(text(f"UPDATE items SET {sets} WHERE id = CAST(:i AS uuid)"),
                           {"i": item, **cols})


async def test_embed_batch_vult_vectoren_en_embedt_opnieuw_na_nieuwe_summary(db):
    engine, fake = db
    item = await _insert(engine, "Zonder samenvatting")
    await _migrate(engine)

    await _embed_all(engine)
    assert fake.calls[-1] == ("passage", ["Zonder samenvatting"])
    assert await si.embed_batch(_maker(engine), None) == 0  # niets meer te doen

    await _set(engine, item, summary="Over wielrennen")
    assert await si.embed_batch(_maker(engine), None) == 1
    assert fake.calls[-1][1] == ["Zonder samenvatting\n\nOver wielrennen"]


async def test_embed_batch_embedt_opnieuw_na_wijziging_van_titel_of_description(db):
    engine, fake = db
    item = await _insert(engine, "Wielrennen")
    await _migrate(engine)
    await _embed_all(engine)

    await _set(engine, item, title="Koken")
    assert await si.embed_batch(_maker(engine), None) == 1
    assert fake.calls[-1][1] == ["Koken"]
    assert await _search(engine, "koken", mode="semantic") == [("Koken", "semantic")]

    await _set(engine, item, description="Stoofpot")
    assert await si.embed_batch(_maker(engine), None) == 1
    assert fake.calls[-1][1] == ["Koken\n\nStoofpot"]

    # Ongewijzigde passage (zelfde titel, transcript buiten de passage): geen werk.
    await _set(engine, item, title="Koken", transcript="lang transcript")
    assert await si.embed_batch(_maker(engine), None) == 0


async def test_embed_batch_schrijft_niet_over_een_nieuwere_summary(db, monkeypatch):
    engine, fake = db
    item = await _insert(engine, "Item", summary="oud")
    await _migrate(engine)

    async def embed_during_new_summary(client, texts, prefix, timeout):
        await _set(engine, item, summary="nieuw")
        return [_fake_vector(t) for t in texts]
    monkeypatch.setattr(si, "embed", embed_during_new_summary)
    await si.embed_batch(_maker(engine), None)

    async with engine.connect() as conn:
        emb = (await conn.execute(text(
            "SELECT search_embedding FROM items WHERE id = CAST(:i AS uuid)"), {"i": item})).scalar()
    assert emb is None
    assert await si.embed_batch(_maker(engine), None) == 1  # volgende ronde: nieuwe summary


# --- hybride zoeken ---

async def test_semantisch_vindt_items_zonder_woordmatch(db):
    engine, _ = db
    await _insert(engine, "Tour de France", summary="Alles over wielrennen")
    await _insert(engine, "Stoofpot", summary="Recept voor koken in de winter")
    await _migrate(engine)
    await _embed_all(engine)

    # 'fiets' staat nergens in de tekst, maar ligt op dezelfde as als wielrennen.
    assert await _search(engine, "fiets", mode="keyword") == []
    assert await _search(engine, "fiets") == [("Tour de France", "semantic")]


async def test_hybride_zet_match_in_beide_lijsten_bovenaan(db):
    engine, _ = db
    await _insert(engine, "Kabinet valt", summary="De verkiezing komt eraan", days_ago=5)
    await _insert(engine, "Nieuwe fiets", summary="Kabinet koopt fietsen", days_ago=0)
    await _insert(engine, "Gearchiveerd kabinet", summary="verkiezing", status="archived")
    await _insert(engine, "Podcast over het kabinet", summary="verkiezing", fmt="podcast")
    await _migrate(engine)
    await _embed_all(engine)

    hits = await _search(engine, "kabinet", fmt="article")
    assert hits[0] == ("Kabinet valt", "both")
    assert ("Nieuwe fiets", "keyword") in hits
    assert all(t not in ("Gearchiveerd kabinet", "Podcast over het kabinet") for t, _ in hits)


async def test_zonder_query_vector_valt_hybride_terug_op_keyword(db):
    engine, _ = db
    await _insert(engine, "Kabinet valt")
    await _migrate(engine)
    await _embed_all(engine)

    async with AsyncSession(engine) as s:
        rows = await si.search(s, "kabinet", None, None, 10, "hybrid")
        assert [(r[1], r[7]) for r in rows] == [("Kabinet valt", "keyword")]
        assert await si.search(s, "kabinet", None, None, 10, "semantic") == []


async def test_hybride_respecteert_uitsluiting_in_semantische_tak(db):
    engine, fake = db
    await _insert(engine, "Tour de France", summary="wielrennen")
    item = await _insert(engine, "Etappe in Den Haag", summary="wielrennen")
    await _migrate(engine)
    # 'kabinet' staat alleen in de description: in search_tsv, niet in de passage.
    await _set(engine, item, description="Langs het kabinet")
    await _embed_all(engine)

    assert {t for t, _ in await _search(engine, "fiets")} == {
        "Tour de France", "Etappe in Den Haag"}
    assert await _search(engine, "fiets -kabinet") == [("Tour de France", "semantic")]
    assert fake.calls[-1] == ("query", ["fiets"])


async def test_uitsluiting_onder_or_geldt_alleen_voor_die_tak(db):
    engine, _ = db
    await _insert(engine, "Fiets kabinet")
    await _insert(engine, "Koken kabinet")
    await _insert(engine, "Koken thuis")
    await _migrate(engine)

    # websearch: fiets | (koken & !kabinet)
    assert {t for t, _ in await _search(engine, "fiets OR koken -kabinet", mode="keyword")} == {
        "Fiets kabinet", "Koken thuis"}


async def test_minteken_binnen_frase_is_geen_uitsluiting(db):
    engine, fake = db
    await _insert(engine, "Curl -X POST uitgelegd")
    await _insert(engine, "Curl GET")
    await _migrate(engine)
    await _embed_all(engine)

    assert [t for t, _ in await _search(engine, '"curl -X POST"', mode="keyword")] == [
        "Curl -X POST uitgelegd"]
    await _search(engine, '"curl -X POST"')
    assert fake.calls[-1] == ("query", ['"curl -X POST"'])


async def test_frase_met_dubbel_stopwoord(db):
    engine, _ = db
    await _insert(engine, "De verkiezingen in Nederland")
    await _insert(engine, "Verkiezingen Nederland")  # afstand 1, niet 2
    await _migrate(engine)

    # 'in' is in beide talen een stopwoord: de frase wordt 'verkiez' <2> 'nederland'.

    assert [t for t, _ in await _search(engine, '"verkiezing in nederland"', mode="keyword")] == [
        "De verkiezingen in Nederland"]


@pytest.mark.parametrize("title,q", [
    ("Waarom open-source wint", "open-source"),
    ("Nieuwe data-centers in Groningen", "data-centers"),
    ("Covid-19 cijfers", "covid-19"),
])
async def test_samengestelde_woorden_matchen_de_index(db, title, q):
    engine, _ = db
    await _insert(engine, title)
    await _migrate(engine)

    assert [t for t, _ in await _search(engine, q, mode="keyword")] == [title]
