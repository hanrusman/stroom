"""Quality-scoring via een Jev-decision model (Ollama /v1/systemone) op de A2.

Waarom: de embedding-interest werkte averechts en cloud-quality clusterde op
5-6. In de eval van 2026-10-02 (54 gelikete + 28 expliciete favorieten vs 300
random items) haalde nimble-quality AUC 0.82 / 0.57 tegen 0.69 / 0.59 voor de
cloud-quality en 0.48 / 0.33 voor de oude hybride score.

Niet inline maar in batches (run_batch, elke DECISION_INTERVAL_SEC): het model
laden kost op de gedeelde A2 minuten, dus één keer laden per batch; daarna laat
de stroom-decision container het na OLLAMA_KEEP_ALIVE weer los. Lukt het niet
(A2 vol, container weg), dan blijft quality_score NULL, probeert de volgende
ronde het opnieuw en gaat er één ntfy-melding per storing uit.

Decision models geven geen uitleg (geen reasoning-stap). In
quality_score_detail bewaren we wat ze wél geven: deelscores, de kansverdeling
per niveau en confidence, plus de versie van het interesseprofiel.
"""
import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import text as sa_text

from services.score_guards import auto_score_guard

SCORER_MODE = os.environ.get("SCORER_MODE", "legacy").lower()
DECISION_URL = os.environ.get("DECISION_SCORER_URL", "").rstrip("/")
DECISION_MODEL = os.environ.get("DECISION_MODEL", "nimble:9b-q4_K_M")
ENABLED = SCORER_MODE == "decision" and bool(DECISION_URL)

# Interest telt standaard niet mee: met het huidige (automatische) profiel
# voegde hij in de eval niets toe aan quality (0.6i+0.4q: 0.78 vs q: 0.82).
# Hij wordt wel gescoord en in het detail getoond.
INTEREST_WEIGHT = float(os.environ.get("DECISION_INTEREST_WEIGHT", "0"))
# Koud laden van nimble op de A2 duurde in de eval ~4 min.
REQUEST_TIMEOUT_SEC = float(os.environ.get("DECISION_TIMEOUT_SEC", "600"))
PULL_TIMEOUT_SEC = float(os.environ.get("DECISION_PULL_TIMEOUT_SEC", "1800"))
SUMMARY_CHARS = int(os.environ.get("DECISION_SUMMARY_CHARS", "6000"))
BATCH_SIZE = int(os.environ.get("DECISION_BATCH_SIZE", "50"))
INTERVAL_SEC = float(os.environ.get("DECISION_INTERVAL_SEC", "900"))
# Oude data is geen prioriteit: alleen recent samengevatte items.
MAX_AGE_DAYS = int(os.environ.get("DECISION_MAX_AGE_DAYS", "3"))
# Zoveel items achter elkaar mislukt = storing, batch afbreken.
MAX_CONSECUTIVE_FAILURES = 3
RETRY_DELAY_SEC = 2.0

PROFILE_KEY = "decision_profile"
PROFILE_MODEL = os.environ.get("DECISION_PROFILE_MODEL", "cloud-kimi")

QUALITY_CRITERIA = [
    "Spam, clickbait or advertisement",
    "Shallow, low signal",
    "Decent but unremarkable",
    "Well-argued with specific insights",
    "Exceptional depth or rare expertise",
]
INTEREST_CRITERIA = ["Not interesting", "Slightly interesting", "Interesting", "Must read"]


class DecisionUnavailable(Exception):
    """Model/container niet bereikbaar (verbinding, timeout, pull mislukt):
    de batch stopt meteen."""


class DecisionItemFailed(Exception):
    """5xx ook na de retry (bv. runner-crash): dit item overslaan; pas na
    MAX_CONSECUTIVE_FAILURES op rij telt het als storing."""


class DecisionItemError(Exception):
    """Dit item kan niet gescoord worden (4xx), de rest van de batch wel."""


