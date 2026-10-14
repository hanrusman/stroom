"""Unit tests voor _spawn_distill: distill draait los van de sum-worker en
een fout (bv. httpx.ReadTimeout met lege str()) komt leesbaar in de log."""
import asyncio
import sys

import httpx
import pytest

sys.path.insert(0, "/app")

import main  # noqa: E402

pytestmark = pytest.mark.unit


def test_spawn_returns_immediately_and_logs_exception_type(monkeypatch, capsys):
    started = asyncio.Event()

    async def slow_fail(*args, **kwargs):
        started.set()
        await asyncio.sleep(0.05)
        raise httpx.ReadTimeout("")

    monkeypatch.setattr(main, "_distill_lessons_for_item", slow_fail)

    async def scenario():
        main._spawn_distill("abc", "s", "body", None, None)
        assert not started.is_set()  # spawn wacht niet op de distill
        assert len(main._distill_tasks) == 1
        await asyncio.gather(*main._distill_tasks)
        await asyncio.sleep(0)  # done-callback laten lopen
        assert not main._distill_tasks

    asyncio.run(scenario())
    out = capsys.readouterr().out
    assert "distill faalde voor abc: ReadTimeout('')" in out
