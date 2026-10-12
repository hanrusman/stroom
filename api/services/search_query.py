"""Zoekvraag → tsquery met NL- én EN-stemming, met behoud van de structuur.

search_tsv bevat per woord de Nederlandse en de Engelse stam op dezelfde
positie (migratie 024). Twee hele queries OR'en (NL-query | EN-query) klopt
niet: een uitsluiting geldt dan maar in één taaltak, en eigen parsing van de
websearch-syntax gaat mis op OR-voorrang en mintekens binnen frases.

Daarom: Postgres parset de vraag met websearch_to_tsquery('simple') — juiste
booleaanse boom, ruwe woorden — en hier wordt elk woord vervangen door
(NL-stam | EN-stam). Een woord dat in beide talen een stopwoord is valt weg;
binnen een frase schuift de afstand dan op ('a in b' → 'a' <2> 'b'), net als
Postgres zelf doet.
"""
import re
from typing import Optional

from sqlalchemy import text as sa_text

# Knopen: ("lex", s) | ("not", x) | ("and"|"or", a, b) | ("phrase", a, b, afstand)
Node = tuple

_TOKEN = re.compile(r"\s*('(?:[^']|'')*'|<->|<\d+>|[()&|!])")
_UNESCAPE = re.compile(r"''|\\\\")


class _Parser:
    """Recursive descent over de tekstvorm van een tsquery. Voorrang zoals
    Postgres hem uitvoert: | < & < <N> < !"""

    def __init__(self, text: str):
        self.toks, pos = [], 0
        while pos < len(text):
            m = _TOKEN.match(text, pos)
            if not m:
                if text[pos:].strip():
                    raise ValueError(f"onverwachte tsquery-tekst: {text[pos:]!r}")
                break
            self.toks.append(m.group(1))
            pos = m.end()
        self.i = 0

    def _peek(self) -> Optional[str]:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _take(self) -> str:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def parse(self) -> Optional[Node]:
        if not self.toks:
            return None
        node = self._or()
        if self._peek() is not None:
            raise ValueError(f"onverwacht token {self._peek()!r}")
        return node

    def _or(self) -> Node:
        node = self._and()
        while self._peek() == "|":
            self._take()
            node = ("or", node, self._and())
        return node

    def _and(self) -> Node:
        node = self._phrase()
        while self._peek() == "&":
            self._take()
            node = ("and", node, self._phrase())
        return node

    def _phrase(self) -> Node:
        node = self._unary()
        while (tok := self._peek()) is not None and tok.startswith("<"):
            self._take()
            dist = 1 if tok == "<->" else int(tok[1:-1])
            node = ("phrase", node, self._unary(), dist)
        return node

    def _unary(self) -> Node:
        tok = self._take()
        if tok == "!":
            return ("not", self._unary())
        if tok == "(":
            node = self._or()
            if self._take() != ")":
                raise ValueError("ontbrekend ')'")
            return node
        if tok.startswith("'"):
            return ("lex", _UNESCAPE.sub(lambda m: m.group(0)[0], tok[1:-1]))
        raise ValueError(f"onverwacht token {tok!r}")


def parse(text: str) -> Optional[Node]:
    return _Parser(text).parse()


def lexemes(node: Optional[Node]) -> set[str]:
    if node is None:
        return set()
    if node[0] == "lex":
        return {node[1]}
    return set().union(*(lexemes(c) for c in node[1:] if isinstance(c, tuple)))


# Resultaat van expand: (knoop, lead, trail). knoop None = alles weggevallen;
# lead/trail = posities die aan de randen van een frase wegvielen.
_Expanded = tuple[Optional[Node], int, int]


def _expand(node: Node, stems: dict[str, list[str]]) -> _Expanded:
    kind = node[0]
    if kind == "lex":
        alts = stems.get(node[1], [node[1]])
        if not alts:
            return None, 0, 0
        out: Node = ("lex", alts[0])
        for alt in alts[1:]:
            out = ("or", out, ("lex", alt))
        return out, 0, 0
    if kind == "not":
        inner = _expand(node[1], stems)[0]
        return (("not", inner) if inner is not None else None), 0, 0
    if kind in ("and", "or"):
        a = _expand(node[1], stems)[0]
        b = _expand(node[2], stems)[0]
        if a is None or b is None:
            return (a if b is None else b), 0, 0
        return (kind, a, b), 0, 0
    # phrase
    a, a_lead, a_trail = _expand(node[1], stems)
    b, b_lead, b_trail = _expand(node[2], stems)
    dist = node[3]
    if a is None and b is None:
        span = a_lead + dist + b_lead
        return None, span, span
    if a is None:
        return b, a_lead + dist + b_lead, b_trail
    if b is None:
        return a, a_lead, a_trail + dist + b_lead
    return ("phrase", a, b, a_trail + dist + b_lead), a_lead, b_trail


