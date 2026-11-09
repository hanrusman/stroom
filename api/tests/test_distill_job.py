"""Unit tests voor de distill-job (routers/lessons.py): een fout in de
achtergrondjob moet als status 'error' zichtbaar worden voor de poller."""
import asyncio
import sys

import pytest

sys.path.insert(0, "/app")

from routers import lessons  # noqa: E402

pytestmark = pytest.mark.unit


def test_failure_marks_job_error(monkeypatch):
    def broken_session():
        raise RuntimeError("db weg")

    monkeypatch.setattr(lessons, "async_session_maker", broken_session)
    lessons._distill_jobs["x"] = lessons.DistillJob(status="running")

    asyncio.run(lessons._run_distill("x", "kimi", "cloud-kimi", llm=None))

    job = lessons._distill_jobs.pop("x")
    assert job.status == "error"
    assert "db weg" in job.error


def test_status_idle_for_unknown_item():
    job = asyncio.run(lessons.distill_status("onbekend", user=None))
    assert job.status == "idle"
