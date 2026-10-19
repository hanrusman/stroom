"""Unit-tests voor tips-mining: vensters, normalisatie, parsing, ruisfilters en
aggregatie (services/tips_helpers.py en services/tips_aggregate.py)."""
import sys

import pytest

sys.path.insert(0, "/app")

from services.tips_aggregate import aggregate, query_works  # noqa: E402
from services.tips_helpers import (  # noqa: E402
    STEP, WIN, clean_tips, norm, parse_tips, parse_verify, title_key, who_label, windows,
)

pytestmark = pytest.mark.unit


def _m(item="i1", title="Dune", **kw) -> dict:
    m = {"item_id": item, "title_key": title_key(title), "category": "book", "title": title,
         "creator": None, "recommended_by": None, "strength": "strong", "why": "Mooi boek",
         "quote": None, "source": "Show A", "episode": "Afl", "published": "2026-10-01"}
    m.update(kw)
    return m


def _w(keep=True, **kw) -> dict:
    w = {"keep": keep, "title": None, "creator": None, "category": None, "confidence": "high"}
    w.update(kw)
    return w


def _works(*titles, **kw) -> dict:
    return {title_key(t): _w(**kw) for t in titles}


# ---- windows / norm / title_key ----

def test_windows_edges():
    assert windows("") == [] and windows(None) == []
    assert windows("abc") == [(0, "abc")]
    exact = "x" * WIN
    assert windows(exact) == [(0, exact)]


def test_windows_long_text_overlaps_and_ends_at_end():
    text = "".join(chr(97 + i % 26) for i in range(WIN + STEP + 100))
    out = windows(text)
    assert [o for o, _ in out] == [0, STEP, 2 * STEP]
    assert out[1][1] == text[STEP:STEP + WIN]
    assert out[-1][1].endswith(text[-50:])
    assert all(chunk for _, chunk in out)


def test_norm_and_title_key():
    assert norm("The Hard Thing About Hard Things: Building a Business") == "hard thing about hard things"
    assert norm("Café Society") == "cafe society"
    assert norm("De Aanslag") == "aanslag"
    assert title_key("Seven Powers") == title_key("7 Powers") == "7 powers"


# ---- clean_tips / parse_tips ----

def test_clean_tips_filters_and_normalises():
    data = {"tips": [
        {"title": "Eigen boek", "category": "self_promo", "strength": "strong"},
        {"title": "Eigen show", "category": "podcast", "strength": "self_promo"},
        {"title": "Cursor", "category": "app", "strength": "STRONG"},
        {"title": "Iets", "category": "sculpture", "strength": "huge"},
        {"title": "Onbekend boek", "category": "book", "strength": "weak"},
        {"title": "  ", "category": "book"},
        "geen dict",
    ]}
    out = clean_tips(data)
    assert [(t["title"], t["category"], t["strength"]) for t in out] == [
        ("Cursor", "software", "strong"), ("Iets", "other", "weak")]
    assert set(out[0]) == {"category", "title", "creator", "recommended_by", "strength", "why", "quote"}
    assert clean_tips(["x"]) == [] and clean_tips({"tips": "x"}) == []


def test_parse_tips_handles_fences_and_noise():
    raw = '```json\n{"tips": [{"title": "Dune", "category": "book", "strength": "medium"}]}\n```'
    assert [t["title"] for t in parse_tips(raw)] == ["Dune"]
    assert parse_tips("geen json hier") == []


# ---- parse_verify / who_label ----

def test_parse_verify_drop_and_fix():
    batch = [{"vid": 0, "title_key": "dune", "title": "Dune", "creator": None, "category": "book"},
             {"vid": 1, "title_key": "muse", "title": "Muse", "creator": None, "category": "software"},
             {"vid": 2, "title_key": "playing in reality", "title": "Playing in Reality",
              "creator": None, "category": "book"}]
    raw = ('{"drop": [1, "x"], "fix": [{"id": 2, "title": "Playing and Reality", '
           '"creator": "D.W. Winnicott", "confidence": "medium"}, {"id": 99, "title": "Nope"}]}')
    out = parse_verify(raw, batch)
    assert out["dune"] == {"keep": True, "title": "Dune", "creator": None, "category": "book",
                           "confidence": "high"}
    assert out["muse"]["keep"] is False
    assert out["playing in reality"]["title"] == "Playing and Reality"
    assert out["playing in reality"]["confidence"] == "medium"
    assert parse_verify("onzin", batch) == {}


def test_who_label():
    assert who_label("gast", "Show A") == "Show A"
    assert who_label(None, "Show A") == "Show A"
    assert who_label("gast (Jan Jansen)", "Show A") == "Jan Jansen (Show A)"
    assert who_label("Lenny from Lenny's Podcast", "Lenny's Podcast") == "Lenny from Lenny's Podcast"


# ---- aggregate ----

def test_aggregate_requires_kept_verification():
    ms = [_m(title="Dune"), _m(title="Muse", category="software"), _m(title="Onverifieerd")]
    works = {**_works("Dune"), **_works("Muse", keep=False)}
    assert [w["title"] for w in aggregate(ms, works)] == ["Dune"]


def test_aggregate_one_mention_per_episode_strongest_wins():
    ms = [_m(strength="weak", why="eerst"), _m(strength="strong", why="beste"),
          _m(item="i2", strength="medium")]
    (w,) = aggregate(ms, _works("Dune"))
    assert w["episodes"] == 2 and w["score"] == 5 and w["strong"] == 1
    assert w["blurb"] == "beste"


