"""Unit tests for parse_llm_json — tolerante JSON-parsing van LLM-output."""
import json
import sys

import pytest

sys.path.insert(0, "/app")

from services.llm_service import parse_llm_json  # noqa: E402

pytestmark = pytest.mark.unit


def test_plain_json():
    assert parse_llm_json('{"lessons": []}') == {"lessons": []}


def test_json_fence():
    # Kimi K2.6 levert dit ondanks response_format=json_object
    raw = '```json\n{"lessons": [{"title": "a", "body": "b"}]}\n```'
    assert parse_llm_json(raw) == {"lessons": [{"title": "a", "body": "b"}]}


def test_bare_fence():
    assert parse_llm_json('```\n{"x": 1}\n```') == {"x": 1}


def test_think_trace_and_preamble():
    raw = '<think>eerst nadenken {niet dit}</think>\nHier is het resultaat: {"x": 1} klaar.'
    assert parse_llm_json(raw) == {"x": 1}


def test_no_json_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json("Sorry, ik kan dat niet.")
