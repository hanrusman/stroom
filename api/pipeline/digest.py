"""Topic-digest pipeline. Vandaaruit groeit ook de weekly/monthly TTS-podcast."""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from sqlalchemy import text as sa_text


DIGEST_MAX_ITEMS = 40
DIGEST_PER_ITEM_CHARS = 600
WEEKLY_SOURCE_DAYS = 7  # weekly componeert uit de laatste N dag-digests
DIGEST_GENERATION_STALE_MIN = 30  # bg-task is dood als hij na N min nog 'is_generating' is
DIGEST_LLM_TIMEOUT = 1200.0  # 20 min per digest — grote weekly + zware topic kan zo lang duren

# Module-level semaphore: serialiseer digest-generaties zodat we lokale qwen niet
# met 12 tegelijk overspoelen. Eén tegelijk = elke krijgt z'n eigen tijd, geen race.
_DIGEST_SEM = asyncio.Semaphore(1)

# Mapping van Stroom-namen naar LiteLLM-aliases. Single source of truth in
# pipeline.digest_model_map; we exposeren 'm hier nog onder de oude naam voor
# bestaande callers (`DIGEST_MODEL_MAP[model]`).
from pipeline.digest_model_map import DIGEST_MODEL_TO_LITELLM as DIGEST_MODEL_MAP  # noqa: E402


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


def build_weekly_corpus_from_dailies(daily_rows) -> list[str]:
    """Bouw het weekly-corpus uit de laatste dag-digests (RAPTOR-laag dag→week).

    daily_rows: (generated_at, markdown) van de recentste dag-digests, nieuw→oud.
    We presenteren ze oud→nieuw zodat het weekbeeld chronologisch leest."""
    blocks: list[str] = []
    for generated_at, markdown in reversed(list(daily_rows)):
        body = (markdown or "").strip()
        if not body:
            continue
        day = str(generated_at)[:10] if generated_at else ""
        blocks.append(f"### Dagsamenvatting {day}\n\n{body}")
    return blocks


def build_weekly_digest_prompt(topic_name: str, corpus: str) -> tuple[str, str]:
    """Citatie-gebonden, lage-temperatuur prompt voor de synthese-laag.

    De anti-drift-hefboom is hier de citatie-binding: het model mag alleen
    samenvatten wat in de dag-samenvattingen staat en de bestaande bronlinks
    overnemen — geen nieuwe feiten of URLs verzinnen."""
    system_prompt = (
        f"Je bent een redacteur die een persoonlijke weeksamenvatting schrijft over het thema "
        f"'{topic_name}'. Je krijgt de losse DAG-samenvattingen van de afgelopen dagen en vat ze "
        "samen tot één weekbeeld in het Nederlands.\n"
        "REGELS (belangrijk tegen parafrase-drift):\n"
        "- Baseer je UITSLUITEND op de onderstaande dag-samenvattingen. Verzin geen feiten, "
        "cijfers of gebeurtenissen die er niet in staan.\n"
        "- Neem de markdown-links/bronnen exact over zoals ze in de dag-samenvattingen staan; "
        "verzin NOOIT nieuwe URLs.\n"
        "- Elke claim moet herleidbaar zijn tot een dag-samenvatting hieronder.\n\n"
        "Structuur:\n"
        "1. Korte intro (2 zinnen): de grote lijn van de week.\n"
        "2. Per thema-cluster een H3-kop, dan 2-4 zinnen die de rode draad over de dagen heen "
        "uitleggen, met de bronlinks die er al waren: [Bronnaam](URL).\n"
        "3. Een '## Verder lezen' lijst (max 5) met items uit de dag-samenvattingen — "
        "elke regel als `- [Titel](URL) — korte reden waarom (1 zin).`\n"
        "Wees scherp, geen marketingtaal. Als dagen elkaar tegenspreken, benoem de ontwikkeling."
    )
    user_prompt = f"Dag-samenvattingen van de afgelopen week (oud → nieuw):\n\n{corpus}"
    return system_prompt, user_prompt


async def run_digest_generation(topic_id: str, topic_name: str, slug: str,
                                model: str, window_hours: int,
                                async_session_maker, llm_service):
    """Background-task: leest items, roept LLM aan, schrijft naar topic_digests.
    Geserialiseerd via module-level semaphore zodat parallelle calls niet timen out
    op een lokale single-GPU LLM."""
    async with _DIGEST_SEM:
        await _run_digest_generation_inner(topic_id, topic_name, slug, model, window_hours,
                                           async_session_maker, llm_service)


