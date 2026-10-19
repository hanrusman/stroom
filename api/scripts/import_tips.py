"""Eenmalige import van de tips-batch-run (oktober 2026) in de DB."""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/app")

from sqlalchemy import text as sa_text

from core.db import async_engine
from services import tips_service
from services.tips_helpers import ALIAS

BATCH = 500
IMPORT_MODEL = "import-2026-10"

MENTION_STMT = sa_text(
    "INSERT INTO tip_mentions (item_id, window_offset, category, title, title_key, "
    "creator, recommended_by, strength, why, quote, model) "
    "VALUES (CAST(:item_id AS uuid), :off, :cat, :title, :tk, :creator, :by, "
    ":strength, :why, :quote, :model)"
)
SCAN_STMT = sa_text(
    "INSERT INTO tip_scans (item_id, status, windows, attempts, model, error, scanned_at) "
    "VALUES (CAST(:item_id AS uuid), 'done', :windows, 1, :model, NULL, now()) "
    "ON CONFLICT (item_id) DO NOTHING"
)
WORK_STMT = sa_text(
    "INSERT INTO tip_works (category, title_key, keep, title, creator, canon_category, "
    "confidence, model) "
    "VALUES (:cat, :tk, :keep, :title, :creator, :canon, :conf, :model) "
    "ON CONFLICT (category, title_key) DO NOTHING"
)


def parse_args() -> argparse.Namespace:
    """Commandoregel-argumenten parsen."""
    parser = argparse.ArgumentParser(description="Importeer de tips-batch-run in de DB.")
    parser.add_argument("--mentions", nargs="+", required=True,
                        help="JSONL-bestanden met venster-uitvoer per model")
    parser.add_argument("--verified", required=True,
                        help="JSONL-bestand met verificaties per title_key")
    parser.add_argument("--dry-run", action="store_true",
                        help="Alles berekenen en tellen, niets schrijven")
    return parser.parse_args()


def read_windows(paths: list[str]) -> dict[str, list[dict]]:
    """Alle venster-regels lezen, gegroepeerd per item_id."""
    windows: dict[str, list[dict]] = {}
    for path in paths:
        if not Path(path).exists():
            sys.exit(f"Bestand niet gevonden: {path}")
        with Path(path).open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                windows.setdefault(str(rec.get("item_id")), []).append(
                    {
                        "offset": int(rec.get("offset") or 0),
                        "model": str(rec.get("model") or ""),
                        "tips": rec.get("tips") or [],
                    }
                )
    return windows


def read_verified(path: str) -> list[dict]:
    """Verificaties lezen; bij dubbele title_key wint de eerste."""
    if not Path(path).exists():
        sys.exit(f"Bestand niet gevonden: {path}")
    rows: list[dict] = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            tk = tips_service.title_key(rec.get("key"))
            if not tk or tk in seen:
                continue
            seen.add(tk)
            rows.append(
                {
                    "tk": tk,
                    "keep": bool(rec.get("v_keep")),
                    "title": rec.get("v_title"),
                    "creator": rec.get("v_creator"),
                    "canon": rec.get("v_category"),
                    "conf": rec.get("v_confidence"),
                    "model": IMPORT_MODEL,
                }
            )
    return rows


def work_rows(verified: list[dict], cats_by_tk: dict[str, Counter]) -> list[dict]:
    """Batch-verificaties (per titel) omzetten naar werken (categorie, titel).

    De batch-run verifieerde per titel, over categorieën heen. Het oordeel geldt
    hier alleen voor de categorie waar het over ging: de categorie die de
    verifier noemde als die voorkomt, anders de meest voorkomende. Andere
    categorieën met dezelfde titel (het boek Dune naast de film) blijven
    ongeverifieerd; de job verifieert ze daarna zelf.
    """
    rows: list[dict] = []
    for v in verified:
        cats = cats_by_tk.get(v["tk"])
        if not cats:
            continue
        canon = ALIAS.get(v["canon"], v["canon"])
        cat = canon if canon in cats else cats.most_common(1)[0][0]
        rows.append({**v, "cat": cat, "canon": canon or cat})
    return rows


