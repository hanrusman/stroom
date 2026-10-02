"""Unit tests voor services/decision_scorer.py: vragen, antwoord-parsing en de
HTTP-afhandeling richting stroom-decision (Ollama /v1/systemone), via
httpx.MockTransport. Geen netwerk, geen database."""
import sys

import httpx
import pytest

sys.path.insert(0, "/app")

from services import decision_scorer as ds  # noqa: E402

pytestmark = pytest.mark.unit

QUALITY_LEGEND = {str(i): c for i, c in enumerate(ds.QUALITY_CRITERIA)}
INTEREST_LEGEND = {str(i): c for i, c in enumerate(ds.INTEREST_CRITERIA)}


def _answers(quality=3.0, interest=1.5, clickbait=0.02):
    return {
        "quality": {"type": "score", "score": quality, "legend": QUALITY_LEGEND,
                    "probabilities": {"0": 0.0, "1": 0.05, "2": 0.15, "3": 0.5, "4": 0.3},
                    "confidence": 0.4},
        "interest": {"type": "score", "score": interest, "legend": INTEREST_LEGEND,
                     "probabilities": {"0": 0.1, "1": 0.4, "2": 0.4, "3": 0.1},
                     "confidence": 0.2},
        "clickbait": {"type": "noul", "noul": clickbait},
    }


def test_questions_without_profile_skip_interest():
    q = ds.build_questions(None)
    assert set(q) == {"quality", "clickbait"}
    assert q["quality"]["criteria"] == ds.QUALITY_CRITERIA


def test_questions_with_profile_embed_it_in_interest():
    q = ds.build_questions("Houdt van AI en politiek.")
    assert "Houdt van AI en politiek." in q["interest"]["instructions"]
    assert q["interest"]["criteria"] == ds.INTEREST_CRITERIA


def test_parse_maps_quality_to_1_10_with_labelled_probabilities():
    score, detail = ds.parse_answers(_answers(quality=3.0), interest_weight=0.0)
    assert score == 8  # 1 + 9 * 3/4 = 7.75
    assert detail["quality"]["score10"] == 8
    assert detail["quality"]["probabilities"]["Well-argued with specific insights"] == 0.5
    assert detail["interest"]["score10"] == 6  # 1 + 9 * 1.5/3
    assert detail["clickbait"] == 0.02


def test_parse_interest_weight_blends_fractions():
    score, _ = ds.parse_answers(_answers(quality=4.0, interest=0.0), interest_weight=0.5)
    assert score == 6  # 1 + 9 * (0.5*1.0 + 0.5*0.0) = 5.5 -> 6
    score, _ = ds.parse_answers(_answers(quality=0.0, interest=3.0), interest_weight=0.0)
    assert score == 1


def test_parse_without_interest_answer():
    answers = _answers()
    del answers["interest"]
    score, detail = ds.parse_answers(answers, interest_weight=0.5)
    assert score == 8
    assert detail["interest"] is None


# --- HTTP-afhandeling ---

@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(ds, "DECISION_URL", "http://decision")
    monkeypatch.setattr(ds, "RETRY_DELAY_SEC", 0)


def _client(responses: list):
    """Geeft per request het volgende element: (status, json/text) of een exception."""
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        nxt = responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        status, body = nxt
        if isinstance(body, dict):
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


async def test_score_item_success():
    client, calls = _client([(200, {"answers": _answers()})])
    score, detail = await ds.score_item(client, "Titel", "Samenvatting", "profiel")
    assert score == 8 and "latency_sec" in detail
    assert calls == ["/v1/systemone"]


async def test_missing_model_is_pulled_then_retried():
    client, calls = _client([
        (404, '{"error":"model \\"nimble:9b-q4_K_M\\" not found, try pulling it first"}'),
        (200, {"status": "success"}),
        (200, {"answers": _answers()}),
    ])
    score, _ = await ds.score_item(client, "Titel", "Samenvatting", None)
    assert score == 8
    assert calls == ["/v1/systemone", "/api/pull", "/v1/systemone"]


async def test_model_still_missing_after_pull_is_unavailable():
    missing = '{"error":"model \\"nimble\\" not found, try pulling it first"}'
    client, _ = _client([(404, missing), (200, {"status": "success"}), (404, missing)])
    with pytest.raises(ds.DecisionUnavailable):
        await ds.score_item(client, "Titel", "Samenvatting", None)


async def test_malformed_answer_is_item_error():
    client, _ = _client([(200, {"answers": {"clickbait": {"noul": 0.1}}})])
    with pytest.raises(ds.DecisionItemError):
        await ds.score_item(client, "Titel", "Samenvatting", None)


async def test_runner_crash_is_retried_once():
    client, calls = _client([(500, '{"error":"EOF"}'), (200, {"answers": _answers()})])
    score, _ = await ds.score_item(client, "Titel", "Samenvatting", None)
    assert score == 8 and len(calls) == 2


async def test_repeated_5xx_fails_the_item():
    client, _ = _client([(500, "EOF"), (503, "busy")])
    with pytest.raises(ds.DecisionItemFailed):
        await ds.score_item(client, "Titel", "Samenvatting", None)


async def test_connection_error_is_unavailable():
    client, _ = _client([httpx.ConnectError("refused")])
    with pytest.raises(ds.DecisionUnavailable):
        await ds.score_item(client, "Titel", "Samenvatting", None)


async def test_4xx_is_item_error():
    client, _ = _client([(400, '{"error":"prompt has 3000 tokens"}')])
    with pytest.raises(ds.DecisionItemError):
        await ds.score_item(client, "Titel", "Samenvatting", None)


async def test_summary_is_truncated(monkeypatch):
    monkeypatch.setattr(ds, "SUMMARY_CHARS", 10)
    seen = {}

    def handler(request):
        import json
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"answers": _answers()})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await ds.score_item(client, None, "x" * 50, None)
    assert seen["state"] == {"title": "", "summary": "x" * 10}


async def test_decision_mode_defers_inline_scoring(monkeypatch):
    """In decision-modus scoren worker/callback niet zelf: None, de batch doet het."""
    import main

    monkeypatch.setattr(main.decision_scorer, "ENABLED", True)

    async def must_not_run(*a, **kw):
        raise AssertionError("legacy-scorer aangeroepen in decision-modus")

    monkeypatch.setattr(main, "_get_score_model", must_not_run)
    assert await main._score_with_quality_scorer(None, "tekst", "titel") is None