# --- Vragen en antwoorden -------------------------------------------------

def build_questions(profile: Optional[str]) -> dict:
    questions = {
        "quality": {
            "type": "score",
            "instructions": "How high is the intellectual quality of this item: depth, "
                            "specificity and original analysis, regardless of topic?",
            "criteria": QUALITY_CRITERIA,
        },
        "clickbait": {
            "type": "noul",
            "instructions": "Is this item clickbait, an advertisement, or a product "
                            "announcement without substance?",
        },
    }
    if profile:
        questions["interest"] = {
            "type": "score",
            "instructions": "How interesting is this item to the reader described here? "
                            f"Reader profile: {profile}",
            "criteria": INTEREST_CRITERIA,
        }
    return questions


def _rubric(answer: dict) -> dict:
    """Score-antwoord -> 1-10 plus kansverdeling met labels i.p.v. indexen."""
    legend = answer.get("legend") or {}
    top = max(len(legend) - 1, 1)
    frac = min(max(float(answer["score"]) / top, 0.0), 1.0)
    return {
        "score10": int(round(1 + 9 * frac)),
        "fraction": round(frac, 4),
        "probabilities": {legend.get(k, k): round(float(v), 4)
                          for k, v in (answer.get("probabilities") or {}).items()},
        "confidence": answer.get("confidence"),
    }


def parse_answers(answers: dict, *, interest_weight: float = INTEREST_WEIGHT) -> tuple[int, dict]:
    """Systemone-antwoorden -> (quality_score 1-10, detail)."""
    quality = _rubric(answers["quality"])
    interest = _rubric(answers["interest"]) if "interest" in answers else None
    frac = quality["fraction"]
    if interest is not None and interest_weight > 0:
        frac = (1 - interest_weight) * frac + interest_weight * interest["fraction"]
    detail = {
        "quality": quality,
        "interest": interest,
        "clickbait": round(float(answers["clickbait"]["noul"]), 4) if "clickbait" in answers else None,
        "interest_weight": interest_weight,
    }
    return int(round(1 + 9 * frac)), detail


# --- HTTP naar stroom-decision -------------------------------------------

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SEC)
    return _client


async def _pull_model(client: httpx.AsyncClient) -> None:
    print(f"[decision] model {DECISION_MODEL} ontbreekt — pull", flush=True)
    try:
        r = await client.post(f"{DECISION_URL}/api/pull",
                              json={"model": DECISION_MODEL, "stream": False},
                              timeout=PULL_TIMEOUT_SEC)
    except httpx.HTTPError as e:
        raise DecisionUnavailable(f"pull faalde: {e!r}") from e
    if r.status_code != 200:
        raise DecisionUnavailable(f"pull {r.status_code}: {r.text[:200]}")


async def score_item(client: httpx.AsyncClient, title: Optional[str], summary: str,
                     profile: Optional[str]) -> tuple[int, dict]:
    payload = {
        "model": DECISION_MODEL,
        "state": {"title": title or "", "summary": summary[:SUMMARY_CHARS]},
        "questions": build_questions(profile),
    }
    pulled = False
    retried = False
    while True:
        t0 = time.monotonic()
        try:
            r = await client.post(f"{DECISION_URL}/v1/systemone", json=payload)
        except httpx.HTTPError as e:
            raise DecisionUnavailable(f"{type(e).__name__}: {e}") from e
        if r.status_code == 200:
            score, detail = parse_answers(r.json()["answers"])
            detail["latency_sec"] = round(time.monotonic() - t0, 2)
            return score, detail
        if r.status_code == 404 and "not found" in r.text and not pulled:
            await _pull_model(client)
            pulled = True
            continue
        if r.status_code >= 500 and not retried:
            # Runner-crash ("EOF") kwam in de eval bij ~3% van de calls voor;
            # één retry, daarna telt hij als mislukt item.
            retried = True
            await asyncio.sleep(RETRY_DELAY_SEC)
            continue
        if r.status_code >= 500:
            raise DecisionItemFailed(f"{r.status_code}: {r.text[:200]}")
        raise DecisionItemError(f"{r.status_code}: {r.text[:300]}")


