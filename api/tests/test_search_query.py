"""Unit-tests voor services/search_query: tsquery-tekst parsen, woorden
vervangen door hun NL/EN-stammen met behoud van structuur, en de globale
uitsluitingen voor de semantische tak. De invoer is wat
websearch_to_tsquery('simple', ...) teruggeeft."""
import sys

import pytest

sys.path.insert(0, "/app")

from services.search_query import (  # noqa: E402
    expand, global_exclusions, parse, positive_text, serialize,
)

pytestmark = pytest.mark.unit

STEMS = {
    "running": ["running", "run"],
    "elections": ["election", "elect"],
    "kabinet": ["kabinet"],
    "in": [],          # stopwoord in beide talen
    "de": ["de"],      # alleen NL-stopwoord; EN houdt hem
}


def _roundtrip(text: str) -> str:
    return serialize(parse(serialize(parse(text))))


@pytest.mark.parametrize("text", [
    "'fiets' | 'koken' & !'kabinet'",
    "'curl' <-> 'x' <-> 'post' & !( 'tour' <-> 'runs' )",
    "'a' <3> ( 'b' | 'c' )",
    "'it''s' & 'back\\\\slash'",
])
def test_parse_serialize_is_stabiel(text):
    assert _roundtrip(text) == serialize(parse(text))


def test_parse_volgt_postgres_voorrang():
    assert parse("'fiets' | 'koken' & !'kabinet'") == (
        "or", ("lex", "fiets"), ("and", ("lex", "koken"), ("not", ("lex", "kabinet"))))
    assert parse("'it''s'") == ("lex", "it's")
    assert parse("") is None


def test_expand_vervangt_elk_woord_door_zijn_stammen():
    tree = expand(parse("'running' & !'elections'"), STEMS)
    assert serialize(tree) == (
        "(('running') | ('run')) & (!(('election') | ('elect')))")


def test_expand_laat_dubbel_stopwoord_weg_en_verschuift_de_frase():
    # 'verkiezingen in nederland' als frase → 'verkiezingen' <2> 'nederland'
    tree = expand(parse("'verkiezingen' <-> 'in' <-> 'nederland'"), STEMS)
    assert tree == ("phrase", ("lex", "verkiezingen"), ("lex", "nederland"), 2)
    tree = expand(parse("'in' <-> 'in' <-> 'kabinet' <-> 'in'"), STEMS)
    assert tree == ("lex", "kabinet")
    assert expand(parse("'tour' <-> 'de' <-> 'kabinet'"), STEMS) == (
        "phrase", ("phrase", ("lex", "tour"), ("lex", "de"), 1), ("lex", "kabinet"), 1)
    assert expand(parse("'in' & !'in'"), STEMS) is None


@pytest.mark.parametrize("text,expected", [
    ("'tour' & !'kabinet'", ("lex", "kabinet")),
    ("'tour' & !'kabinet' & !'zorg'", ("or", ("lex", "kabinet"), ("lex", "zorg"))),
    ("'fiets' | 'koken' & !'kabinet'", None),
    ("!( 'tour' <-> 'runs' ) & 'fiets'", ("phrase", ("lex", "tour"), ("lex", "runs"), 1)),
    ("'curl' <-> 'x' <-> 'post'", None),
])
def test_globale_uitsluitingen(text, expected):
    assert global_exclusions(parse(text)) == expected


@pytest.mark.parametrize("q,expected", [
    ("tour -kabinet", "tour"),
    ('"curl -X POST"', '"curl -X POST"'),
    ('fiets -"tour runs" koken', "fiets koken"),
    ("covid-19 -", "covid-19 -"),
])
def test_positive_text(q, expected):
    assert positive_text(q) == expected
