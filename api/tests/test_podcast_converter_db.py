import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from services import podcast_converter as pc

pytestmark = pytest.mark.db
SCHEMA = "podcast_converter_test"


@pytest.fixture
async def db(monkeypatch, tmp_path):
    url = os.environ.get("STROOM_TEST_DB_URL")
    if not url:
        pytest.skip("STROOM_TEST_DB_URL not set")
    conn = await asyncpg.connect(urlunsplit(urlsplit(url)._replace(scheme="postgresql")))
    await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE; CREATE SCHEMA {SCHEMA}; SET search_path TO {SCHEMA};")
    await conn.execute("CREATE TABLE items(processing_status text);")
    await conn.execute((Path(__file__).resolve().parents[2] / "schema/migrations/026-podcast-tests.sql").read_text())
    await conn.close()
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": SCHEMA}})
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setenv("PODCAST_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("PODCAST_VOICESTUDIO_URL", "http://voice")
    monkeypatch.delenv("PODCAST_HOST_STATS_URL", raising=False)
    yield maker
    await engine.dispose()


async def add(db, text="Hello, this is a test.", model="omnivoice"):
    async with db() as session:
        return await pc.enqueue(session, text, model)


def upstream(request):
    if request.url.path == "/engines/tts":
        return httpx.Response(200, json={"backends": [{"id": m, "available": True, "routing_status": "accelerated"} for m in pc.MODELS]})
    return httpx.Response(200, content=b"ID3" + b"x" * 200, headers={"Content-Type": "audio/mpeg"})


async def test_atomic_duplicate_admission_and_bounded_queue(db):
    a, b = await asyncio.gather(add(db), add(db))
    assert a["id"] == b["id"]
    await add(db, model="cosyvoice")
    await add(db, model="kittentts")
    with pytest.raises(HTTPException) as exc:
        await add(db, text="A fourth unique task.")
    assert exc.value.status_code == 429


async def test_render_and_reopen_history(db):
    first = await add(db)
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        assert await pc.run_next(db, client)
    async with db() as session:
        row = (await session.execute(sql("SELECT * FROM podcast_tests"))).mappings().one()
    result = pc.public_job(row)
    assert result["status"] == "ready" and result["audio_bytes"] == 203
    assert result["text"] == first["text"]
    assert result["audio_url"].endswith(f"{first['id']}/audio")
    assert pc.audio_path(first["id"]).is_file()
    assert (await add(db))["id"] != first["id"]  # deliberate second experiment


async def test_gpu_lock_excludes_second_worker(db):
    await add(db)
    async with db() as owner:
        assert await pc.try_gpu_lock(owner)
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            assert not await pc.run_next(db, client)
        async with db() as second:
            assert not await pc.try_gpu_lock(second)
    async with db() as released:
        assert await pc.try_gpu_lock(released)


async def test_transcription_and_capacity_wait_do_not_start_tts(db, monkeypatch):
    await add(db)
    async with db() as session:
        await session.execute(sql("INSERT INTO items VALUES ('transcribing')")); await session.commit()
    calls = []
    def handle(r):
        calls.append(r.url.path)
        return upstream(r)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert not await pc.run_next(db, client)
        assert not calls
        async with db() as session:
            row = (await session.execute(sql("SELECT status,message FROM podcast_tests"))).one()
            assert row[0] == "queued" and "transcribeert" in row[1]
            await session.execute(sql("DELETE FROM items")); await session.commit()
        async def busy(*args):
            return "Wachten: hoge load."
        monkeypatch.setattr(pc, "capacity_reason", busy)
        assert not await pc.run_next(db, client)
        assert not calls


async def test_restart_recovery_and_upstream_failure(db):
    await add(db)
    async with db() as session:
        await session.execute(sql("UPDATE podcast_tests SET status='rendering'")); await session.commit()
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        assert not await pc.run_next(db, client)
    async with db() as session:
        assert (await session.execute(sql("SELECT status FROM podcast_tests"))).scalar() == "failed"
    await add(db)
    def failing(request):
        return upstream(request) if request.url.path == "/engines/tts" else httpx.Response(503, text="private diagnostic")
    async with httpx.AsyncClient(transport=httpx.MockTransport(failing)) as client:
        assert await pc.run_next(db, client)
    async with db() as session:
        rows = (await session.execute(sql("SELECT status,message FROM podcast_tests"))).all()
    assert all(r[0] == "failed" and "private" not in r[1] for r in rows)


async def test_full_storage_does_not_hide_old_records(db):
    async with db() as session:
        await session.execute(sql("""
            INSERT INTO podcast_tests(id,text,text_hash,model,status)
            SELECT gen_random_uuid(),'test',n::text,'omnivoice','failed' FROM generate_series(1,30) n
        """)); await session.commit()
    with pytest.raises(HTTPException) as exc:
        await add(db)
    assert exc.value.status_code == 409


async def test_decision_scorer_uses_same_lease(db, monkeypatch):
    from services import decision_scorer as ds
    called = []

    async def batch(*args):
        called.append(True)
        async with db() as other:
            assert not await pc.try_gpu_lock(other)
        return {"scored": 0}

    monkeypatch.setattr(ds, "_run_batch", batch)
    async with db() as owner:
        assert await pc.try_gpu_lock(owner)
        assert await ds.run_batch(db, None, client=object()) == {"skipped": "podcast_gpu_busy"}
        assert not called
    assert await ds.run_batch(db, None, client=object()) == {"scored": 0}
    assert called == [True]
