"""Dossiers: brede onderzoeksvragen over het hele Stroom-archief.

Een chat-LLM met zoektools verdrinkt in een vraag als "hoe verandert het
inkopen van software?": de relevante bronnen zijn er honderden, elk met een
samenvatting van tientallen KB. Deze pijplijn doet daarom wat een
onderzoeksteam zou doen, met per stap het model dat erbij past:

1. plan      — sterk model: deelvragen (aspecten) + 18-28 zoekvragen NL/EN.
2. recall    — hybride zoeken (FTS + e5-vectoren) per zoekvraag, Reciprocal
               Rank Fusion over alle zoekvragen. Ook gearchiveerde (= gelezen)
               items tellen mee.
3. screen    — goedkoop model: titel + teaser in batches van 25 op 0-3 scoren.
4. extract   — goedkoop/middel model, één call per bron: specifieke beweringen
               met actor, sector, regio, bewijssoort en citaat.
5. write     — sterkste model: het dossier, met [S12]-bronverwijzingen.
6. critique  — model uit een andere familie toetst het concept aan de
               bevindingen (onderbouwing, overgeneralisatie, gemist tegengeluid).
7. revise    — schrijfmodel verwerkt de kritiek.

Elke stap slaat zijn resultaat op voordat de volgende begint, dus een run is
hervatbaar na een herstart: wat er al ligt wordt overgeslagen. Een
"vernieuwing" (parent_id) hergebruikt plan, screening en extracties van de
vorige run en doet alleen nieuwe items opnieuw.

Opslag loopt via een Store (DbStore in productie, MemoryStore in tests en
proefruns); het archief via Corpus (alleen lezen).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable, Optional, Protocol

import httpx
from fastapi import HTTPException
from sqlalchemy import text as sa_text

from services import search_index, search_query
from services.llm_service import parse_llm_json
from services.research_prompts import (
    ASK_SYSTEM,
    CRITIQUE_SYSTEM,
    CRITIQUE_TEXT_SUFFIX,
    DEEPEN_SYSTEM,
    EXTRACT_SYSTEM,
    PLAN_SYSTEM,
    REVISE_SYSTEM,
    SCREEN_SYSTEM,
    SYNTH_SYSTEM,
)

# ---------------------------------------------------------------- config


def _models(env: str, default: str) -> list[str]:
    """Kommagescheiden fallback-keten: eerste model dat antwoordt wint."""
    return [m.strip() for m in os.environ.get(env, default).split(",") if m.strip()]


# Plan en schrijven: Anthropic is krediet-gevoelig (flaky), dus altijd een
# Ollama-Cloud-model als laatste vangnet.
PLAN_MODELS = _models("RESEARCH_PLAN_MODELS", "stroom-sonnet,cloud-kimi,cloud-deepseek")
SCREEN_MODELS = _models("RESEARCH_SCREEN_MODELS", "cloud-gemma,cloud-gpt-120b")
EXTRACT_MODELS = _models("RESEARCH_EXTRACT_MODELS", "cloud-gemma,cloud-deepseek")
WRITE_MODELS = _models("RESEARCH_WRITE_MODELS", "stroom-deep,stroom-sonnet,cloud-kimi")
# Gemini (stroom-long-context) staat er bewust niet in: problemen met
# API-krediet (2026-11). Terugzetten kan via RESEARCH_CRITIQUE_MODELS.
CRITIQUE_MODELS = _models("RESEARCH_CRITIQUE_MODELS", "cloud-deepseek,cloud-kimi")

RECALL_POOL = int(os.environ.get("RESEARCH_RECALL_POOL", "40"))     # per zoekvraag per ranglijst
SCREEN_MAX = int(os.environ.get("RESEARCH_SCREEN_MAX", "650"))      # kandidaten die gescreend worden
SCREEN_BATCH = 25
SCREEN_MIN = 2                                                      # vanaf deze score extraheren
EXTRACT_MAX = int(os.environ.get("RESEARCH_EXTRACT_MAX", "160"))
EXTRACT_FILL_LOW = 40           # max. twijfelgevallen (screen 1) die toch gelezen worden
DEEPEN_CANDIDATES = 160         # nieuwe kandidaten uit de verdiepingsronde
DEEPEN_EXTRACT = 60
EXTRACT_BODY_CHARS = 22000
EXTRACT_MIN_SUMMARY = 2500      # kortere samenvatting → brontekst erbij
WRITE_MAX_FINDINGS_CHARS = 260000
RRF_K = 60

# Ollama Cloud geeft 429 boven ~4 gelijktijdige calls en Stroom deelt dat
# budget (tips, scoring). Anthropic/Gemini hebben ruimere limieten.
_OLLAMA_SEM = asyncio.Semaphore(int(os.environ.get("RESEARCH_CLOUD_CONCURRENCY", "3")))
_OTHER_SEM = asyncio.Semaphore(4)

STAGES = ("planning", "recall", "screening", "extracting", "deepening", "writing",
          "critiquing", "revising")
TERMINAL = ("done", "failed", "cancelled")


_http: Optional[httpx.AsyncClient] = None


def http_client() -> httpx.AsyncClient:
    """Eigen client voor de LLM-calls van dossiers, zodat een lopend dossier
    de verbindingspool van de samenvat-workers (app.state.llm_client) niet leegtrekt."""
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=600.0, limits=httpx.Limits(max_connections=8))
    return _http


def _sem_for(model: str) -> asyncio.Semaphore:
    return _OLLAMA_SEM if model.startswith("cloud-") else _OTHER_SEM


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- LLM


@dataclass
class Usage:
    calls: int = 0
    failures: int = 0
    by_model: dict = field(default_factory=dict)

    def note(self, model: str, ok: bool, secs: float) -> None:
        m = self.by_model.setdefault(model, {"calls": 0, "failures": 0, "secs": 0.0})
        m["calls"] += 1
        m["secs"] = round(m["secs"] + secs, 1)
        self.calls += 1
        if not ok:
            m["failures"] += 1
            self.failures += 1


class Truncated(Exception):
    """Antwoord afgekapt op max_tokens (finish_reason 'length')."""


async def _one_call(llm, model: str, messages: list[dict], *, as_json: bool, max_tokens: int,
                    timeout: float, temperature: float, usage: Optional[Usage]) -> str:
    async with _sem_for(model):
        t0 = time.monotonic()  # binnen de semafoor: wachttijd telt niet als rekentijd
        meta: dict = {}
        try:
            raw = await llm.call_llm(model, messages, temperature=temperature,
                                     response_format="json_object" if as_json else "text",
                                     timeout=timeout, max_tokens=max_tokens, meta=meta)
        except Exception:
            if usage:
                usage.note(model, False, time.monotonic() - t0)
            raise
        if usage:
            usage.note(model, True, time.monotonic() - t0)
    if meta.get("finish_reason") == "length":
        raise Truncated(raw)
    return raw


async def llm_call(llm, models: list[str], system: str, user: str, *,
                   as_json: bool, max_tokens: int, timeout: float,
                   usage: Optional[Usage] = None, temperature: float = 0.2,
                   attempts: int = 4, continuations: int = 2) -> tuple[Any, str]:
    """Probeer de modellen op volgorde. Per model: retries bij 429/5xx/netwerk
    en één herkansing bij kapotte JSON. Een afgekapte tekst wordt tot
    `continuations` keer doorgeschreven; afgekapte JSON telt als kapot.
    Geeft (antwoord, gebruikt model)."""
    last_exc: Optional[Exception] = None
    base = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for model in models:
        json_retried = False
        for attempt in range(attempts):
            try:
                try:
                    raw = await _one_call(llm, model, base, as_json=as_json, max_tokens=max_tokens,
                                          timeout=timeout, temperature=temperature, usage=usage)
                except Truncated as t:
                    if as_json:
                        raise json.JSONDecodeError("afgekapt op max_tokens", "", 0) from None
                    raw = t.args[0]
                    for _ in range(continuations):
                        try:
                            more = await _one_call(
                                llm, model, base + [
                                    {"role": "assistant", "content": raw},
                                    {"role": "user", "content": "Je antwoord werd afgekapt. Ga exact "
                                     "verder waar je stopte, zonder herhaling of inleiding."}],
                                as_json=False, max_tokens=max_tokens, timeout=timeout,
                                temperature=temperature, usage=usage)
                            raw += more
                            break
                        except Truncated as t2:
                            raw += t2.args[0]
                return (parse_llm_json(raw) if as_json else raw.strip()), model
            except json.JSONDecodeError as exc:
                last_exc = exc
                if json_retried:
                    break
                json_retried = True
                continue
            except HTTPException as exc:
                last_exc = exc
                # 4xx (behalve 429) = dit model gaat het niet worden (krediet op,
                # context te lang, onbekende alias): volgende model.
                if exc.status_code != 429 and exc.status_code < 500:
                    break
            except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                last_exc = exc
            if attempt < attempts - 1:
                await asyncio.sleep(min(45, 3 * 2 ** attempt))
        print(f"[research] model {model} gaf het op: {last_exc!r:.300}", flush=True)
    raise RuntimeError(f"alle modellen faalden ({', '.join(models)}): {last_exc!r:.300}")


# ---------------------------------------------------------------- tekst-hulp

_META_LINE = re.compile(r"^\s*[-*]\s+\*\*[^*]+\*\*:.*$", re.MULTILINE)
_HEADING = re.compile(r"^#+\s*", re.MULTILINE)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_CITE = re.compile(r"\[(S\d+(?:\s*[,;]\s*S?\d+)*)\]")


def teaser(summary: Optional[str], description: Optional[str], n: int = 420) -> str:
    """Korte, informatieve teaser voor screening: bij voorkeur de 'Key
    takeaways' van de samenvatting, zonder metadata-regels en koppen."""
    s = summary or ""
    m = re.search(r"(?im)^#+\s*(key takeaways|kernpunten|belangrijkste punten|tl;dr)\s*$", s)
    if m:
        s = s[m.end():]
    s = _META_LINE.sub("", s)
    s = _HEADING.sub("", s)
    if not s.strip():
        s = _TAGS.sub(" ", description or "")
    s = _WS.sub(" ", s.replace("**", "")).strip()
    return s[:n] + ("…" if len(s) > n else "")


