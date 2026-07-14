"""Kernlessen: parsen uit summaries en LLM-distill uit artikel-bodies."""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy import text as sa_text

from core.config import settings

log = logging.getLogger("stroom.lessons")

# Minimaal aantal chars in de geëxtraheerde body voordat lesson-distill draait.
# Beschermt tegen oppervlakkige/verzonnen lessen op een RSS-teaser i.p.v. full-text.
ARTICLE_MIN_BODY_FOR_LESSONS = settings.ARTICLE_MIN_BODY_FOR_LESSONS

_LESSONS_HEADER_RE = re.compile(
    r"^##\s+(?:Kernlessen|Kernpunten|Key\s+lessons|Key\s+points|Key\s+takeaways)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_LESSON_ITEM_RE = re.compile(
    r"^\s*\d+\.\s+\*\*(?P<title>.+?)\*\*\s*[:.]?\s*(?P<body>.+?)\s*$",
    re.MULTILINE,
)


def parse_lessons(summary_text: str) -> list[tuple[str, str]]:
    """Extract (title, body) tuples from the ## Kernlessen section."""
    if not summary_text:
        return []
    m = _LESSONS_HEADER_RE.search(summary_text)
    if not m:
        return []
    section = summary_text[m.end():]
    end = re.search(r"^(##\s|---\s*$)", section, re.MULTILINE)
    if end:
        section = section[: end.start()]
    out: list[tuple[str, str]] = []
    for item in _LESSON_ITEM_RE.finditer(section):
        title = item.group("title").strip().rstrip(":").strip()
        body = item.group("body").strip()
        if title and body:
            out.append((title, body))
    return out


async def replace_lessons(session, item_id: str, summary_text: str) -> None:
    """Idempotent: delete existing lessons, then insert parsed ones. Preserves no rating."""
    lessons = parse_lessons(summary_text)
    await session.exec(sa_text(
        "DELETE FROM lessons WHERE item_id = CAST(:i AS uuid)"
    ).bindparams(i=item_id))
    for idx, (title, body) in enumerate(lessons, start=1):
        await session.exec(sa_text(
            "INSERT INTO lessons (item_id, idx, title, body) "
            "VALUES (CAST(:i AS uuid), :idx, :t, :b)"
        ).bindparams(i=item_id, idx=idx, t=title, b=body))


async def distill_lessons_for_item(item_id: str, summary: str, article_body: str,
                                   llm_service, async_session_maker) -> int:
    """Genereer kernlessen via LLM en sla ze op. Returnt aantal inserted.

    Idempotent: als het item al lessen heeft (bv. door een eerdere run) wordt
    niets gedaan — voorkomt duplicaten én behoudt eerder gegeven ratings.
    """
    body_text = article_body.strip()[:18000]
    if not body_text:
        return 0
    async with async_session_maker() as bg:
        existing = (await bg.exec(sa_text(
            "SELECT count(*) FROM lessons WHERE item_id = CAST(:i AS uuid)"
        ).bindparams(i=item_id))).first()
        if existing and existing[0]:
            return 0
    system = (
        "Je destilleert kernlessen uit een bron (artikel). "
        "Lever concrete, bruikbare lessen die de kern van het artikel vangen.\n\n"
        "Output: strikt JSON, vorm: {\"lessons\": [{\"title\": \"…\", \"body\": \"…\"}]}\n"
        "- title: korte kop (4-8 woorden)\n"
        "- body: 1-3 zinnen, concreet en bruikbaar\n"
        "Maximaal 5 lessen. Liever 0 dan oppervlakkig."
    )
    raw = await llm_service.call_llm(
        "stroom-bulk",
        [{"role": "system", "content": system},
         {"role": "user", "content": f"Samenvatting: {summary}\n\nArtikel tekst:\n{body_text}"}],
        temperature=0.4, response_format="json_object",
    )
    try:
        data = json.loads(raw)
        new_lessons = data.get("lessons", []) or []
    except json.JSONDecodeError:
        return 0

    inserted = 0
    async with async_session_maker() as bg:
        for idx, entry in enumerate(new_lessons, start=1):
            t = (entry.get("title") or "").strip()
            b = (entry.get("body") or "").strip()
            if not t or not b:
                continue
            await bg.exec(sa_text(
                "INSERT INTO lessons (item_id, idx, title, body) "
                "VALUES (CAST(:i AS uuid), :idx, :t, :b)"
            ).bindparams(i=item_id, idx=idx, t=t, b=b))
            inserted += 1
        if inserted:
            await bg.commit()
    return inserted
