"""Unit tests voor `_score_item_after_summary`.

Die helper scoort items waarvan de summary buiten de summarize-worker om is
geschreven (transcribe-callback met summary, handmatige /summarize). Scorer
en DB-session zijn gemockt; geen netwerk, geen database.
"""
import sys
import pytest

sys.path.insert(0, "/app")

import main  # noqa: E402

pytestmark = pytest.mark.unit


class _FakeSession:
    def __init__(self, log: list):
        self.log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def exec(self, stmt):
        self.log.append(stmt)

    async def commit(self):
        self.log.append("commit")


@pytest.fixture
def db_log(monkeypatch):
    import core.db
    log: list = []
    monkeypatch.setattr(core.db, "async_session_maker", lambda: _FakeSession(log))
    monkeypatch.setattr(main.app.state, "http_client", None, raising=False)
    return log


def _patch_scorer(monkeypatch, value):
    calls = []

    async def fake(http_client, text, title=None):
        calls.append((text, title))
        return value

    monkeypatch.setattr(main, "_score_with_quality_scorer", fake)
    return calls


async def test_writes_auto_score_without_overwriting_manual(monkeypatch, db_log):
    calls = _patch_scorer(monkeypatch, 7)
    await main._score_item_after_summary("abc", "Een samenvatting", "Titel")

    assert calls == [("Een samenvatting", "Titel")]
    stmt, commit = db_log
    sql = str(stmt)
    assert "quality_score_reason='auto'" in sql
    # Handmatige correcties (personal_interest, not_interesting, ...) blijven staan.
    assert "(quality_score_reason IS NULL OR quality_score_reason = 'auto')" in sql
    assert stmt.compile().params == {"q": 7, "i": "abc"}
    assert commit == "commit"


async def test_failed_score_leaves_item_untouched(monkeypatch, db_log):
    _patch_scorer(monkeypatch, None)
    await main._score_item_after_summary("abc", "Een samenvatting", "Titel")
    assert db_log == []


async def test_empty_summary_skips_scoring(monkeypatch, db_log):
    calls = _patch_scorer(monkeypatch, 7)
    await main._score_item_after_summary("abc", "", "Titel")
    assert calls == []
    assert db_log == []
