"""Constanten en kleine pure helpers voor tips-mining uit podcasttranscripten."""

import json
import re
import unicodedata
from difflib import SequenceMatcher

from services.llm_service import parse_llm_json

WIN = 6000
STEP = 5200
WEIGHT = {"strong": 3, "medium": 2, "weak": 1}
CATEGORIES = ("book", "software", "film", "series", "documentary", "game", "podcast", "music",
              "youtube", "newsletter", "comic", "theatre", "other")
ALIAS = {"app": "software", "tool": "software", "website": "software", "tv_show": "series",
         "poetry": "book", "poem": "book"}
NUM = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
       "eight": "8", "nine": "9", "ten": "10", "een": "1", "twee": "2", "drie": "3", "vier": "4",
       "vijf": "5", "zeven": "7"}
GENERIC_WHO = {"", "host", "gast", "guest", "fan", "self_promo", "luisteraars", "listeners", "beller",
               "caller", "de host", "de gast", "spreker", "speaker", "presentator", "presenter",
               "interviewer", "hosts", "co-host", "luisteraar", "listener", "null", "none",
               "onbekend", "unknown"}
BAD_TITLE_PREFIXES = ("onbekend", "unknown", "untitled", "null", "none")


def windows(text: str | None) -> list[tuple[int, str]]:
    """Knip de tekst in overlappende vensters van WIN tekens."""
    if not text:
        return []
    out: list[tuple[int, str]] = []
    offset = 0
    while True:
        out.append((offset, text[offset:offset + WIN]))
        if offset + WIN >= len(text):
            return out
        offset += STEP


def norm(title: str | None) -> str:
    """Normaliseer een titel naar een vergelijkbare ASCII-vorm."""
    if not title:
        return ""
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    t = t.lower().strip()
    t = re.sub(r"^(the|de|het|een|a|an)\s+", "", t)
    t = re.split(r"\s*[:(\-–—]\s+", t)[0]
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def title_key(title: str | None) -> str:
    """Maak een canonieke sleutel voor een titel."""
    return " ".join(NUM.get(w, w) for w in norm(title).split())


def same_work(a: str | None, b: str | None) -> bool:
    """Bepaal of twee titels naar hetzelfde werk verwijzen."""
    x, y = norm(a), norm(b)
    if not x or not y:
        return False
    return x in y or y in x or SequenceMatcher(None, x, y).ratio() >= 0.6


def _s(value: object, limit: int) -> str | None:
    """Strip een stringwaarde en kap die af op limit tekens."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:limit]


def clean_tips(data: object) -> list[dict]:
    """Filter en normaliseer de tips uit een al geparseerd LLM-antwoord."""
    if not isinstance(data, dict):
        return []
    raw_tips = data.get("tips")
    if not isinstance(raw_tips, list):
        return []
    tips: list[dict] = []
    for raw in raw_tips:
        if not isinstance(raw, dict):
            continue
        raw_title = raw.get("title")
        if not isinstance(raw_title, str) or not raw_title.strip():
            continue
        category = str(raw.get("category") or "").lower()
        strength = str(raw.get("strength") or "").lower()
        if category == "self_promo" or strength == "self_promo":
            continue
        category = ALIAS.get(category, category)
        if category not in CATEGORIES:
            category = "other"
        if strength not in WEIGHT:
            strength = "weak"
        title = _s(raw_title, 300)
        key = title_key(title)
        if len(key) < 2 or key.startswith(BAD_TITLE_PREFIXES):
            continue
        tips.append(
            {
                "category": category,
                "title": title,
                "creator": _s(raw.get("creator"), 300),
                "recommended_by": _s(raw.get("recommended_by"), 300),
                "strength": strength,
                "why": _s(raw.get("why"), 500),
                "quote": _s(raw.get("quote"), 500),
            }
        )
    return tips


def parse_tips(raw: str) -> list[dict]:
    """Parse een ruw LLM-antwoord tot een lijst schone tips."""
    try:
        return clean_tips(parse_llm_json(raw))
    except json.JSONDecodeError:
        return []


def parse_verify(raw: str, batch: list[dict]) -> dict[str, dict]:
    """Verwerk een verificatie-antwoord tot keep/fix-beslissingen per title_key."""
    try:
        data = parse_llm_json(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict] = {}
    vid_to_key: dict[int, str] = {}
    for item in batch:
        key = item.get("title_key")
        if not key:
            continue
        result[key] = {
            "keep": True,
            "title": item.get("title"),
            "creator": item.get("creator"),
            "category": item.get("category"),
            "confidence": "high",
        }
        try:
            vid_to_key[int(item["vid"])] = key
        except (KeyError, TypeError, ValueError):
            continue
    drop = data.get("drop")
    if isinstance(drop, list):
        for vid in drop:
            try:
                vid = int(vid)
            except (TypeError, ValueError):
                continue
            key = vid_to_key.get(vid)
            if key:
                result[key]["keep"] = False
    fixes = data.get("fix")
    if isinstance(fixes, list):
        for fix in fixes:
            if not isinstance(fix, dict):
                continue
            try:
                vid = int(fix.get("id"))
            except (TypeError, ValueError):
                continue
            key = vid_to_key.get(vid)
            if not key:
                continue
            for field in ("title", "creator", "category", "confidence"):
                value = fix.get(field)
                if isinstance(value, str) and value.strip():
                    result[key][field] = value.strip()
    return result


def who_label(recommended_by: str | None, source: str) -> str:
    """Maak een leesbaar label voor de aanrader, met de podcast als fallback."""
    by = (recommended_by or "").strip()
    by = re.sub(r"^(gast|host|guest|fan|spreker|de gast|de host)\s*[:(]\s*(.*?)\)?$", r"\2", by,
                flags=re.I).strip()
    if by.lower() in GENERIC_WHO:
        return source
    if source.lower() in by.lower():
        return by
    return f"{by} ({source})"