def _is_self_promo(tip: dict) -> bool:
    """Categorie of sterkte self_promo slaan we nooit op."""
    return (
        str(tip.get("category") or "").lower() == "self_promo"
        or str(tip.get("strength") or "").lower() == "self_promo"
    )


def mention_rows(item_id: str, wins: list[dict]) -> list[dict]:
    """Mention-rijen voor één item, geduped op (offset, title_key, model)."""
    rows: list[dict] = []
    seen: set[tuple[int, str, str]] = set()
    for win in wins:
        for tip in tips_service.parse_tips(json.dumps({"tips": win["tips"]})):
            if _is_self_promo(tip):
                continue
            tk = tips_service.title_key(tip.get("title"))
            if not tk:
                continue
            key = (win["offset"], tk, win["model"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "item_id": item_id,
                    "off": win["offset"],
                    "cat": tip.get("category"),
                    "title": tip.get("title"),
                    "tk": tk,
                    "creator": tip.get("creator"),
                    "by": tip.get("recommended_by"),
                    "strength": tip.get("strength"),
                    "why": tip.get("why"),
                    "quote": tip.get("quote"),
                    "model": win["model"],
                }
            )
    return rows


async def flush_batch(session, mentions: list[dict], scans: list[dict], dry_run: bool) -> None:
    """Eén batch wegschrijven; bij dry-run alleen de buffers legen."""
    if not mentions and not scans:
        return
    if not dry_run:
        if mentions:
            await session.execute(MENTION_STMT, mentions)
        if scans:
            await session.execute(SCAN_STMT, scans)
        await session.commit()
    mentions.clear()
    scans.clear()


async def main() -> None:
    """Batch-uitvoer lezen en tip_mentions, tip_scans en tip_works vullen."""
    args = parse_args()
    windows_by_item = read_windows(args.mentions)
    verified = read_verified(args.verified)

    n_items = n_missing = n_scanned = n_mentions = n_works = 0
    # Kale SQLAlchemy-connectie: executemany met een lijst parameters, zonder sqlmodel-waarschuwingen.
    async with async_engine.connect() as session:
        res = await session.execute(sa_text("SELECT id::text FROM items"))
        item_ids = {row[0] for row in res}
        res = await session.execute(sa_text("SELECT item_id::text FROM tip_scans"))
        scanned_ids = {row[0] for row in res}

        pending_mentions: list[dict] = []
        pending_scans: list[dict] = []
        cats_by_tk: dict[str, Counter] = {}
        for item_id in sorted(windows_by_item):
            if item_id not in item_ids:
                n_missing += 1
                continue
            if item_id in scanned_ids:
                n_scanned += 1
                continue
            wins = windows_by_item[item_id]
            rows = mention_rows(item_id, wins)
            n_items += 1
            n_mentions += len(rows)
            pending_mentions.extend(rows)
            for r in rows:
                cats_by_tk.setdefault(r["tk"], Counter())[r["cat"]] += 1
            pending_scans.append(
                {
                    "item_id": item_id,
                    "windows": len({w["offset"] for w in wins}),
                    "model": ",".join(sorted({w["model"] for w in wins})),
                }
            )
            if len(pending_mentions) >= BATCH or len(pending_scans) >= BATCH:
                await flush_batch(session, pending_mentions, pending_scans, args.dry_run)
                print(f"Voortgang: {n_items} items, {n_mentions} mentions", flush=True)
        await flush_batch(session, pending_mentions, pending_scans, args.dry_run)

        works = work_rows(verified, cats_by_tk)
        for i in range(0, len(works), BATCH):
            chunk = works[i : i + BATCH]
            n_works += len(chunk)
            if not args.dry_run:
                await session.execute(WORK_STMT, chunk)
                await session.commit()
            print(f"Voortgang works: {n_works}/{len(works)}", flush=True)

    print(f"Items geïmporteerd: {n_items}", flush=True)
    print(
        f"Items overgeslagen: {n_missing + n_scanned} "
        f"(onbekend: {n_missing}, al gescand: {n_scanned})",
        flush=True,
    )
    print(f"Mentions: {n_mentions}", flush=True)
    print(f"Works: {n_works}", flush=True)
    if args.dry_run:
        print("Dry run: niets geschreven.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
