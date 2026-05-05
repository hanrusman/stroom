"""Topic-digest pipeline. Vandaaruit groeit ook de weekly/monthly TTS-podcast."""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import text as sa_text


DIGEST_MAX_ITEMS = 40
DIGEST_PER_ITEM_CHARS = 600
DIGEST_GENERATION_STALE_MIN = 10  # bg-task is dood als hij na 10 min nog 'is_generating' is

DIGEST_MODEL_MAP: dict[str, str] = {
    "qwen": "stroom-bulk",
    "sonnet": "stroom-sonnet",
    "opus": "stroom-deep",
}


def strip_html(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_digest_prompt(topic_name: str, window_hours: int, corpus: str) -> tuple[str, str]:
    window_label = "weeksamenvatting" if window_hours >= 168 else "dagsamenvatting"
    window_short = f"{window_hours // 24} dagen" if window_hours >= 48 else f"{window_hours}u"
    system_prompt = (
        f"Je bent een redacteur die een persoonlijke {window_label} schrijft over een specifiek thema. "
        f"De gebruiker volgt het thema '{topic_name}' en heeft geen tijd om alles te lezen. "
        "Schrijf een markdown-digest in het Nederlands met:\n"
        f"1. Een korte intro (2 zinnen) over wat er in de laatste {window_short} opviel.\n"
        "2. Per cluster (groepeer waar logisch) een H3-kop, dan 2-4 zinnen die de gemeenschappelijke draad uitleggen. "
        "Verwijs naar bronnen met markdown-links: [Bronnaam](URL).\n"
        "3. Een '## Verder lezen' lijst (markdown bullet list) van max 5 items die individueel de moeite waard zijn — "
        "elke regel als `- [Titel](URL) — korte reden waarom (1 zin).`\n"
        "Wees scherp, geen marketingtaal. Als bronnen elkaar tegenspreken, benoem dat. "
        "Gebruik UITSLUITEND de URLs die in de bronlijst staan; verzin geen URLs."
    )
    user_prompt = f"Items van laatste {window_short}:\n\n{corpus}"
    return system_prompt, user_prompt


def build_corpus(rows) -> list[str]:
    """Bouw markdown-blocks per item. Voorkeur: summary > stripped description."""
    blocks: list[str] = []
    for title, fmt, sname, summary, desc, pub, url in rows:
        body = (summary or "").strip() or strip_html(desc)
        if not body:
            continue
        body = body[:DIGEST_PER_ITEM_CHARS]
        when = str(pub)[:16] if pub else ""
        url_line = f"URL: {url}\n" if url else ""
        blocks.append(f"### [{fmt}] {title}\n_{sname} · {when}_\n{url_line}\n{body}")
    return blocks


async def run_digest_generation(topic_id: str, topic_name: str, slug: str,
                                model: str, window_hours: int,
                                async_session_maker, llm_service):
    """Background-task: leest items, roept LLM aan, schrijft naar topic_digests."""
    llm_alias = DIGEST_MODEL_MAP[model]
    try:
        async with async_session_maker() as bg:
            rows = (await bg.exec(sa_text(
                f"""
                SELECT i.title, i.format::text, s.name, i.summary, i.description, i.published_at, i.media_url
                FROM items i
                JOIN item_topics it ON it.item_id = i.id
                JOIN sources s ON s.id = i.source_id
                WHERE it.topic_id = CAST(:tid AS uuid)
                  AND i.published_at >= now() - INTERVAL '{window_hours} hours'
                  AND s.active = true
                  AND i.status <> 'archived'::item_status
                ORDER BY i.published_at DESC
                LIMIT {DIGEST_MAX_ITEMS}
                """
            ).bindparams(tid=topic_id))).all()

            if not rows:
                await bg.exec(sa_text(
                    "UPDATE topic_digests SET is_generating=false, error=:e "
                    "WHERE topic_id=CAST(:tid AS uuid) AND window_hours=:w"
                ).bindparams(e=f"Geen items van laatste {window_hours}u", tid=topic_id, w=window_hours))
                await bg.commit()
                return

            blocks = build_corpus(rows)
            if not blocks:
                await bg.exec(sa_text(
                    "UPDATE topic_digests SET is_generating=false, error='Items hebben geen tekst' "
                    "WHERE topic_id=CAST(:tid AS uuid) AND window_hours=:w"
                ).bindparams(tid=topic_id, w=window_hours))
                await bg.commit()
                return

            corpus = "\n\n---\n\n".join(blocks)
            system_prompt, user_prompt = build_digest_prompt(topic_name, window_hours, corpus)
            markdown = await llm_service.call_llm(llm_alias, [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ], temperature=0.4, timeout=300.0)

            await bg.exec(sa_text(
                """
                UPDATE topic_digests SET
                  markdown = :m, item_count = :n, model = :ml,
                  generated_at = now(), is_generating = false, error = NULL
                WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w
                """
            ).bindparams(m=markdown.strip(), n=len(blocks), ml=llm_alias,
                         w=window_hours, tid=topic_id))
            await bg.commit()
            print(f"[digest bg] {slug} {window_hours}u klaar — {len(blocks)} items, {llm_alias}",
                  flush=True)
    except Exception as exc:
        try:
            async with async_session_maker() as bg:
                await bg.exec(sa_text(
                    "UPDATE topic_digests SET is_generating=false, error=:e "
                    "WHERE topic_id=CAST(:tid AS uuid) AND window_hours=:w"
                ).bindparams(e=str(exc)[:500], tid=topic_id, w=window_hours))
                await bg.commit()
        except Exception:
            pass
        print(f"[digest bg] {slug} {window_hours}u faalde: {exc}", flush=True)
