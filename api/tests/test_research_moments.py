"""Momenten terugvinden in een getimed transcript (services/research_moments.py)."""
import json
import sys

sys.path.insert(0, "/app")

from services import research_moments as rm  # noqa: E402

SEGS = [
    {"start": 0.4, "end": 4.1, "text": "Welcome back to the show."},
    {"start": 12.0, "end": 15.0, "text": "Today we talk about software procurement."},
    {"start": 31.5, "end": 36.0, "text": "We took the designs for all of our servers"},
    {"start": 34.0, "end": 39.0, "text": "and network switches and made them open source."},
    {"start": 65.0, "end": 70.0, "text": "Apple will never open its operating system to others."},
    {"start": 3725.0, "end": 3730.0, "text": "Thanks for listening."},
]


def test_locate_quotes_finds_verbatim_quotes_across_segments():
    out = rm.locate_quotes(SEGS, [
        "we took the designs for all of our servers and network switches",  # over twee segmenten
        "network switches and made them open source",
        "Apple will never open",                                           # kort, maar letterlijk
        "Apple houdt zijn besturingssysteem gesloten",                     # parafrase/vertaling
        "",
    ])
    assert out == [31.5, 34.0, 65.0, None, None]


def test_locate_quotes_without_segments():
    assert rm.locate_quotes(None, ["iets"]) == [None]
    assert rm.locate_quotes([{"text": "geen start"}], ["geen start"]) == [None]


def test_transcript_blocks_group_by_time_and_cap():
    text, starts = rm.transcript_blocks(SEGS, block_secs=30)
    lines = text.splitlines()
    assert starts == [0.4, 31.5, 65.0, 3725.0]
    assert lines[0].startswith("[0:00] Welcome back") and "procurement" in lines[0]
    assert lines[1].startswith("[0:31] We took") and "switches" in lines[1]
    assert lines[3].startswith("[1:02:05] Thanks")
    _, capped = rm.transcript_blocks(SEGS, block_secs=30, max_chars=90)
    assert capped == [0.4]


def test_parse_ts_and_snap():
    assert rm.parse_ts("12:30") == 750.0
    assert rm.parse_ts("[1:02:05]") == 3725.0
    assert rm.parse_ts(90) == 90.0
    assert rm.parse_ts(None) is None and rm.parse_ts("ongeveer") is None and rm.parse_ts(True) is None
    starts = [0.4, 31.5, 65.0]
    assert rm.snap(40.0, starts) == 31.5
    assert rm.snap(31.0, starts) == 31.5      # afgerond in de weergave ([0:31])
    assert rm.snap(9999.0, starts) is None    # buiten het transcript


def test_parse_moments_ignores_garbage():
    starts = [0.4, 31.5, 65.0]
    obj = {"moments": [{"i": 2, "t": "0:31"}, {"i": 1, "t": None}, {"i": 9, "t": "0:00"},
                       {"i": "x", "t": "0:00"}, "onzin", {"i": 3, "t": "99:00"}]}
    assert rm.parse_moments(obj, 3, starts) == [None, 31.5, None]
    assert rm.parse_moments("geen object", 2, starts) == [None, None]


class FakeLLM:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    async def call_llm(self, model, messages, **kw):
        self.prompts.append(messages[-1]["content"])
        if kw.get("meta") is not None:
            kw["meta"]["finish_reason"] = "stop"
        return json.dumps(self.answer)


async def test_locate_moments_exact_first_then_model_for_the_rest():
    findings = [
        {"claim": "Meta maakte serverontwerpen open source.",
         "quote": "we took the designs for all of our servers and network switches"},
        {"claim": "Apple houdt zijn OS gesloten.", "quote": "", "speaker": "host"},
        {"claim": "Iets dat er niet in staat."},
    ]
    llm = FakeLLM({"moments": [{"i": 1, "t": "1:05"}, {"i": 2, "t": None}]})
    out, model = await rm.locate_moments(llm, SEGS, findings, models=["m1"])
    assert model == "m1"
    assert out == [{"t": 31.5, "exact": True}, {"t": 65.0, "exact": False}, None]
    # Het model ziet alleen wat nog open stond, hernummerd vanaf 1.
    assert "1. Apple houdt" in llm.prompts[0] and "2. Iets dat" in llm.prompts[0]
    assert "Meta maakte" not in llm.prompts[0]


async def test_locate_moments_skips_model_when_all_exact_or_no_transcript():
    llm = FakeLLM({})
    out, model = await rm.locate_moments(llm, SEGS, [{"claim": "x", "quote": "Apple will never open"}],
                                         models=["m1"])
    assert out == [{"t": 65.0, "exact": True}] and model is None and not llm.prompts
    out, model = await rm.locate_moments(llm, [], [{"claim": "x"}], models=["m1"])
    assert out == [None] and model is None and not llm.prompts
