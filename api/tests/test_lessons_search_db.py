"""DB-tests voor GET /internal/lessons/search (Okavango's search_stroom_lessons)
en migratie 029, tegen een echte Postgres: losse woorden in plaats van één
letterlijke substring, NL/EN-stemming, rangschikking op aantal geraakte
termen en veldgewicht, uitsluitingen, het rating-filter, en de trigger en
backfill die lessons.search_tsv bijhouden.

Draait alleen met STROOM_TEST_DB_URL, in schema `stroom_test`; zie
test_score_guards_db.py voor lokaal draaien met pgserver.
"""
import os
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

sys.path.insert(0, "/app")

from routers.lessons import search_lessons  # noqa: E402
from tests.test_search_db import _asyncpg_dsn, _statements  # noqa: E402

pytestmark = pytest.mark.db

TEST_DB_URL = os.environ.get("STROOM_TEST_DB_URL", "")
SCHEMA = "stroom_test"
_MIGRATIONS = Path(__file__).resolve().parents[2] / "schema" / "migrations"
MIGRATIONS = [_MIGRATIONS / "024-search-stemming-embeddings.sql",
              _MIGRATIONS / "029-lessons-search-stemming.sql"]
SOURCE = "00000000-0000-0000-0000-000000000001"
ITEM = "00000000-0000-0000-0000-0000000000a1"