def clean_text(s: Optional[str]) -> str:
    return _WS.sub(" ", _TAGS.sub(" ", s or "")).strip()


_PLACEHOLDER = re.compile(r"^[\s.…<>-]*$|^<.*>$")


def parse_plan(obj: Any, question: str) -> dict:
    """Valideer het plan. ValueError als het onbruikbaar is (te weinig
    zoekvragen, of het model gaf het sjabloon terug); dan probeert de caller
    het volgende model."""
    if not isinstance(obj, dict):
        raise ValueError("plan is geen object")
    aspects = []
    for i, a in enumerate(obj.get("aspects") or []):
        if isinstance(a, dict) and not _PLACEHOLDER.match(a.get("name") or ""):
            aspects.append({
                "id": f"a{len(aspects) + 1}",
                "name": a["name"].strip()[:80],
                "description": (a.get("description") or "").strip()[:300],
            })
    queries = []
    for q in obj.get("queries") or []:
        if (isinstance(q, str) and not _PLACEHOLDER.match(q)
                and q.strip().lower() not in {x.lower() for x in queries}):
            queries.append(q.strip()[:150])
    if len(aspects) < 2 or len(queries) < 6:
        raise ValueError(f"plan onbruikbaar: {len(aspects)} aspecten, {len(queries)} zoekvragen")
    title = obj.get("title") if isinstance(obj.get("title"), str) else ""
    rq = obj.get("question") if isinstance(obj.get("question"), str) else ""
    return {
        "title": (title if not _PLACEHOLDER.match(title) else question[:80]).strip()[:120],
        "question": (rq if not _PLACEHOLDER.match(rq) else question).strip()[:600],
        "aspects": aspects[:8],
        "queries": queries[:32],
        "include": (obj.get("include") or "").strip()[:300],
        "exclude": (obj.get("exclude") or "").strip()[:300],
    }