# --- Interesseprofiel (app_settings) ------------------------------------

def profile_version(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


async def load_profile(session) -> Optional[dict]:
    r = await session.exec(sa_text(
        "SELECT value FROM app_settings WHERE key = :k").bindparams(k=PROFILE_KEY))
    row = r.first()
    if not row:
        return None
    value = row[0]
    return json.loads(value) if isinstance(value, str) else value


async def save_profile(session, text: str, source: str, n_lessons: Optional[int] = None) -> dict:
    value = {"text": text.strip(), "source": source, "n_lessons": n_lessons,
             "version": profile_version(text.strip()),
             "updated_at": datetime.now(timezone.utc).isoformat()}
    await session.exec(sa_text("""
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (:k, CAST(:v AS jsonb), now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
    """).bindparams(k=PROFILE_KEY, v=json.dumps(value)))
    await session.commit()
    return value


async def build_profile(session, llm) -> dict:
    """Genereer het profiel uit alle gelikete lessen (en hun item-titels)."""
    from pipeline.digest_model_map import resolve_model
    r = await session.exec(sa_text("""
        SELECT l.title, i.title FROM lessons l JOIN items i ON i.id = l.item_id
        WHERE l.rating = 1 ORDER BY l.rated_at DESC NULLS LAST LIMIT 300
    """))
    rows = r.all()
    if not rows:
        raise ValueError("geen gelikete lessen om een profiel uit te maken")
    item_titles = list(dict.fromkeys(t for _, t in rows if t))[:120]
    lines = [f"- {t}" for t in item_titles] + [f"- {lt}" for lt, _ in rows if lt][:200]
    prompt = (
        "Below are titles of articles, podcasts and key lessons that one reader found valuable "
        "(mostly Dutch). Write a reader interest profile in English of at most 150 words: "
        "the topics, angles and kinds of content this reader values, and what they are likely "
        "NOT interested in. Plain prose, no lists, no preamble.\n\n" + "\n".join(lines)
    )
    text = (await llm.call_llm(model=resolve_model(PROFILE_MODEL),
                               messages=[{"role": "user", "content": prompt}],
                               temperature=0.2, timeout=180)).strip()
    if not text:
        raise ValueError("leeg profiel van het LLM")
    return await save_profile(session, text, source="auto", n_lessons=len(rows))


# --- ntfy -----------------------------------------------------------------

async def notify(title: str, body: str) -> None:
    topic = os.environ.get("NTFY_TOPIC", "")
    if not topic:
        print(f"[decision] geen NTFY_TOPIC — melding niet verstuurd: {title}", flush=True)
        return
    endpoint = os.environ.get("NTFY_ENDPOINT", "https://ntfy.sh").rstrip("/")
    headers = {"Title": title, "Priority": "3", "Tags": "hourglass_flowing_sand"}
    if os.environ.get("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['NTFY_TOKEN']}"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(f"{endpoint}/{topic}", content=body.encode(), headers=headers)
    except Exception as e:
        print(f"[decision] ntfy faalde: {e!r}", flush=True)


# --- Batch ----------------------------------------------------------------

_lock = asyncio.Lock()
state: dict = {"last_run_at": None, "last_result": None, "outage_since": None,
               "outage_notified": False}


async def _select_candidates(session) -> list:
    r = await session.exec(sa_text(f"""
        SELECT id::text, title, summary FROM items
        WHERE quality_score IS NULL
          AND coalesce(summary, '') <> ''
          AND {auto_score_guard()}
          AND (quality_score_detail IS NULL OR quality_score_detail->>'error' IS NULL)
          AND summary_generated_at > now() - make_interval(days => :days)
        ORDER BY summary_generated_at DESC
        LIMIT :n
    """).bindparams(days=MAX_AGE_DAYS, n=BATCH_SIZE))
    return r.all()


async def _write_score(session, item_id: str, summary: str, score: int, detail: dict) -> bool:
    """Atomair: alleen als het item nog ongescoord is, de score van het systeem
    is en de summary dezelfde als bij selectie."""
    res = await session.exec(sa_text(f"""
        UPDATE items SET quality_score = :q, quality_score_reason = 'auto',
               quality_score_updated_at = now(), quality_score_detail = CAST(:d AS jsonb)
        WHERE id = CAST(:i AS uuid) AND quality_score IS NULL AND summary = :s
          AND {auto_score_guard()}
    """).bindparams(q=score, d=json.dumps(detail), i=item_id, s=summary))
    await session.commit()
    return res.rowcount > 0


async def _mark_item_error(session, item_id: str, error: str) -> None:
    await session.exec(sa_text("""
        UPDATE items SET quality_score_detail = CAST(:d AS jsonb)
        WHERE id = CAST(:i AS uuid) AND quality_score IS NULL
    """).bindparams(d=json.dumps({"error": error[:300], "model": DECISION_MODEL}), i=item_id))
    await session.commit()


async def _ensure_profile(session_maker, llm) -> Optional[dict]:
    async with session_maker() as session:
        profile = await load_profile(session)
        if profile and profile.get("text"):
            return profile
        try:
            return await build_profile(session, llm)
        except Exception as e:
            # Zonder profiel scoren we alleen quality/clickbait; volgende ronde opnieuw.
            print(f"[decision] profiel maken faalde: {e!r}", flush=True)
            return None


async def run_batch(session_maker, llm, client: Optional[httpx.AsyncClient] = None) -> dict:
    if _lock.locked():
        return {"skipped": "already_running"}
    async with _lock:
        result = await _run_batch(session_maker, llm, client or _get_client())
        state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        state["last_result"] = result
        return result


async def _run_batch(session_maker, llm, client) -> dict:
    async with session_maker() as session:
        rows = await _select_candidates(session)
    result = {"selected": len(rows), "scored": 0, "skipped": 0, "item_errors": 0, "error": None}
    if not rows:
        return result

    profile = await _ensure_profile(session_maker, llm)
    profile_text = profile.get("text") if profile else None
    failures = 0
    try:
        for item_id, title, summary in rows:
            try:
                score, detail = await score_item(client, title, summary, profile_text)
            except DecisionItemError as e:
                result["item_errors"] += 1
                async with session_maker() as session:
                    await _mark_item_error(session, item_id, str(e))
                continue
            except DecisionItemFailed as e:
                failures += 1
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    raise DecisionUnavailable(f"{failures} items op rij mislukt: {e}") from e
                result["skipped"] += 1
                continue
            failures = 0
            detail.update(model=DECISION_MODEL,
                          profile_version=profile.get("version") if profile else None,
                          scored_at=datetime.now(timezone.utc).isoformat())
            async with session_maker() as session:
                if await _write_score(session, item_id, summary, score, detail):
                    result["scored"] += 1
                else:
                    result["skipped"] += 1
    except DecisionUnavailable as e:
        result["error"] = str(e)[:300]
        print(f"[decision] storing: {e}", flush=True)
        if state["outage_since"] is None:
            state["outage_since"] = datetime.now(timezone.utc).isoformat()
        if not state["outage_notified"]:
            await notify("Stroom: classificatie lukte even niet",
                         "Classificatie lukte even niet, we proberen het later nog een keer.\n"
                         f"({DECISION_MODEL} via {DECISION_URL}: {str(e)[:200]})")
            state["outage_notified"] = True
        return result

    if result["scored"]:
        state["outage_since"] = None
        state["outage_notified"] = False
    print(f"[decision] batch: {result}", flush=True)
    return result