def test_aggregate_sponsor_read_needs_distinct_episodes():
    ad = "Work OS turns enterprise authentication into drop-in APIs for every team"
    # Hetzelfde citaat 3× in dezelfde aflevering (overlappende vensters/modellen): geen ad.
    same_item = [_m(title="WorkOS", category="software", quote=ad) for _ in range(3)]
    (w,) = aggregate(same_item, _works("WorkOS"))
    assert w["episodes"] == 1
    # In 3 verschillende afleveringen: sponsor-read, en daarmee ook sponsor van die show.
    ms = [_m(item=f"i{n}", title="WorkOS", category="software", quote=ad) for n in range(3)]
    ms.append(_m(item="i9", title="WorkOS", category="software", quote="We gebruiken het zelf graag"))
    assert aggregate(ms, _works("WorkOS")) == []


def test_aggregate_ad_text_network_promo_and_self_work():
    ms = [_m(title="Atomic Habits", quote="use code STROOM for 20% off"),
          _m(title="Wordle", category="game", creator="The New York Times", source="The Daily (NYT)"),
          _m(title="Deep Work", creator="Cal Newport", source="Deep Questions with Cal Newport"),
          _m(title="Show A", category="podcast")]
    assert aggregate(ms, _works("Atomic Habits", "Wordle", "Deep Work", "Show A")) == []


def test_aggregate_recurring_single_show_ad_only_for_ad_categories():
    pod = [_m(item=f"i{n}", title="America Actually", category="podcast", why=f"r{n}") for n in range(4)]
    book = [_m(item=f"i{n}", title="Dune", why=f"r{n}") for n in range(4)]
    out = aggregate(pod + book, _works("America Actually", "Dune"))
    assert [w["title"] for w in out] == ["Dune"]
    # Twee shows: geen vaste ad.
    pod[0]["source"] = "Show B"
    assert {w["title"] for w in aggregate(pod, _works("America Actually"))} == {"America Actually"}


def test_aggregate_since_filters_mentions():
    ms = [_m(item="i1", published="2026-09-01"), _m(item="i2", published="2026-10-05"),
          _m(item="i3", published=None), _m(item="i4", title="Oud", published="2025-01-01")]
    works = _works("Dune", "Oud")
    (w,) = aggregate(ms, works, since="2026-10-01")
    assert w["title"] == "Dune" and w["episodes"] == 1 and w["last_mentioned"] == "2026-10-05"
    assert len(aggregate(ms, works)) == 2


def test_aggregate_title_correction_rules():
    ms = [_m(title="Playing in Reality")]
    sure = {title_key("Playing in Reality"): _w(title="Playing and Reality", confidence="medium")}
    assert aggregate(ms, sure)[0]["title"] == "Playing and Reality"
    other_work = {title_key("Playing in Reality"): _w(title="The Kindly Ones", confidence="high")}
    assert aggregate(ms, other_work)[0]["title"] == "Playing in Reality"
    unsure = {title_key("Playing in Reality"): _w(title="Playing and Reality", confidence="low")}
    (w,) = aggregate(ms, unsure)
    assert w["title"] == "Playing in Reality" and w["aka"] == []


def test_aggregate_merges_number_spellings():
    ms = [_m(item="i1", title="Seven Powers"), _m(item="i2", title="7 Powers")]
    (w,) = aggregate(ms, _works("7 Powers"))
    assert w["episodes"] == 2 and w["title_key"] == "7 powers"


def test_aggregate_mentions_sorted_strongest_then_newest():
    ms = [_m(item="a", strength="medium", published="2026-10-09"),
          _m(item="b", strength="strong", published="2026-01-01"),
          _m(item="c", strength="strong", published="2026-06-01")]
    (w,) = aggregate(ms, _works("Dune"))
    assert [m["item_id"] for m in w["mentions"]] == ["c", "b", "a"]


# ---- query_works ----

def _work(title, category="book", score=3, episodes=1, strong=1, who=(), sources=("Show A",),
          last=None) -> dict:
    return {"title": title, "creator": None, "category": category, "title_key": title_key(title),
            "score": score, "episodes": episodes, "strong": strong, "who": list(who), "blurb": None,
            "sources": list(sources), "last_mentioned": last, "aka": [], "mentions": [{"x": 1}]}


def test_query_works_filters_facets_and_paging():
    works = [_work("Dune", score=9, episodes=3, last="2026-10-01"),
             _work("Cursor", category="software", score=6, episodes=2, who=["Jan (Show B)"],
                   sources=["Show B"], last="2026-10-09"),
             _work("Halo", category="game", score=1, strong=0, last=None)]
    r = query_works(works, category="book")
    assert r["total"] == 1 and r["categories"] == {"book": 1, "software": 1, "game": 1}
    assert "mentions" not in r["works"][0]
    assert query_works(works, q="jan")["works"][0]["title"] == "Cursor"
    assert [w["title"] for w in query_works(works, strong_only=True)["works"]] == ["Dune", "Cursor"]
    assert query_works(works, min_episodes=2)["total"] == 2
    assert [w["title"] for w in query_works(works, sort="recent")["works"]] == ["Cursor", "Dune", "Halo"]
    page = query_works(works, sort="title", limit=1, offset=1)
    assert page["total"] == 3 and [w["title"] for w in page["works"]] == ["Dune"]
    assert query_works(works, source="Show B")["sources"] == [{"name": "Show B", "n": 1}]
