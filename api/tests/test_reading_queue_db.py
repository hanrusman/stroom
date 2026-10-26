"""Queue contract against disposable Postgres; never use the production database.
Run with STROOM_TEST_DB_URL and pytest tests/test_reading_queue_db.py.
"""
import asyncio
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from routers import reading_queue as q

pytestmark = pytest.mark.db

@pytest.fixture
async def db():
    url = os.environ.get("STROOM_TEST_DB_URL")
    if not url:
        pytest.skip("STROOM_TEST_DB_URL must point to a disposable database")
    schema = "queue_test_" + uuid4().hex
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute("""
            CREATE TABLE users (id uuid PRIMARY KEY);
            CREATE TABLE sources (id uuid PRIMARY KEY, name text, image_url text);
            CREATE TABLE items (id uuid PRIMARY KEY, source_id uuid REFERENCES sources(id),
                title text DEFAULT 'Titel', description text DEFAULT '<p>Beschrijving</p>', author text,
                thumbnail_url text, media_url text, published_at timestamptz,
                format text DEFAULT 'article', status text DEFAULT 'new',
                processing_status text DEFAULT 'ready', quality_score int, scheduled_for timestamptz,
                summary text, transcript text);
        """)
        migration = (Path(__file__).parents[2] / "schema/migrations/027-reading-queue.sql").read_text()
        await raw.driver_connection.execute(migration)
        await raw.driver_connection.execute(migration)  # migration is repeatable
    users = [{"id": str(uuid4())}, {"id": str(uuid4())}]
    source = uuid4(); items = [uuid4(), uuid4(), uuid4()]
    async with engine.begin() as conn:
        for u in users:
            await conn.execute(text("INSERT INTO users VALUES (CAST(:id AS uuid))"), u)
        await conn.execute(text("INSERT INTO sources VALUES (:s, 'De bron', NULL)"), {"s": source})
        for i in items:
            await conn.execute(text("INSERT INTO items (id,source_id) VALUES (:i,:s)"), {"i": i,"s": source})
    yield engine, users, items
    await engine.dispose()

async def add(engine, user, item):
    async with AsyncSession(engine) as session:
        return await q.enqueue(item, session=session, user=user)
async def ids(engine, user):
    async with AsyncSession(engine) as session:
        return await q.queue_ids(session=session, user=user)

async def test_duplicate_put_preserves_fifo_and_bookmark(db):
    engine, users, items = db; user = users[0]
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE items SET status='pinned' WHERE id=:i"), {"i": items[0]})
    await add(engine,user,items[0]); await add(engine,user,items[1]); await add(engine,user,items[0])
    assert await ids(engine,user) == [str(i) for i in items[:2]]
    async with AsyncSession(engine) as session:
        rows = await q.list_queue(limit=1,offset=0,session=session,user=user)
        assert rows[0]['status'] == 'pinned'
        assert rows[0]['source_name'] == 'De bron'
        assert rows[0]['description'] == '<p>Beschrijving</p>'
        assert len(await q.list_queue(limit=1,offset=1,session=session,user=user)) == 1

async def test_user_isolation_and_idempotent_delete(db):
    engine, users, items = db
    for user in users: await add(engine,user,items[0])
    async with AsyncSession(engine) as session:
        for _ in range(2): await q.dequeue(items[0],session=session,user=users[0])
    assert await ids(engine,users[0]) == []
    assert await ids(engine,users[1]) == [str(items[0])]

async def test_archive_clears_all_queues_and_restore_does_not_readd(db):
    engine, users, items = db
    for user in users: await add(engine,user,items[0])
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE items SET status='archived' WHERE id=:i"), {"i":items[0]})
    for user in users: assert await ids(engine,user) == []
    with pytest.raises(HTTPException) as exc: await add(engine,users[0],items[0])
    assert exc.value.status_code == 409
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE items SET status='new' WHERE id=:i"), {"i":items[0]})
    assert await ids(engine,users[0]) == []

async def test_missing_item_and_item_delete(db):
    engine, users, items = db
    with pytest.raises(HTTPException) as exc: await add(engine,users[0],uuid4())
    assert exc.value.status_code == 404
    await add(engine,users[0],items[0])
    async with engine.begin() as conn: await conn.execute(text("DELETE FROM items WHERE id=:i"), {"i":items[0]})
    assert await ids(engine,users[0]) == []

async def test_concurrent_duplicate_add(db):
    engine, users, items = db
    await asyncio.gather(*(add(engine,users[0],items[0]) for _ in range(6)))
    assert await ids(engine,users[0]) == [str(items[0])]

async def test_add_waiting_for_archive_cannot_resurrect_entry(db):
    engine, users, items = db
    async with AsyncSession(engine) as session:
        await session.execute(text("UPDATE items SET status='archived' WHERE id=:i"), {"i":items[0]})
        pending = asyncio.create_task(add(engine,users[0],items[0]))
        await asyncio.sleep(0.1)
        assert not pending.done()
        await session.commit()
    with pytest.raises(HTTPException) as exc: await pending
    assert exc.value.status_code == 409
    assert await ids(engine,users[0]) == []

async def test_http_auth_and_uuid_validation(db):
    engine, users, items = db
    app = FastAPI(); app.include_router(q.router)
    async def sessions():
        async with AsyncSession(engine) as session: yield session
    app.dependency_overrides[q.get_async_session] = sessions
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        assert (await client.get('/reading-queue')).status_code == 401
        app.dependency_overrides[q.require_user] = lambda: users[0]
        assert (await client.put('/reading-queue/not-a-uuid')).status_code == 422
        assert (await client.get('/reading-queue?offset=-1')).status_code == 422
        assert (await client.put('/reading-queue/'+str(items[0]))).status_code == 200
        assert (await client.get('/reading-queue/ids')).json() == [str(items[0])]
