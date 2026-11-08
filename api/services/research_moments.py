"""Momenten in een aflevering terugvinden bij de bevindingen van een dossier.

Een bevinding uit een podcast of video wil je terugluisteren. Het getimede
transcript (`items.transcript_segments`, korte stukjes met `start`/`end` in
seconden) zegt waar iets gezegd is; het lastige is welk stukje bij welke
bevinding hoort.

1. Exact: staat het citaat letterlijk in het transcript (zes woorden op een
   rij), dan is dat het moment. Gratis en precies.
2. Model: de meeste citaten komen uit de samenvatting en zijn parafrases
   (gemeten op het software-inkoopdossier: 94 van 370 citaten letterlijk
   terug te vinden, de rest uit de samenvatting). Voor die bevindingen leest
   een goedkoop model het transcript in blokken van ~30 seconden en wijst per
   bevinding het blok aan. Dat moment is bij benadering ("≈").

Het resultaat wordt per run en bron bewaard (`research_runs.moments`), zodat
het model per bron maar één keer meekijkt.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from services import research_service as rs
from services.research_prompts import MOMENT_SYSTEM

MOMENT_MODELS = rs._models("RESEARCH_MOMENT_MODELS", "cloud-gemma,cloud-gpt-120b")
BLOCK_SECS = 30.0
MAX_TRANSCRIPT_CHARS = 180_000   # ~45k tokens; langere afleveringen worden afgekapt
EXACT_WINDOW = 6

_WORD = re.compile(r"[0-9a-zà-ÿ]+", re.I)


def _words(text: Optional[str]) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def _segments(segments: Any) -> list[dict]:
    out = []
    for s in segments or []:
        if isinstance(s, dict) and isinstance(s.get("start"), (int, float)):
            out.append(s)
    return out


def locate_quotes(segments: Any, quotes: list[str], window: int = EXACT_WINDOW) -> list[Optional[float]]:
    """Begintijd (s) van het segment waar het citaat letterlijk begint, per
    citaat; None als het niet letterlijk in het transcript staat. Een citaat
    telt als gevonden zodra `window` woorden op een rij overeenkomen."""
    stream: list[str] = []
    starts: list[float] = []
    for seg in _segments(segments):
        for w in _words(seg.get("text")):
            stream.append(w)
            starts.append(float(seg["start"]))
    if not stream:
        return [None] * len(quotes)
    index: dict[tuple, int] = {}
    for i in range(len(stream) - window + 1):
        index.setdefault(tuple(stream[i:i + window]), i)
    out: list[Optional[float]] = []
    for q in quotes:
        qw = _words(q)
        hit: Optional[float] = None
        if len(qw) >= window:
            for k in range(len(qw) - window + 1):
                i = index.get(tuple(qw[k:k + window]))
                if i is not None:
                    hit = starts[i]
                    break
        elif len(qw) >= 3:
            n = len(qw)
            for i in range(len(stream) - n + 1):
                if stream[i:i + n] == qw:
                    hit = starts[i]
                    break
        out.append(hit)
    return out


def fmt_ts(secs: float) -> str:
    s = int(secs)
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_ts(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value >= 0 else None
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"\s*\[?(?:(\d+):)?(\d{1,2}):(\d{2})\]?\s*", value)
    if not m:
        return None
    h, mi, s = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    return float(h * 3600 + mi * 60 + s)


def transcript_blocks(segments: Any, block_secs: float = BLOCK_SECS,
                      max_chars: int = MAX_TRANSCRIPT_CHARS) -> tuple[str, list[float]]:
    """Transcript als regels '[12:30] tekst', één per blok van ~block_secs.
    Geeft ook de begintijden van de blokken (om antwoorden op te laten
    passen). Segmenten overlappen soms in tijd; de tekst volgt de volgorde."""
    lines: list[str] = []
    block_starts: list[float] = []
    cur_start: Optional[float] = None
    cur: list[str] = []
    total = 0

    def flush() -> bool:
        nonlocal total
        if cur_start is None or not cur:
            return True
        line = f"[{fmt_ts(cur_start)}] {' '.join(cur)}"
        if total + len(line) > max_chars:
            return False
        lines.append(line)
        block_starts.append(cur_start)
        total += len(line) + 1
        return True

    for seg in _segments(segments):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        st = float(seg["start"])
        if cur_start is None:
            cur_start = st
        elif st - cur_start >= block_secs:
            if not flush():
                break
            cur_start, cur = st, []
        cur.append(text)
    else:
        flush()
    return "\n".join(lines), block_starts


def snap(t: float, block_starts: list[float]) -> Optional[float]:
    """Laat een modelantwoord landen op het begin van het blok waar het in
    valt; tijden buiten het transcript tellen niet."""
    if not block_starts or t < 0 or t > block_starts[-1] + BLOCK_SECS * 2:
        return None
    best = block_starts[0]
    for b in block_starts:
        if b <= t + 0.5:
            best = b
        else:
            break
    return best


def parse_moments(obj: Any, n: int, block_starts: list[float]) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * n
    items = obj.get("moments") if isinstance(obj, dict) else None
    for m in items or []:
        if not isinstance(m, dict):
            continue
        try:
            i = int(m.get("i")) - 1
        except (TypeError, ValueError):
            continue
        t = parse_ts(m.get("t"))
        if 0 <= i < n and t is not None:
            out[i] = snap(t, block_starts)
    return out


def _finding_line(k: int, f: dict) -> str:
    bits = [f"{k}. {f.get('claim', '').strip()}"]
    if f.get("quote"):
        bits.append(f'   citaat: "{f["quote"].strip()}"')
    if f.get("speaker"):
        bits.append(f"   spreker: {f['speaker']}")
    return "\n".join(bits)


async def locate_moments(llm, segments: Any, findings: list[dict], *,
                         models: Optional[list[str]] = None) -> tuple[list[Optional[dict]], Optional[str]]:
    """Per bevinding {"t": seconden, "exact": bool} of None. Tweede waarde:
    het gebruikte model (None als het niet nodig was of niets opleverde)."""
    quotes = [f.get("quote") or "" for f in findings]
    exact = locate_quotes(segments, quotes)
    out: list[Optional[dict]] = [{"t": t, "exact": True} if t is not None else None for t in exact]
    todo = [k for k, m in enumerate(out) if m is None]
    if not todo or not _segments(segments):
        return out, None
    text, block_starts = transcript_blocks(segments)
    if not block_starts:
        return out, None
    numbered = "\n".join(_finding_line(j, findings[k]) for j, k in enumerate(todo, 1))
    user = f"=== TRANSCRIPT ===\n{text}\n\n=== BEVINDINGEN ===\n{numbered}"
    try:
        obj, model = await rs.llm_call(llm, models or MOMENT_MODELS, MOMENT_SYSTEM, user,
                                       as_json=True, max_tokens=6000, timeout=240,
                                       usage=None, temperature=0.0, attempts=2)
    except RuntimeError as e:
        print(f"[research] momenten zoeken faalde: {e}", flush=True)
        return out, None
    for j, t in enumerate(parse_moments(obj, len(todo), block_starts)):
        if t is not None:
            out[todo[j]] = {"t": t, "exact": False}
    return out, model