def parse_screen(obj: Any, n: int) -> dict[int, int]:
    """{index: score}; onbekende/kapotte regels vallen weg."""
    out: dict[int, int] = {}
    rows = obj.get("scores") if isinstance(obj, dict) else None
    for r in rows or []:
        try:
            i, s = int(r.get("i")), int(r.get("r"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 1 <= i <= n and 0 <= s <= 3:
            out[i] = s
    return out


_EVIDENCE = {"data", "case", "expert", "prediction", "anecdote"}


def parse_findings(obj: Any, aspect_ids: set[str]) -> tuple[int, list[dict]]:
    if not isinstance(obj, dict):
        raise ValueError("extractie-antwoord is geen object")
    if "findings" not in obj or not isinstance(obj.get("findings"), list):
        raise ValueError("extractie-antwoord zonder findings-lijst")
    try:
        rel = max(0, min(3, int(obj.get("relevance", 0))))
    except (TypeError, ValueError):
        rel = 0
    out = []
    for f in obj["findings"][:8]:
        if not isinstance(f, dict):
            continue
        claim = clean_text(f.get("claim"))
        if len(claim) < 15:
            continue
        aspect = f.get("aspect") if f.get("aspect") in aspect_ids else "other"
        actors = [clean_text(a)[:60] for a in (f.get("actors") or []) if isinstance(a, str) and a.strip()]
        ev = (f.get("evidence") or "").strip().lower()
        out.append({
            "claim": claim[:700],
            "aspect": aspect,
            "stance": clean_text(f.get("stance"))[:60],
            "actors": actors[:8],
            "sector": clean_text(f.get("sector"))[:60],
            "region": clean_text(f.get("region"))[:20],
            "evidence": ev if ev in _EVIDENCE else "",
            "speaker": clean_text(f.get("speaker"))[:80],
            "quote": clean_text(f.get("quote"))[:300],
        })
    if not out:
        rel = min(rel, 1)
    return rel, out


def verify_quotes(findings: list[dict], source_text: str) -> None:
    """Citaten die niet (vrijwel) letterlijk in de brontekst staan gaan eruit:
    kleine modellen 'citeren' graag hun eigen parafrase."""
    hay = _WS.sub(" ", source_text.lower())
    for f in findings:
        q = f.get("quote") or ""
        if not q:
            continue
        probe = _WS.sub(" ", q.lower()).strip(" .…\"'“”")
        # Eerste 40 tekens moeten erin staan; dat vangt parafrases af zonder
        # te struikelen over een afwijkend leesteken aan het eind.
        if len(probe) < 12 or probe[:40] not in hay:
            f["quote"] = ""


def fix_citations(report: str, n_sources: int) -> tuple[str, list[int]]:
    """Normaliseer [S3, 7] → [S3, S7], gooi nummers buiten de lijst weg.
    Geeft (rapport, gebruikte bronnummers in volgorde van eerste gebruik)."""
    used: list[int] = []

    def repl(m: re.Match) -> str:
        nums = []
        for part in re.split(r"\s*[,;]\s*", m.group(1)):
            try:
                k = int(part.lstrip("Ss"))
            except ValueError:
                continue
            if 1 <= k <= n_sources and k not in nums:
                nums.append(k)
        for k in nums:
            if k not in used:
                used.append(k)
        return "[" + ", ".join(f"S{k}" for k in nums) + "]" if nums else ""

    return _CITE.sub(repl, report), used


# ---------------------------------------------------------------- opslag


class Store(Protocol):
    async def get_run(self, run_id: str) -> dict: ...
    async def update_run(self, run_id: str, **fields) -> None: ...
    async def load_candidates(self, run_id: str) -> list[dict]: ...
    async def save_candidates(self, run_id: str, cands: list[dict]) -> None: ...
    async def set_screen(self, run_id: str, scores: dict[str, int]) -> None: ...
    async def load_findings(self, run_id: str) -> dict[str, dict]: ...
    async def save_finding(self, run_id: str, item_id: str, relevance: int,
                           findings: list[dict], model: str) -> None: ...


def can_access(run_user_id, user_id) -> bool:
    """Eigen dossiers, plus dossiers zonder eigenaar (via Okavango gestart)."""
    return run_user_id is None or str(run_user_id) == str(user_id)


class MemoryStore:
    """Voor tests en proefruns buiten de database."""

    def __init__(self):
        self.runs: dict[str, dict] = {}
        self.cands: dict[str, dict[str, dict]] = {}
        self.finds: dict[str, dict[str, dict]] = {}

    async def get_run(self, run_id):
        return dict(self.runs[run_id])

    async def update_run(self, run_id, **fields):
        self.runs.setdefault(run_id, {"id": run_id}).update(fields)

    async def load_candidates(self, run_id):
        return [dict(c) for c in self.cands.get(run_id, {}).values()]

    async def save_candidates(self, run_id, cands):
        d = self.cands.setdefault(run_id, {})
        for c in cands:
            d[c["item_id"]] = {**d.get(c["item_id"], {}), **c}

    async def set_screen(self, run_id, scores):
        for iid, s in scores.items():
            self.cands[run_id][iid]["screen_score"] = s

    async def load_findings(self, run_id):
        return {k: dict(v) for k, v in self.finds.get(run_id, {}).items()}

    async def save_finding(self, run_id, item_id, relevance, findings, model):
        self.finds.setdefault(run_id, {})[item_id] = {
            "item_id": item_id, "relevance": relevance, "findings": findings, "model": model}


_JSON_COLS = {"plan", "options", "progress", "stats", "critique", "sources", "models",
              "followups"}


class DbStore:
    def __init__(self, session_maker):
        self.sm = session_maker

    async def get_run(self, run_id):
        async with self.sm() as s:
            r = (await s.exec(sa_text("""
                SELECT id::text, user_id::text, parent_id::text, question, title, status,
                       stage_detail, plan, options, progress, stats, draft, critique,
                       report, sources, models, followups, error, created_at, updated_at,
                       finished_at
                FROM research_runs WHERE id = CAST(:i AS uuid)""").bindparams(i=run_id))).mappings().first()
        if not r:
            raise KeyError(run_id)
        return dict(r)

    async def update_run(self, run_id, **fields):
        if not fields:
            return
        sets, params = [], {"i": run_id}
        for k, v in fields.items():
            if k in _JSON_COLS:
                sets.append(f"{k} = CAST(:{k} AS jsonb)")
                params[k] = json.dumps(v, ensure_ascii=False) if v is not None else None
            elif k == "finished_at":
                sets.append("finished_at = now()" if v else "finished_at = NULL")
            else:
                sets.append(f"{k} = :{k}")
                params[k] = v
        sets.append("updated_at = now()")
        async with self.sm() as s:
            await s.exec(sa_text(
                f"UPDATE research_runs SET {', '.join(sets)} WHERE id = CAST(:i AS uuid)"
            ).bindparams(**params))
            await s.commit()

    async def load_candidates(self, run_id):
        async with self.sm() as s:
            rows = (await s.exec(sa_text("""
                SELECT item_id::text, recall_score, queries, screen_score, round
                FROM research_candidates WHERE run_id = CAST(:i AS uuid)""").bindparams(i=run_id))).all()
        return [{"item_id": r[0], "recall_score": r[1], "queries": list(r[2] or []),
                 "screen_score": r[3], "round": r[4]} for r in rows]

    async def save_candidates(self, run_id, cands):
        async with self.sm() as s:
            for c in cands:
                await s.exec(sa_text("""
                    INSERT INTO research_candidates
                        (run_id, item_id, recall_score, queries, screen_score, round)
                    VALUES (CAST(:r AS uuid), CAST(:i AS uuid), :sc, :q, :ss, :rd)
                    ON CONFLICT (run_id, item_id) DO UPDATE SET
                        recall_score = EXCLUDED.recall_score, queries = EXCLUDED.queries,
                        screen_score = COALESCE(EXCLUDED.screen_score, research_candidates.screen_score)
                """).bindparams(r=run_id, i=c["item_id"], sc=c.get("recall_score") or 0.0,
                                q=c.get("queries") or [], ss=c.get("screen_score"),
                                rd=c.get("round", 0)))
            await s.commit()

    async def set_screen(self, run_id, scores):
        async with self.sm() as s:
            for iid, sc in scores.items():
                await s.exec(sa_text("""
                    UPDATE research_candidates SET screen_score = :s
                    WHERE run_id = CAST(:r AS uuid) AND item_id = CAST(:i AS uuid)
                """).bindparams(s=sc, r=run_id, i=iid))
            await s.commit()

    async def load_findings(self, run_id):
        async with self.sm() as s:
            rows = (await s.exec(sa_text("""
                SELECT item_id::text, relevance, findings, model FROM research_findings
                WHERE run_id = CAST(:i AS uuid)""").bindparams(i=run_id))).all()
        return {r[0]: {"item_id": r[0], "relevance": r[1], "findings": r[2] or [], "model": r[3]}
                for r in rows}

    async def save_finding(self, run_id, item_id, relevance, findings, model):
        async with self.sm() as s:
            await s.exec(sa_text("""
                INSERT INTO research_findings (run_id, item_id, relevance, findings, model)
                VALUES (CAST(:r AS uuid), CAST(:i AS uuid), :rel, CAST(:f AS jsonb), :m)
                ON CONFLICT (run_id, item_id) DO UPDATE SET
                    relevance = EXCLUDED.relevance, findings = EXCLUDED.findings,
                    model = EXCLUDED.model, created_at = now()
            """).bindparams(r=run_id, i=item_id, rel=relevance,
                            f=json.dumps(findings, ensure_ascii=False), m=model))
            await s.commit()


# ---------------------------------------------------------------- archief


class Corpus:
    """Alleen-lezen toegang tot items, voor recall en extractie."""

    def __init__(self, session_maker, http_client: httpx.AsyncClient):
        self.sm = session_maker
        self.http = http_client

    async def _ranked(self, q: str) -> list[list[str]]:
        qvec = await search_index.embed_query(self.http, q)
        lists: list[list[str]] = []
        async with self.sm() as s:
            tsq, _ = await search_query.build(s, q)
            if tsq:
                rows = (await s.exec(sa_text("""
                    SELECT i.id::text FROM items i
                    WHERE i.search_tsv @@ CAST(:tsq AS tsquery)
                    ORDER BY ts_rank(i.search_tsv, CAST(:tsq AS tsquery)) DESC,
                             i.published_at DESC NULLS LAST
                    LIMIT :p""").bindparams(tsq=tsq, p=RECALL_POOL))).all()
                lists.append([r[0] for r in rows])
            if qvec:
                await s.exec(sa_text(f"SET LOCAL hnsw.ef_search = {max(100, 4 * RECALL_POOL)}"))
                rows = (await s.exec(sa_text("""
                    SELECT id::text FROM (
                        SELECT i.id, i.search_embedding <=> CAST(:v AS vector) AS d
                        FROM items i WHERE i.search_embedding IS NOT NULL
                        ORDER BY d LIMIT :p) nn
                    WHERE d <= :maxd ORDER BY d""").bindparams(
                    v=search_index._vec_literal(qvec), p=RECALL_POOL,
                    maxd=search_index.MAX_DISTANCE))).all()
                lists.append([r[0] for r in rows])
        return lists

    async def recall(self, queries: list[str]) -> list[dict]:
        """RRF over alle (zoekvraag × ranglijst)-combinaties. Een item dat bij
        veel zoekvragen opduikt wint — precies wat je wilt bij een brede vraag."""
        agg: dict[str, dict] = {}
        for q in queries:
            try:
                lists = await self._ranked(q)
            except Exception as e:  # één kapotte zoekvraag mag de run niet slopen
                print(f"[research] recall faalde voor {q!r}: {e!r}", flush=True)
                continue
            for ids in lists:
                for rank, iid in enumerate(ids, 1):
                    e = agg.setdefault(iid, {"item_id": iid, "recall_score": 0.0, "queries": []})
                    e["recall_score"] += 1.0 / (RRF_K + rank)
                    if q not in e["queries"]:
                        e["queries"].append(q)
        out = sorted(agg.values(), key=lambda c: -c["recall_score"])
        for c in out:
            c["recall_score"] = round(c["recall_score"], 5)
        return out

    async def meta(self, item_ids: list[str]) -> dict[str, dict]:
        if not item_ids:
            return {}
        async with self.sm() as s:
            rows = (await s.exec(sa_text("""
                SELECT i.id::text, i.title, s.name, i.format::text, i.published_at,
                       CASE WHEN left(i.external_id, 4) = 'http' THEN i.external_id
                            ELSE i.media_url END,
                       i.summary, i.description
                FROM items i JOIN sources s ON s.id = i.source_id
                WHERE i.id = ANY(CAST(:ids AS uuid[]))""").bindparams(ids=item_ids))).all()
        return {r[0]: {"item_id": r[0], "title": r[1] or "(zonder titel)", "source": r[2],
                       "format": r[3],
                       "date": r[4].date().isoformat() if r[4] else None,
                       "url": r[5], "teaser": teaser(r[6], r[7])} for r in rows}

    async def content(self, item_id: str) -> Optional[dict]:
        async with self.sm() as s:
            r = (await s.exec(sa_text("""
                SELECT i.title, s.name, i.format::text, i.published_at, i.summary,
                       i.transcript, i.description, i.author
                FROM items i JOIN sources s ON s.id = i.source_id
                WHERE i.id = CAST(:i AS uuid)""").bindparams(i=item_id))).first()
            if not r:
                return None
            lessons = (await s.exec(sa_text("""
                SELECT title, body FROM lessons WHERE item_id = CAST(:i AS uuid)
                ORDER BY idx LIMIT 15""").bindparams(i=item_id))).all()
        return {"title": r[0], "source": r[1], "format": r[2],
                "date": r[3].date().isoformat() if r[3] else None,
                "summary": r[4] or "", "transcript": r[5] or "", "description": r[6] or "",
                "author": r[7] or "", "lessons": [(l[0], l[1]) for l in lessons]}


def extract_input(c: dict, budget: int = EXTRACT_BODY_CHARS) -> tuple[str, str]:
    """(prompt-tekst over de bron, brontekst voor citaatcontrole)."""
    parts = [f"Titel: {c['title']}", f"Bron: {c['source']} ({c['format']})"]
    if c.get("author"):
        parts.append(f"Auteur/spreker: {c['author']}")
    if c.get("date"):
        parts.append(f"Datum: {c['date']}")
    summary = (c.get("summary") or "").strip()
    body = summary[:budget]
    raw_bits = [summary]
    if len(summary) < EXTRACT_MIN_SUMMARY:
        extra = clean_text(c.get("transcript")) or clean_text(c.get("description"))
        if extra:
            room = max(4000, budget - len(body))
            body = (body + "\n\nBrontekst:\n" + extra[:room]).strip()
            raw_bits.append(extra[:room])
    if body:
        parts.append(f"\nSamenvatting:\n{body}")
    if c.get("lessons"):
        parts.append("\nKernlessen:\n" + "\n".join(f"- {t}: {b}" for t, b in c["lessons"]))
        raw_bits.extend(f"{t} {b}" for t, b in c["lessons"])
    # Citaten mogen ook uit het transcript komen, ook als het niet in de prompt zat.
    raw_bits.append(c.get("transcript") or "")
    return "\n".join(parts), "\n".join(raw_bits)


def _plan_block(plan: dict) -> str:
    asp = "\n".join(f"- {a['id']}: {a['name']} — {a['description']}" for a in plan["aspects"])
    lines = [f"Onderzoeksvraag: {plan['question']}", f"Aspecten:\n{asp}"]
    if plan.get("include"):
        lines.append(f"Relevant: {plan['include']}")
    if plan.get("exclude"):
        lines.append(f"Niet relevant: {plan['exclude']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- pijplijn


ProgressFn = Callable[[], Awaitable[bool]]  # True = annuleren


@dataclass
class Ctx:
    store: Any
    corpus: Any
    llm: Any
    usage: Usage = field(default_factory=Usage)
    should_cancel: Optional[ProgressFn] = None
    # Rekentijd van eerdere pogingen (hervatten na herstart of "verder"):
    # statistiek telt op over alle pogingen in plaats van alleen de laatste.
    base_secs: float = 0.0
    t0: float = field(default_factory=time.monotonic)


def _resume_usage(ctx: Ctx, stats: Optional[dict]) -> None:
    stats = stats or {}
    ctx.usage.calls = int(stats.get("llm_calls") or 0)
    ctx.usage.failures = int(stats.get("llm_failures") or 0)
    ctx.usage.by_model = {m: {"calls": int(v.get("calls", 0)), "failures": int(v.get("failures", 0)),
                              "secs": float(v.get("secs", 0.0))}
                          for m, v in (stats.get("by_model") or {}).items() if isinstance(v, dict)}
    ctx.base_secs = float(stats.get("secs") or 0)
    ctx.t0 = time.monotonic()


def _stats(ctx: Ctx) -> dict:
    return {"llm_calls": ctx.usage.calls, "llm_failures": ctx.usage.failures,
            "by_model": ctx.usage.by_model,
            "secs": round(ctx.base_secs + time.monotonic() - ctx.t0)}


async def _check_cancel(ctx: Ctx) -> None:
    if ctx.should_cancel and await ctx.should_cancel():
        raise Cancelled()


async def _stage(ctx: Ctx, run_id: str, status: str, **progress) -> None:
    await ctx.store.update_run(run_id, status=status, progress={"stage": status, **progress},
                               stats=_stats(ctx))


async def step_plan(ctx: Ctx, run: dict) -> dict:
    if run.get("plan"):
        return run["plan"]
    await _stage(ctx, run["id"], "planning")
    plan, errors = None, []
    for m in PLAN_MODELS:
        try:
            obj, model = await llm_call(ctx.llm, [m], PLAN_SYSTEM, run["question"],
                                        as_json=True, max_tokens=8000, timeout=240,
                                        usage=ctx.usage, attempts=2)
            plan = parse_plan(obj, run["question"])
            plan["model"] = model
            break
        except (RuntimeError, ValueError) as e:
            errors.append(f"{m}: {e}")
    if plan is None:
        raise RuntimeError("geen bruikbaar plan: " + " | ".join(errors)[:600])
    await ctx.store.update_run(run["id"], plan=plan, title=plan["title"])
    return plan


async def _reuse_parent_screen(ctx: Ctx, run: dict, cands: list[dict]) -> None:
    """Vernieuwing: screening van de vorige run overnemen voor dezelfde items."""
    if not run.get("parent_id"):
        return
    prev = {c["item_id"]: c.get("screen_score")
            for c in await ctx.store.load_candidates(run["parent_id"])}
    for c in cands:
        if c.get("screen_score") is None and prev.get(c["item_id"]) is not None:
            c["screen_score"] = prev[c["item_id"]]


async def step_recall(ctx: Ctx, run: dict, plan: dict) -> list[dict]:
    cands = await ctx.store.load_candidates(run["id"])
    if any(c.get("round", 0) == 0 for c in cands):
        return cands
    await _stage(ctx, run["id"], "recall", queries=len(plan["queries"]))
    cands = await ctx.corpus.recall(plan["queries"])
    for c in cands:
        c["round"] = 0
    await _reuse_parent_screen(ctx, run, cands)
    await ctx.store.save_candidates(run["id"], cands)
    return cands


async def screen_items(ctx: Ctx, run: dict, plan: dict, pool: list[dict], stage: str) -> None:
    """Scoor alle items in pool zonder screen_score (in place + opslag)."""
    todo = [c for c in pool if c.get("screen_score") is None]
    if not todo:
        return
    meta = await ctx.corpus.meta([c["item_id"] for c in todo])
    batches = [todo[i:i + SCREEN_BATCH] for i in range(0, len(todo), SCREEN_BATCH)]
    done = len(pool) - len(todo)
    await _stage(ctx, run["id"], stage, step="screening", done=done, total=len(pool))
    head = _plan_block(plan)

    async def one(batch: list[dict]) -> None:
        nonlocal done
        await _check_cancel(ctx)
        lines = []
        for k, c in enumerate(batch, 1):
            m = meta.get(c["item_id"]) or {}
            lines.append(f"{k}. {m.get('title', '?')} — {m.get('source', '?')}, "
                         f"{m.get('date') or '?'} ({m.get('format', '?')})\n   {m.get('teaser', '')}")
        user = f"{head}\n\nBronnen:\n" + "\n".join(lines)
        try:
            obj, _ = await llm_call(ctx.llm, SCREEN_MODELS, SCREEN_SYSTEM, user,
                                    as_json=True, max_tokens=2500, timeout=120,
                                    usage=ctx.usage, temperature=0.0)
            scores = parse_screen(obj, len(batch))
        except RuntimeError as e:
            print(f"[research] screening-batch faalde: {e}", flush=True)
            scores = {}
        # Geen score = model sloeg 'm over: liever 1 (twijfelgeval) dan
        # opnieuw proberen tot in de eeuwigheid.
        res = {c["item_id"]: scores.get(k, 1) for k, c in enumerate(batch, 1)}
        await ctx.store.set_screen(run["id"], res)
        for c in batch:
            c["screen_score"] = res[c["item_id"]]
        done += len(batch)
        await _stage(ctx, run["id"], stage, step="screening", done=done, total=len(pool))

    await asyncio.gather(*(one(b) for b in batches))


def select_for_extraction(pool: list[dict], limit: int) -> list[dict]:
    """Eerst alles met screen >= 2 (beste eerst), dan aanvullen met de
    twijfelgevallen (screen 1) die het vaakst gevonden werden — de extractie
    zegt daarna zelf of er iets bruikbaars in zat."""
    def by_rank(c: dict) -> tuple:
        return (-(c.get("screen_score") or 0), -c["recall_score"])
    strong = sorted((c for c in pool if (c.get("screen_score") or 0) >= SCREEN_MIN), key=by_rank)
    weak = sorted((c for c in pool if c.get("screen_score") == 1), key=by_rank)
    room = max(0, min(EXTRACT_FILL_LOW, limit - len(strong)))
    return (strong + weak[:room])[:limit]


async def extract_items(ctx: Ctx, run: dict, plan: dict, chosen: list[dict], stage: str) -> None:
    have = await ctx.store.load_findings(run["id"])
    if run.get("parent_id"):
        prev = await ctx.store.load_findings(run["parent_id"])
        for c in chosen:
            p = prev.get(c["item_id"])
            if p and c["item_id"] not in have:
                await ctx.store.save_finding(run["id"], c["item_id"], p["relevance"],
                                             p["findings"], p.get("model") or "")
                have[c["item_id"]] = p
    todo = [c for c in chosen if c["item_id"] not in have]
    done = len(chosen) - len(todo)
    await _stage(ctx, run["id"], stage, step="extracting", done=done, total=len(chosen))
    head = _plan_block(plan)
    aspect_ids = {a["id"] for a in plan["aspects"]}

    async def one(c: dict) -> None:
        nonlocal done
        await _check_cancel(ctx)
        content = await ctx.corpus.content(c["item_id"])
        if content is None:
            done += 1
            return
        prompt, source_text = extract_input(content)
        user = f"{head}\n\n=== BRON ===\n{prompt}"
        rel, findings, model = 0, [], ""
        try:
            for _ in range(2):  # kapot schema → één nieuwe poging
                obj, model = await llm_call(ctx.llm, EXTRACT_MODELS, EXTRACT_SYSTEM, user,
                                            as_json=True, max_tokens=4000, timeout=240,
                                            usage=ctx.usage, temperature=0.1)
                try:
                    rel, findings = parse_findings(obj, aspect_ids)
                    break
                except ValueError:
                    continue
            verify_quotes(findings, source_text)
            await ctx.store.save_finding(run["id"], c["item_id"], rel, findings, model)
        except RuntimeError as e:
            print(f"[research] extractie faalde voor {c['item_id']}: {e}", flush=True)
        done += 1
        if done % 3 == 0 or done == len(chosen):
            await _stage(ctx, run["id"], stage, step="extracting", done=done, total=len(chosen))

    await asyncio.gather(*(one(c) for c in todo))


async def step_screen(ctx: Ctx, run: dict, plan: dict, cands: list[dict]) -> list[dict]:
    pool = sorted((c for c in cands if c.get("round", 0) == 0),
                  key=lambda c: -c["recall_score"])[:SCREEN_MAX]
    await screen_items(ctx, run, plan, pool, "screening")
    return pool


async def step_extract(ctx: Ctx, run: dict, plan: dict, pool: list[dict]) -> None:
    await extract_items(ctx, run, plan, select_for_extraction(pool, EXTRACT_MAX), "extracting")


def coverage_summary(plan: dict, findings: dict[str, dict], meta: dict[str, dict]) -> str:
    """Wat de eerste ronde opleverde, per aspect: aantallen, actoren, regio's,
    bewijssoort en een paar voorbeeldbeweringen. Input voor de verdieping."""
    names = {a["id"]: a["name"] for a in plan["aspects"]}
    per: dict[str, list[dict]] = {a["id"]: [] for a in plan["aspects"]}
    per_source: Counter = Counter()
    for iid, f in findings.items():
        if f["relevance"] < 1:
            continue
        per_source[(meta.get(iid) or {}).get("source", "?")] += 1
        for x in f["findings"]:
            per.setdefault(x["aspect"], []).append(x)
    lines = []
    for aid, xs in per.items():
        actors = Counter(a for x in xs for a in x.get("actors") or [])
        regions = Counter(x.get("region") or "?" for x in xs)
        ev = Counter(x.get("evidence") or "?" for x in xs)
        lines.append(f"## {names.get(aid, 'Overig')} ({aid}): {len(xs)} bevindingen")
        lines.append("regio's: " + ", ".join(f"{k} {v}" for k, v in regions.most_common(5)))
        lines.append("bewijs: " + ", ".join(f"{k} {v}" for k, v in ev.most_common(5)))
        if actors:
            lines.append("actoren: " + ", ".join(a for a, _ in actors.most_common(15)))
        for x in xs[:4]:
            lines.append(f"- {x['claim'][:220]}")
    lines.append("\nMeest gebruikte bronnen: " + ", ".join(
        f"{k} ({v})" for k, v in per_source.most_common(10)))
    return "\n".join(lines)


async def step_deepen(ctx: Ctx, run: dict, plan: dict, cands: list[dict]) -> dict[str, dict]:
    """Tweede ronde: een sterk model ziet wat de eerste ronde opleverde en
    zoekt gericht naar wat ontbreekt (dunne aspecten, tegengeluid, andere
    regio's of sectoren, ontbrekende spelers, harder bewijs)."""
    findings = await ctx.store.load_findings(run["id"])
    deepen = plan.get("deepen")
    if deepen is None:
        await _stage(ctx, run["id"], "deepening", step="planning")
        meta = await ctx.corpus.meta(list(findings))
        user = (f"{_plan_block(plan)}\n\nAl gebruikte zoekvragen:\n"
                + "\n".join(f"- {q}" for q in plan["queries"])
                + f"\n\n=== OPBRENGST EERSTE RONDE ===\n{coverage_summary(plan, findings, meta)}")
        try:
            obj, model = await llm_call(ctx.llm, PLAN_MODELS, DEEPEN_SYSTEM, user, as_json=True,
                                        max_tokens=6000, timeout=240, usage=ctx.usage, attempts=2)
            if not isinstance(obj, dict):
                raise RuntimeError("verdieping is geen object")
            used = {q.lower() for q in plan["queries"]}
            qs = [q.strip()[:150] for q in (obj.get("queries") or [])
                  if isinstance(q, str) and q.strip() and q.strip().lower() not in used][:16]
            deepen = {"gaps": clean_text(obj.get("gaps"))[:1200], "queries": qs, "model": model}
        except RuntimeError as e:
            print(f"[research] verdieping overgeslagen: {e}", flush=True)
            deepen = {"gaps": "", "queries": [], "model": None}
        plan = {**plan, "deepen": deepen}
        await ctx.store.update_run(run["id"], plan=plan)
    if not deepen["queries"]:
        return findings

    known = {c["item_id"] for c in cands}
    round1 = [c for c in cands if c.get("round", 0) == 1]
    if not round1:
        await _stage(ctx, run["id"], "deepening", step="recall", queries=len(deepen["queries"]))
        new = [c for c in await ctx.corpus.recall(deepen["queries"]) if c["item_id"] not in known]
        round1 = new[:DEEPEN_CANDIDATES]
        for c in round1:
            c["round"] = 1
        await _reuse_parent_screen(ctx, run, round1)
        await ctx.store.save_candidates(run["id"], round1)
        cands.extend(round1)
    await screen_items(ctx, run, plan, round1, "deepening")
    await extract_items(ctx, run, plan, select_for_extraction(round1, DEEPEN_EXTRACT), "deepening")
    return await ctx.store.load_findings(run["id"])


def build_sources(findings: dict[str, dict], meta: dict[str, dict],
                  cands: dict[str, dict]) -> list[dict]:
    """Bronnen met bevindingen, gesorteerd op datum (oud → nieuw) zodat S-nummers
    ook iets over tijd zeggen. Relevance 0 valt weg."""
    rows = []
    for iid, f in findings.items():
        if not f["findings"] or f["relevance"] < 1 or iid not in meta:
            continue
        m = meta[iid]
        rows.append({**{k: m[k] for k in ("item_id", "title", "source", "format", "date", "url")},
                     "relevance": f["relevance"],
                     "recall_score": (cands.get(iid) or {}).get("recall_score", 0.0),
                     "findings": f["findings"]})
    rows.sort(key=lambda r: (r["date"] or "0000", r["title"]))
    for k, r in enumerate(rows, 1):
        r["ref"] = f"S{k}"
    return rows


def date_spread(sources: list[dict]) -> str:
    """Bronnen per jaar, en per kwartaal voor het meest recente jaar: de
    schrijver moet zien of 'verschuiving in de tijd' over jaren of maanden gaat."""
    years = Counter((s.get("date") or "?")[:4] for s in sources)
    out = ", ".join(f"{y}: {n}" for y, n in sorted(years.items()))
    last = max((y for y in years if y != "?"), default=None)
    if last:
        q = Counter(f"Q{(int(s['date'][5:7]) - 1) // 3 + 1}" for s in sources
                    if (s.get("date") or "").startswith(last))
        out += f" (waarvan {last} per kwartaal: " + ", ".join(f"{k} {v}" for k, v in sorted(q.items())) + ")"
    return out


def findings_block(plan: dict, sources: list[dict],
                   max_chars: int = WRITE_MAX_FINDINGS_CHARS) -> str:
    """Bronnenlijst + bevindingen per aspect. Bij overschrijding van het budget
    vallen eerst de minst relevante bronnen af (bevindingen, niet bronnen in de lijst)."""
    ranked = sorted(sources, key=lambda s: (-s["relevance"], -s["recall_score"]))
    keep: set[str] = set()
    size = 0
    for s in ranked:
        cost = sum(len(f["claim"]) + len(f.get("quote") or "") + 80 for f in s["findings"])
        if size + cost > max_chars and keep:
            break
        keep.add(s["ref"])
        size += cost

    src_lines = [f"[{s['ref']}] {s['date'] or '?'} · {s['source']} ({s['format']}) — {s['title']}"
                 for s in sources if s["ref"] in keep]
    names = {a["id"]: a["name"] for a in plan["aspects"]}
    by_aspect: dict[str, list[str]] = {a["id"]: [] for a in plan["aspects"]}
    by_aspect["other"] = []
    for s in sources:
        if s["ref"] not in keep:
            continue
        for f in s["findings"]:
            bits = [f"[{s['ref']}] {f['claim']}"]
            meta = ", ".join(x for x in (f.get("stance"), f.get("evidence"), f.get("region"),
                                         f.get("sector")) if x)
            if meta:
                bits.append(f"({meta})")
            if f.get("actors"):
                bits.append("actoren: " + ", ".join(f["actors"]))
            if f.get("speaker"):
                bits.append(f"spreker: {f['speaker']}")
            if f.get("quote"):
                bits.append(f"citaat: “{f['quote']}”")
            by_aspect.setdefault(f["aspect"], []).append(" ".join(bits))
    blocks = []
    for aid, lines in by_aspect.items():
        if lines:
            blocks.append(f"### {names.get(aid, 'Overig')} ({aid})\n" + "\n".join(f"- {x}" for x in lines))
    return ("BRONNEN:\n" + "\n".join(src_lines) + "\n\nBEVINDINGEN PER ASPECT:\n\n"
            + "\n\n".join(blocks))


async def step_write(ctx: Ctx, run: dict, plan: dict, findings: dict[str, dict],
                     cands: list[dict]) -> None:
    meta = await ctx.corpus.meta(list(findings))
    sources = build_sources(findings, meta, {c["item_id"]: c for c in cands})
    if not sources:
        raise RuntimeError("geen bruikbare bevindingen gevonden — de vraag lijkt buiten het archief te vallen")
    block = findings_block(plan, sources)
    head = (f"{today_note()}Titel: {plan['title']}\n{_plan_block(plan)}\n\n"
            f"Aantal bronnen met bevindingen: {len(sources)} "
            f"(periode {sources[0]['date']} t/m {sources[-1]['date']}).\n"
            f"Spreiding in de tijd: {date_spread(sources)}\n\n")
    models: dict = dict(run.get("models") or {})
    models["plan"] = plan.get("model")
    if (plan.get("deepen") or {}).get("model"):
        models["deepen"] = plan["deepen"]["model"]

    draft = run.get("draft")
    if not draft:
        await _stage(ctx, run["id"], "writing", sources=len(sources))
        draft, models["write"] = await llm_call(
            ctx.llm, WRITE_MODELS, SYNTH_SYSTEM, head + block, as_json=False,
            max_tokens=32000, timeout=900, usage=ctx.usage, temperature=0.3, attempts=2)
        await ctx.store.update_run(run["id"], draft=draft, models=models,
                                   sources=_public_sources(sources))
    await _check_cancel(ctx)

    critique = run.get("critique")
    if critique is None:
        await _stage(ctx, run["id"], "critiquing", sources=len(sources))
        crit_user = f"{head}=== CONCEPT ===\n{draft}\n\n=== BEVINDINGEN ===\n{block}"
        try:
            # Redeneermodellen (Gemini 2.5, DeepSeek, Kimi) tellen hun denkwerk mee
            # in max_tokens: ruim budget, anders blijft er geen JSON over.
            critique, models["critique"] = await llm_call(
                ctx.llm, CRITIQUE_MODELS, CRITIQUE_SYSTEM, crit_user,
                as_json=True, max_tokens=24000, timeout=900, usage=ctx.usage,
                temperature=0.1, attempts=2)
            if not isinstance(critique, dict):
                raise RuntimeError("kritiek is geen object")
            critique["issues"] = drop_date_disputes(
                [i for i in (critique.get("issues") or []) if isinstance(i, dict)])
        except RuntimeError as e:
            print(f"[research] JSON-kritiek faalde, probeer als tekst: {e}", flush=True)
            try:
                text, models["critique"] = await llm_call(
                    ctx.llm, CRITIQUE_MODELS, CRITIQUE_SYSTEM + CRITIQUE_TEXT_SUFFIX, crit_user,
                    as_json=False, max_tokens=24000, timeout=900, usage=ctx.usage,
                    temperature=0.1, attempts=1)
                critique = {"verdict": "", "issues": [], "text": text[:20000]}
            except RuntimeError as e2:
                critique = {"verdict": f"kritiek overgeslagen: {e2}"[:300], "issues": []}
        await ctx.store.update_run(run["id"], critique=critique, models=models)
    await _check_cancel(ctx)

    report = draft
    issues = [i for i in (critique.get("issues") or []) if isinstance(i, dict)]
    if issues or critique.get("text"):
        await _stage(ctx, run["id"], "revising", issues=len(issues))
        issue_txt = "\n".join(f"- [{i.get('type', '')}] {i.get('where', '')}: {i.get('problem', '')} "
                              f"→ {i.get('fix', '')}" for i in issues) or critique.get("text", "")
        revise_user = (f"{head}{block}\n\n=== JOUW CONCEPT ===\n{draft}\n\n=== KRITIEK ===\n"
                       f"{critique.get('verdict', '')}\n{issue_txt}")
        report, models["revise"] = draft, None
        tried: list[str] = []
        # Max twee pogingen, elk met een ander model: een herziening die geen
        # dossier is (denkwerk als tekst, ontspoord doorschrijven) valt terug.
        for _ in range(2):
            chain = [m for m in WRITE_MODELS if m not in tried]
            if not chain:
                break
            try:
                text, used = await llm_call(
                    ctx.llm, chain, REVISE_SYSTEM, revise_user,
                    as_json=False, max_tokens=32000, timeout=900, usage=ctx.usage,
                    temperature=0.3, attempts=2, continuations=1)
            except RuntimeError as e:
                print(f"[research] herziening faalde, concept blijft staan: {e}", flush=True)
                break
            tried.append(used)
            cleaned = clean_revision(draft, text)
            if cleaned is not None:
                report, models["revise"] = cleaned, used
                break
            print(f"[research] herziening van {used} afgekeurd ({len(text.split())} woorden, "
                  f"begint met {text[:60]!r}); probeer volgend model", flush=True)
    report, used = fix_citations(report, len(sources))
    pub = _public_sources(sources)
    for s in pub:
        s["cited"] = int(s["ref"][1:]) in used
    await ctx.store.update_run(run["id"], report=report, sources=pub, models=models)


def _public_sources(sources: list[dict]) -> list[dict]:
    return [{k: s[k] for k in ("ref", "item_id", "title", "source", "format", "date",
                               "url", "relevance", "findings")} for s in sources]


async def run_pipeline(ctx: Ctx, run_id: str) -> None:
    """Draai (of hervat) een run tot het eind. Fouten → status failed."""
    try:
        run = await ctx.store.get_run(run_id)
        _resume_usage(ctx, run.get("stats"))
        if run.get("parent_id") and not run.get("plan"):
            parent = await ctx.store.get_run(run["parent_id"])
            if parent.get("plan"):
                await ctx.store.update_run(run_id, plan=parent["plan"], title=parent.get("title"))
                run = await ctx.store.get_run(run_id)
        plan = await step_plan(ctx, run)
        await _check_cancel(ctx)
        cands = await step_recall(ctx, run, plan)
        await _check_cancel(ctx)
        pool = await step_screen(ctx, run, plan, cands)
        await _check_cancel(ctx)
        await step_extract(ctx, run, plan, pool)
        await _check_cancel(ctx)
        findings = await step_deepen(ctx, run, plan, cands)
        await _check_cancel(ctx)
        run = await ctx.store.get_run(run_id)
        plan = run.get("plan") or plan
        await step_write(ctx, run, plan, findings, cands)
        n_find = sum(len(f["findings"]) for f in findings.values())
        await ctx.store.update_run(
            run_id, status="done", error=None, finished_at=True,
            progress={"stage": "done", "candidates": len(cands),
                      "screened": sum(1 for c in cands if c.get("screen_score") is not None),
                      "extracted": len(findings), "findings": n_find},
            stats=_stats(ctx))
    except Cancelled:
        await ctx.store.update_run(run_id, status="cancelled", finished_at=True, stats=_stats(ctx))
    except Exception as e:
        print(f"[research] run {run_id} faalde: {e!r}", flush=True)
        await ctx.store.update_run(run_id, status="failed", error=str(e)[:1000], finished_at=True,
                                   stats=_stats(ctx))


# ---------------------------------------------------------------- na afloop

ASK_MODELS = _models("RESEARCH_ASK_MODELS", "stroom-sonnet,stroom-deep,cloud-kimi")


def plan_from_run(run: dict) -> dict:
    return run.get("plan") or {"title": run.get("title") or "", "question": run["question"],
                               "aspects": [], "queries": []}


def clean_revision(draft: str, text: str) -> Optional[str]:
    """Een herziening moet een dossier zijn: beginnen bij de titelkop en
    ongeveer zo lang als het concept. Opus gaf in een live-run (2026-11) zijn
    overwegingen als tekst ("De gebruiker vraagt me…", 46k woorden). Losse
    aanloop vóór de eerste kop wordt weggeknipt; anders None (= afkeuren)."""
    text = (text or "").strip()
    m = re.search(r"^# \S", text, re.M)
    if not m:
        return None
    if m.start() > 0:
        if m.start() > 600:
            return None
        text = text[m.start():]
    n_draft, n = max(len(draft.split()), 1), len(text.split())
    if not (0.5 * n_draft <= n <= 1.6 * n_draft):
        return None
    if re.search(r"^(De gebruiker vraagt|Ik moet |Laten we |Let me |I need to )", text, re.M):
        return None
    return text


_MONTHS_NL = ("januari", "februari", "maart", "april", "mei", "juni", "juli",
              "augustus", "september", "oktober", "november", "december")


def today_note(today: Optional[date] = None) -> str:
    """Modellen kennen de datum niet en houden jaartallen na hun trainingsdata
    voor toekomst. Een proefrun (2026-11) noemde het archief daardoor een
    'prospectief scenario-archief'. Dit zet de datum vooraan in de prompt."""
    d = today or date.today()
    return (f"Vandaag is het {d.day} {_MONTHS_NL[d.month - 1]} {d.year}. Alle bronnen "
            f"zijn echte, al verschenen items uit het archief (t/m vandaag); jaartallen "
            f"tot en met {d.year} zijn verleden of heden, geen toekomst.\n\n")


# Kritiek die de datering zelf aanvecht ("fictief", "nog niet verschenen") is
# een artefact van de trainingsdata van het kritiekmodel, geen inhoudelijk punt.
_DATE_DISPUTE = re.compile(
    r"prospectie|fictie|fictief|fictieve|scenario-archief|speculatieve? (?:dataset|archief|exercitie)"
    r"|nog niet (?:verschenen|gepubliceerd)|in de toekomst|toekomstige? (?:bron|publicatie|datum)"
    r"|fictional|hypothetical (?:dataset|archive)|future[- ]dated|not yet (?:published|happened)",
    re.I)


def drop_date_disputes(issues: list[dict]) -> list[dict]:
    keep = []
    for i in issues:
        txt = " ".join(str(i.get(k, "")) for k in ("where", "problem", "fix"))
        if _DATE_DISPUTE.search(txt) and re.search(r"\b20\d\d\b", txt):
            print(f"[research] kritiekpunt over datering genegeerd: {txt[:160]}", flush=True)
            continue
        keep.append(i)
    return keep


def sources_for_prompt(run: dict) -> list[dict]:
    """Opgeslagen (publieke) bronnen terug naar het formaat van findings_block."""
    return [{**s, "recall_score": 0.0} for s in (run.get("sources") or [])]


async def ask(llm, run: dict, question: str) -> tuple[str, str]:
    """Vervolgvraag op een afgerond dossier. Geeft (antwoord, model)."""
    if not run.get("report"):
        raise ValueError("dossier is nog niet af")
    plan = plan_from_run(run)
    block = findings_block(plan, sources_for_prompt(run))
    prev = "".join(f"\n\nEerdere vraag: {f['question']}\nAntwoord: {f['answer']}"
                   for f in (run.get("followups") or [])[-4:])
    user = (f"{today_note()}=== DOSSIER ===\n{run['report']}\n\n=== BEVINDINGEN ===\n{block}{prev}"
            f"\n\n=== VRAAG ===\n{question}")
    answer, model = await llm_call(llm, ASK_MODELS, ASK_SYSTEM, user, as_json=False,
                                   max_tokens=8000, timeout=300, temperature=0.2, attempts=2)
    answer, _ = fix_citations(answer, len(run.get("sources") or []))
    return answer, model


def to_markdown(run: dict, item_url: Callable[[str], str]) -> str:
    """Dossier als losstaand markdown-document (Obsidian/download): de
    [S12]-verwijzingen worden links naar een bronnenlijst onderaan."""
    sources = run.get("sources") or []
    by_ref = {s["ref"]: s for s in sources}

    def link(m: re.Match) -> str:
        refs = [r.strip() for r in m.group(1).split(",")]
        return "[" + ", ".join(f"[{r}](#{r.lower()})" if r in by_ref else r for r in refs) + "]"

    body = re.sub(r"\[(S\d+(?:\s*,\s*S\d+)*)\]", link, run.get("report") or "")
    lines = [body.rstrip(), "", "---", "", "## Bronnen", ""]
    for s in sources:
        if not s.get("cited", True):
            continue
        lines.append(f'<a id="{s["ref"].lower()}"></a>**{s["ref"]}** · {s.get("date") or "?"} · '
                     f'{s["source"]} — [{s["title"]}]({item_url(s["item_id"])})')
    for f in run.get("followups") or []:
        lines += ["", f"### Vervolgvraag: {f['question']}", "", f["answer"]]
    q = run.get("plan", {}).get("question") or run["question"]
    meta = (f"---\ntype: stroom-dossier\nvraag: {json.dumps(q, ensure_ascii=False)}\n"
            f"bronnen: {len(sources)}\ngemaakt: {str(run.get('finished_at') or '')[:10]}\n---\n\n")
    return meta + "\n".join(lines) + "\n"


# ---------------------------------------------------------------- jobs

_job_lock = asyncio.Lock()
_tasks: set[asyncio.Task] = set()
_cancel: set[str] = set()


def request_cancel(run_id: str) -> None:
    _cancel.add(run_id)


def spawn(session_maker, llm, http_client, run_id: str) -> None:
    """Start de run op de achtergrond. Runs lopen één voor één (gedeeld
    Ollama-budget); de rest wacht als 'queued'."""

    async def _go():
        async with _job_lock:
            if run_id in _cancel:
                _cancel.discard(run_id)
                await DbStore(session_maker).update_run(run_id, status="cancelled", finished_at=True)
                return

            async def should_cancel() -> bool:
                return run_id in _cancel

            ctx = Ctx(store=DbStore(session_maker), corpus=Corpus(session_maker, http_client),
                      llm=llm, should_cancel=should_cancel)
            await run_pipeline(ctx, run_id)
            _cancel.discard(run_id)

    task = asyncio.create_task(_go())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def resume_interrupted(session_maker, llm, http_client) -> int:
    """Bij opstart: runs die midden in een stap zaten opnieuw oppakken."""
    async with session_maker() as s:
        rows = (await s.exec(sa_text("""
            SELECT id::text FROM research_runs
            WHERE status NOT IN ('done', 'failed', 'cancelled')
            ORDER BY created_at""" ))).all()
    for r in rows:
        spawn(session_maker, llm, http_client, r[0])
    return len(rows)