async def _run_digest_generation_inner(topic_id: str, topic_name: str, slug: str,
                                       model: str, window_hours: int,
                                       async_session_maker, llm_service):
    """Inner worker: dit draait binnen de semaphore, dus één tegelijk."""
    llm_alias = DIGEST_MODEL_MAP[model]
    try:
        async with async_session_maker() as bg:
            # Zet generation_started_at NU pas — we zitten binnen de semaphore,
            # dus dit is het moment dat de generatie écht begint.
            # queued_at blijft staan zodat we later kunnen zien hoe lang de wachtrij duurde.
            await bg.exec(sa_text(
                "UPDATE topic_digests SET generation_started_at=now() "
                "WHERE topic_id=CAST(:tid AS uuid) AND window_hours=:w"
            ).bindparams(tid=topic_id, w=window_hours))
            await bg.commit()

            # Kies corpus + prompt. Weekly (>=168u) componeert uit de laatste
            # WEEKLY_SOURCE_DAYS dag-digests (RAPTOR-laag dag→week): klein corpus,
            # geen 19u-hang die 7 dagen ruwe items op de lokale GPU gaf.
            # system_prompt blijft None tot we een bruikbaar corpus hebben; is het
            # daarna nog None, dan valt het door naar het ruwe-items-pad (daily, of
            # weekly zonder bruikbare dag-history).
            system_prompt = user_prompt = None
            base_temp = 0.4

            if window_hours >= 168:
                daily_rows = (await bg.exec(sa_text(
                    """
                    SELECT generated_at, markdown
                    FROM topic_digest_runs
                    WHERE topic_id = CAST(:tid AS uuid) AND window_hours = 24
                      AND markdown IS NOT NULL AND markdown <> ''
                    ORDER BY generated_at DESC
                    LIMIT :lim
                    """
                ).bindparams(tid=topic_id, lim=WEEKLY_SOURCE_DAYS))).all()
                blocks = build_weekly_corpus_from_dailies(daily_rows) if daily_rows else []
                if blocks:
                    base_temp = 0.3
                    corpus = "\n\n---\n\n".join(blocks)
                    system_prompt, user_prompt = build_weekly_digest_prompt(topic_name, corpus)
                    if len(blocks) < WEEKLY_SOURCE_DAYS:
                        print(f"[digest bg] {slug} weekly — slechts {len(blocks)} dag-digests "
                              f"beschikbaar (<{WEEKLY_SOURCE_DAYS})", flush=True)

            if system_prompt is None:
                # Ruwe-items-pad: daily, óf weekly-fallback zonder bruikbare dag-history.
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
                    msg = f"Geen nieuwe items voor dit topic in de afgelopen {window_hours // 24} dag(en)."
                    await bg.exec(sa_text(
                        "UPDATE topic_digests SET is_generating=false, error=NULL, "
                        "markdown=:m, item_count=0, model=NULL, generated_at=now() "
                        "WHERE topic_id=CAST(:tid AS uuid) AND window_hours=:w"
                    ).bindparams(m=msg, tid=topic_id, w=window_hours))
                    await bg.commit()
                    print(f"[digest bg] {slug} {window_hours}u klaar — 0 items (geen content)", flush=True)
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
            markdown = ""
            last_err: Optional[Exception] = None
            for attempt in range(2):
                try:
                    markdown = await llm_service.call_llm(llm_alias, [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ], temperature=base_temp if attempt == 0 else min(base_temp + 0.2, 0.7),
                       timeout=DIGEST_LLM_TIMEOUT)
                    if markdown and markdown.strip():
                        break
                except Exception as e:
                    last_err = e
                    print(f"[digest bg] {slug} {window_hours}u poging {attempt+1} faalde: {e}", flush=True)
            if not (markdown and markdown.strip()):
                raise last_err or RuntimeError(f"LLM gaf 2x lege output (model {llm_alias})")

            await bg.exec(sa_text(
                """
                UPDATE topic_digests SET
                  markdown = :m, item_count = :n, model = :ml,
                  generated_at = now(), is_generating = false, error = NULL
                WHERE topic_id = CAST(:tid AS uuid) AND window_hours = :w
                """
            ).bindparams(m=markdown.strip(), n=len(blocks), ml=llm_alias,
                         w=window_hours, tid=topic_id))
            # Append run-history zodat user door de laatste 7 kan navigeren.
            await bg.exec(sa_text(
                """
                INSERT INTO topic_digest_runs (topic_id, window_hours, model, item_count, markdown)
                VALUES (CAST(:tid AS uuid), :w, :ml, :n, :m)
                """
            ).bindparams(tid=topic_id, w=window_hours, ml=llm_alias,
                         n=len(blocks), m=markdown.strip()))
            await bg.commit()
            print(f"[digest bg] {slug} {window_hours}u klaar — {len(blocks)} items, {llm_alias}",
                  flush=True)
    except Exception as exc:
        msg = (str(exc) or repr(exc) or type(exc).__name__).strip() or "onbekende fout"
        try:
            async with async_session_maker() as bg:
                await bg.exec(sa_text(
                    "UPDATE topic_digests SET is_generating=false, error=:e "
                    "WHERE topic_id=CAST(:tid AS uuid) AND window_hours=:w"
                ).bindparams(e=msg[:500], tid=topic_id, w=window_hours))
                await bg.commit()
        except Exception:
            pass
        print(f"[digest bg] {slug} {window_hours}u faalde: {msg}", flush=True)