def expand(node: Optional[Node], stems: dict[str, list[str]]) -> Optional[Node]:
    """Vervang elk woord door zijn stammen; stems[w] == [] = stopwoord."""
    return None if node is None else _expand(node, stems)[0]


def _quote(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"


def serialize(node: Node) -> str:
    kind = node[0]
    if kind == "lex":
        return _quote(node[1])
    if kind == "not":
        return f"!({serialize(node[1])})"
    if kind == "phrase":
        op = "<->" if node[3] == 1 else f"<{node[3]}>"
        return f"({serialize(node[1])}) {op} ({serialize(node[2])})"
    op = "&" if kind == "and" else "|"
    return f"({serialize(node[1])}) {op} ({serialize(node[2])})"


def global_exclusions(node: Optional[Node]) -> Optional[Node]:
    """De uitsluitingen die voor de hele vraag gelden: NOT-termen in de
    bovenste AND-keten. Onder een OR gelden ze maar voor één tak
    ('fiets OR koken -kabinet' = fiets | (koken & !kabinet)), en dan niet."""
    if node is None:
        return None
    conjuncts, stack = [], [node]
    while stack:
        n = stack.pop()
        if n[0] == "and":
            stack.extend((n[2], n[1]))
        else:
            conjuncts.append(n)
    excl: Optional[Node] = None
    for n in conjuncts:
        if n[0] == "not":
            excl = n[1] if excl is None else ("or", excl, n[1])
    return excl


# Per token van de vraag: het ruwe lexeem ('simple') naast wat de 'dutch'- en
# 'english'-config ervan maken. Zelfde parser, dus dezelfde tokens in dezelfde
# volgorde; zo volgt de stemming de tokentypen en dictionaries van de index,
# ook voor samengestelde woorden ('data-centers' → data-center / data-cent).
_STEMS_SQL = """
    SELECT s.lexemes[1], d.lexemes, e.lexemes
    FROM ts_debug('simple', :q) WITH ORDINALITY AS s(a, b, c, f, g, lexemes, n)
    JOIN ts_debug('dutch', :q) WITH ORDINALITY AS d(a, b, c, f, g, lexemes, n) USING (n)
    JOIN ts_debug('english', :q) WITH ORDINALITY AS e(a, b, c, f, g, lexemes, n) USING (n)
    WHERE s.lexemes IS NOT NULL AND cardinality(s.lexemes) > 0
"""


async def build(session, q: str) -> tuple[Optional[str], Optional[str]]:
    """(tsquery-tekst, tsquery-tekst van de globale uitsluitingen). None =
    niets om op te zoeken / niets uit te sluiten. Te gebruiken als
    CAST(:tsq AS tsquery): de tsquery-invoer doet geen stemming meer."""
    raw = (await session.exec(sa_text(
        "SELECT websearch_to_tsquery('simple', :q)::text").bindparams(q=q))).scalar()
    tree = parse(raw or "")
    stems: dict[str, list[str]] = {}
    for word, nl, en in (await session.exec(sa_text(_STEMS_SQL).bindparams(q=q))).all():
        # [] = stopwoord in die taal; NULL = geen dictionary, het woord zelf telt.
        alts = (nl if nl is not None else [word]) + (en if en is not None else [word])
        stems[word] = list(dict.fromkeys(stems.get(word, []) + alts))
    tsq = expand(tree, stems)
    excl = expand(global_exclusions(tree), stems)
    return (serialize(tsq) if tsq else None, serialize(excl) if excl else None)


def positive_text(q: str) -> str:
    """De vraag zonder -uitsluitingen, voor de query-embedding. Een minteken
    binnen aanhalingstekens is geen uitsluiting."""
    tokens = re.findall(r'-?"[^"]*"?|\S+', q)
    return " ".join(t for t in tokens if not (t.startswith("-") and len(t) > 1)).strip()

