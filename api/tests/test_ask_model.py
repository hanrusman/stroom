"""Unit tests voor de modelkeuze van /huygens/items/{id}/ask: elke Stroom-naam
uit de modelinstellingen werkt, net als bij distill/expand/digest."""
import asyncio
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, "/app")

from pipeline.digest_model_map import RetiredModelError  # noqa: E402
from routers import ask  # noqa: E402

pytestmark = pytest.mark.unit


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _Session:
    """Item, geen lessen; de INSERT van de vraag slikt hij in."""

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM items" in sql:
            return _Result([("Titel", "De volledige brontekst.", None, None, "article")])
        return _Result([])

    async def commit(self):
        pass


def _ask(monkeypatch, model):
    calls = []

    class FakeLLM:
        def __init__(self, client):
            pass

        async def call_llm(self, alias, messages, **kwargs):
            calls.append(alias)
            return "Antwoord."

    monkeypatch.setattr(ask, "LLMService", FakeLLM)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(http_client=None)))
    answer = asyncio.run(ask.ask_item(
        "00000000-0000-0000-0000-000000000001", ask.AskBody(question="Waarom?"), request,
        model=model, session=_Session(), user={"id": "00000000-0000-0000-0000-000000000002"},
    ))
    return answer, calls


def test_catalogusnaam_wordt_alias(monkeypatch):
    answer, calls = _ask(monkeypatch, "qwen")
    assert calls == ["stroom-bulk"]
    assert answer.model == "qwen"


def test_vrij_litellm_model_uit_de_instellingen(monkeypatch):
    # Voorheen een 422: AskModel was Literal["qwen", "sonnet", "opus"].
    answer, calls = _ask(monkeypatch, "cloud-kimi")
    assert calls == ["cloud-kimi"]
    assert answer.model == "cloud-kimi"


def test_uitgefaseerd_model_stopt_voor_de_llm_call(monkeypatch):
    with pytest.raises(RetiredModelError):
        _ask(monkeypatch, "cloud-qwen-coder")
