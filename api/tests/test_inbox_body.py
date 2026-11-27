"""Unit tests voor eigen tekst (body) bij /inbox/submit."""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers.inbox import BODY_MAX_CHARS, InboxSubmitRequest, _body_from_request  # noqa: E402

pytestmark = pytest.mark.unit

TEKST = " ".join(["inzicht"] * 120)


def verzoek(**kw):
    basis = dict(url="https://stroom.c4w.nl/digest/ai/2026-11-28", title="AI-digest", format="article", topic_slug="ai")
    return InboxSubmitRequest(**{**basis, **kw})


def test_zonder_body_none():
    assert _body_from_request(verzoek()) is None


def test_body_wordt_gebruikt_en_getrimd():
    assert _body_from_request(verzoek(body=f"  {TEKST}\n")) == TEKST


def test_body_alleen_bij_article():
    with pytest.raises(HTTPException) as e:
        _body_from_request(verzoek(format="video", body=TEKST))
    assert e.value.status_code == 400


def test_body_te_kort():
    with pytest.raises(HTTPException):
        _body_from_request(verzoek(body="te kort"))


def test_body_te_lang():
    with pytest.raises(HTTPException):
        _body_from_request(verzoek(body="woord " * (BODY_MAX_CHARS // 5 + 1)))