# Subset van items/sources/lessons zoals vóór 024 en 029.
_DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;
CREATE SCHEMA {SCHEMA};
CREATE TABLE sources (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE items (
    id uuid PRIMARY KEY,
    source_id uuid NOT NULL REFERENCES sources(id),
    title text NOT NULL,
    description text,
    summary text,
    transcript text,
    media_url text
);
CREATE TABLE lessons (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    idx int NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    rating smallint,
    rated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    expansion text,
    expansion_model text,
    expansion_generated_at timestamptz,
    vikunja_task_id bigint,
    vikunja_sent_at timestamptz,
    UNIQUE (item_id, idx)
);
INSERT INTO sources VALUES ('{SOURCE}', 'Bron');
INSERT INTO items (id, source_id, title) VALUES ('{ITEM}', '{SOURCE}', 'Een item');
"""


@pytest.fixture
async def engine():
    if not TEST_DB_URL:
        pytest.skip("STROOM_TEST_DB_URL niet gezet")
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL),
                                 server_settings={"search_path": f"{SCHEMA}, public"})
    try:
        await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await conn.execute(_DDL)
    finally:
        await conn.close()
    eng = create_async_engine(
        TEST_DB_URL, connect_args={"server_settings": {"search_path": f"{SCHEMA}, public"}})
    yield eng
    await eng.dispose()


async def _migrate() -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL),
                                 server_settings={"search_path": f"{SCHEMA}, public"})
    try:
        for path in MIGRATIONS:
            for stmt in _statements(path.read_text()):
                await conn.execute(stmt)
    finally:
        await conn.close()


_idx = iter(range(1, 10**6))


async def _lesson(engine, title, body, *, expansion=None, rating=1, minutes_ago=0) -> str:
    lesson_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO lessons (id, item_id, idx, title, body, expansion, rating, rated_at) "
            "VALUES (CAST(:i AS uuid), CAST(:item AS uuid), :idx, :t, :b, :e, CAST(:r AS smallint), "
            "CASE WHEN CAST(:r AS smallint) IS NOT NULL "
            "     THEN now() - make_interval(mins => :m) END)"
        ), {"i": lesson_id, "item": ITEM, "idx": next(_idx), "t": title, "b": body,
            "e": expansion, "r": rating, "m": minutes_ago})
    return lesson_id


async def _search(engine, q, rating=1, limit=10) -> list[str]:
    async with AsyncSession(engine) as s:
        rows = await search_lessons(q=q, rating=rating, limit=limit, session=s)
    return [r.title for r in rows]


async def test_losse_woorden_en_stammen_in_beide_talen(engine):
    await _lesson(engine, "Kies open formaten",
                  "Bij de inkoop van nieuwe software horen open standaarden een eis te zijn.")
    await _lesson(engine, "Procurement matters",
                  "Running a procurement for open-source tools reduces vendor lock-in.")
    await _lesson(engine, "Verkiezingen", "Over campagnes en peilingen.")
    await _migrate()

    # Vroeger: ILIKE '%inkoop software open standaarden%' → niets.
    assert (await _search(engine, "inkoop software open standaarden"))[0] == "Kies open formaten"
    assert await _search(engine, "standaard") == ["Kies open formaten"]   # NL-stam
    assert await _search(engine, "verkiezing") == ["Verkiezingen"]
    assert await _search(engine, "procure") == ["Procurement matters"]    # EN-stam
    assert await _search(engine, "run tool") == ["Procurement matters"]


async def test_meer_geraakte_termen_eerst_dan_gewicht_van_het_veld(engine):
    await _lesson(engine, "Alleen software", "Een les over software in het algemeen.")
    await _lesson(engine, "Uitgebreid", "Iets anders.",
                  expansion="Bij inkoop gaat het om software en open standaarden.")
    await _lesson(engine, "Inkoop van software", "Kies leveranciers met open standaarden.")
    await _lesson(engine, "Nergens over", "Koken met seizoensgroenten.")
    await _migrate()

    # Drie lessen raken alle termen of een deel; titel+body (A/B) wint van
    # expansion (C) bij evenveel termen; de les zonder één term valt weg.
    assert await _search(engine, "inkoop software open standaarden") == [
        "Inkoop van software", "Uitgebreid", "Alleen software"]


async def test_uitsluiting_en_frase(engine):
    await _lesson(engine, "Spreadsheets", "Software als Excel is de standaard, niet open.")
    await _lesson(engine, "Formaten", "Open standaarden voor software maken je vrij.")
    await _migrate()

    assert await _search(engine, "software -excel") == ["Formaten"]
    assert await _search(engine, '"open standaarden"') == ["Formaten"]


async def test_rating_filter_en_lege_vraag_houden_oud_gedrag(engine):
    await _lesson(engine, "Oud nuttig", "Software kiezen.", minutes_ago=30)
    await _lesson(engine, "Nieuw nuttig", "Software bouwen.", minutes_ago=1)
    await _lesson(engine, "Niet nuttig", "Software slopen.", rating=-1)
    await _lesson(engine, "Ongekureerd", "Software testen.", rating=None)
    await _migrate()

    assert await _search(engine, "") == ["Nieuw nuttig", "Oud nuttig"]
    assert await _search(engine, "   ", rating=-1) == ["Niet nuttig"]
    assert len(await _search(engine, "software", rating=0)) == 4
    assert await _search(engine, "", limit=1) == ["Nieuw nuttig"]


async def test_alleen_stopwoorden_vindt_niets(engine):
    await _lesson(engine, "De les", "Het is in de tekst.")
    await _migrate()
    assert await _search(engine, "in is") == []


async def test_trigger_houdt_nieuwe_en_gewijzigde_lessen_bij(engine):
    await _migrate()
    lesson = await _lesson(engine, "Nieuwe les", "Over aanbestedingen.")
    assert await _search(engine, "aanbesteding") == ["Nieuwe les"]

    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE lessons SET expansion = 'Uitleg over de verkiezingen.' "
            "WHERE id = CAST(:i AS uuid)"), {"i": lesson})
    assert await _search(engine, "verkiezing") == ["Nieuwe les"]

    # Een rating zetten raakt de tekstkolommen niet en laat search_tsv staan.
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE lessons SET rating = -1, rated_at = now() WHERE id = CAST(:i AS uuid)"),
            {"i": lesson})
    assert await _search(engine, "aanbesteding", rating=-1) == ["Nieuwe les"]


async def test_backfill_loopt_over_meerdere_batches(engine):
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO lessons (item_id, idx, title, body, rating, rated_at) "
            "SELECT CAST(:item AS uuid), g, 'Les ' || g, 'Over verkiezingen', 1, now() "
            "FROM generate_series(1, 1200) g"), {"item": ITEM})
    await _migrate()

    async with engine.connect() as conn:
        missing = (await conn.execute(text(
            "SELECT count(*) FROM lessons WHERE search_tsv IS NULL"))).scalar()
    assert missing == 0
    assert len(await _search(engine, "verkiezing", limit=50)) == 50
