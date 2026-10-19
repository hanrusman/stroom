"""Ruisfilters en aggregatie voor tips-mining: aanbevelingen uit podcasttranscripten."""

import re
from collections import Counter

from services.tips_helpers import ALIAS, WEIGHT, norm, same_work, title_key, who_label

AD = re.compile(
    r"sponsor|brought to you|supported by|promo ?code|use code|\.com/|gesponsord|advertentie|"
    r"reclame|kortingscode|this episode is|deze aflevering wordt|free trial|gratis proef|"
    r"\bslash \w+|favou?rite compan|time to (thank|talk about) one of|our (friends|partners) at|"
    r"dot com|\.(com|io|ai)/\w+|go to \w+\.(com|io|ai)|fastest path to", re.I)
NETWORK = {"nyt": ("new york times", "nyt"), "goalhanger": ("goalhanger",), "vox": ("vox",),
           "npo": ("npo",), "bnr": ("bnr",), "correspondent": ("correspondent",)}
NET_OF_SOURCE = {"The Daily (NYT)": "nyt", "Hard Fork (NYT)": "nyt", "Ezra Klein": "nyt",
                 "The Rest Is Politics": "goalhanger", "Today Explained": "vox",
                 "The Vergecast": "vox", "Radio 1": "npo", "BNR tech show": "bnr",
                 "De Correspondent": "correspondent"}
RECURRING_AD_CATEGORIES = ("podcast", "newsletter", "software")


def quote_key(q: str | None) -> str:
    """Genormaliseerde, ingekorte sleutel voor een quote."""
    return re.sub(r"[^a-z]+", " ", (q or "").lower()).strip()[:60]


def is_promo(m: dict, creator: str | None, qcount: dict[str, int]) -> bool:
    """Geeft True als een mention vermoedelijk reclame of zelfpromotie is."""
    by = (m["recommended_by"] or "").lower()
    if "self_promo" in by or "sponsor" in by:
        return True
    if AD.search((m["quote"] or "") + " " + (m["why"] or "")):
        return True
    qk = quote_key(m["quote"])
    if len(qk) >= 25 and qcount.get(qk, 0) >= 3:
        return True
    t = norm(m["title"])
    s = norm(m["source"])
    if t and s and (t == s or (len(t) > 4 and t in s) or (len(s) > 4 and s in t)):
        return True
    cr = (creator or "").lower()
    net = NET_OF_SOURCE.get(m["source"])
    if net and any(alias in cr for alias in NETWORK[net]):
        return True
    if by and cr and len(by) > 3 and (by in cr or cr in by):
        return True
    if cr and len(cr) > 4 and cr in (m["source"] or "").lower():
        return True
    return False


def _most_common(values: list[str | None]) -> str | None:
    """Meest voorkomende waarde; bij gelijke telling de eerstgeziene."""
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def aggregate(mentions: list[dict], works: dict[tuple[str, str], dict],
              since: str | None = None) -> list[dict]:
    """Filtert ruis weg en aggregeert mentions per werk tot aanbevelingen.

    Een werk is (category, title_key): het boek Dune en de film Dune zijn twee
    werken, ook als ze in dezelfde aflevering vallen. `works` is de verificatie,
    gekeyd op diezelfde identiteit.
    """
    # Eerst één mention per (item, werk): overlappende vensters en meerdere modellen
    # leveren hetzelfde citaat vaak 2-3× uit dezelfde aflevering, en dat zou de
    # sponsor-read-telling hieronder ten onrechte laten afgaan.
    best: dict[tuple[str, str], dict] = {}
    for m in mentions:
        k = (m["item_id"], m["category"], m["title_key"])
        cur = best.get(k)
        if cur is None or WEIGHT[m["strength"]] > WEIGHT[cur["strength"]]:
            best[k] = m
    mentions = list(best.values())

    qcount: Counter[str] = Counter(
        quote_key(m["quote"]) for m in mentions if len(quote_key(m["quote"])) >= 25)

    groups: dict[tuple[str, str], list[dict]] = {}
    for m in mentions:
        groups.setdefault((m["category"], m["title_key"]), []).append(m)

    final: dict[tuple[str | None, str], dict] = {}
    for k, ms in groups.items():
        w = works.get(k)
        if w is None or w.get("keep") is not True:
            continue
        creator0 = _most_common([m["creator"] for m in ms if m["creator"]])
        title0 = _most_common([m["title"] for m in ms])
        cat0 = k[0]

        flags = [is_promo(m, creator0, qcount) for m in ms]
        flagged = Counter(m["source"] for m, f in zip(ms, flags) if f)
        sponsor_in = {src for src, n in flagged.items() if n >= 2}
        keep = [m for m, f in zip(ms, flags) if not f and m["source"] not in sponsor_in]
        if not keep:
            continue

        sure = w.get("confidence") in ("high", "medium")
        w_title = w.get("title")
        title = w_title if sure and w_title and same_work(title0, w_title) else title0
        w_creator = w.get("creator")
        creator = w_creator if sure and w_creator else creator0
        w_cat = w.get("category")
        cat = w_cat if sure and w_cat else cat0
        cat = ALIAS.get(cat, cat)

        key = (cat, title_key(title))
        entry = final.get(key)
        if entry is None:
            entry = {"title": title, "creator": creator, "category": cat,
                     "aka": set(), "by_item": {}}
            final[key] = entry
        if title0:
            entry["aka"].add(title0)
        if not entry["creator"]:
            entry["creator"] = creator
        for m in keep:
            cur = entry["by_item"].get(m["item_id"])
            if cur is None or WEIGHT[m["strength"]] > WEIGHT[cur["strength"]]:
                entry["by_item"][m["item_id"]] = m

    # Vaste advertenties: >= 4 items uit één show in een terugkerende categorie.
    final = {key: entry for key, entry in final.items()
             if not (entry["category"] in RECURRING_AD_CATEGORIES
                     and len(entry["by_item"]) >= 4
                     and len({m["source"] for m in entry["by_item"].values()}) == 1)}

    if since:
        for entry in final.values():
            entry["by_item"] = {iid: m for iid, m in entry["by_item"].items()
                                if m["published"] is not None and m["published"] >= since}
        final = {key: entry for key, entry in final.items() if entry["by_item"]}

    out: list[dict] = []
    for entry in final.values():
        ms = list(entry["by_item"].values())
        ms.sort(key=lambda m: m["published"] or "", reverse=True)
        ms.sort(key=lambda m: WEIGHT[m["strength"]], reverse=True)
        labels = [who_label(m["recommended_by"], m["source"]) for m in ms]
        pubs = [m["published"] for m in ms if m["published"]]
        title = entry["title"]
        out.append({
            "title": title,
            "creator": entry["creator"],
            "category": entry["category"],
            "title_key": title_key(title),
            "score": sum(WEIGHT[m["strength"]] for m in ms),
            "episodes": len(ms),
            "strong": sum(1 for m in ms if m["strength"] == "strong"),
            "who": list(dict.fromkeys(labels)),
            "blurb": next((m["why"] for m in ms if m["why"]), None),
            "sources": sorted({m["source"] for m in ms if m["source"]}),
            "last_mentioned": max(pubs) if pubs else None,
            "aka": sorted(a for a in entry["aka"] if a != title),
            "mentions": [
                {"item_id": m["item_id"], "source": m["source"], "episode": m["episode"],
                 "published": m["published"], "by": label, "strength": m["strength"],
                 "why": m["why"], "quote": m["quote"]}
                for m, label in zip(ms, labels)],
        })
    out.sort(key=lambda r: (-r["score"], -r["episodes"], (r["title"] or "").lower()))
    return out


def query_works(works: list[dict], *, category: str | None = None, q: str | None = None,
                source: str | None = None, strong_only: bool = False,
                min_episodes: int = 1, sort: str = "score", limit: int = 100,
                offset: int = 0) -> dict:
    """Filtert, facetteert, sorteert en pagineert geaggregeerde werken."""
    base: list[dict] = []
    for w in works:
        if q:
            needle = q.lower()
            parts: list[str | None] = [w.get("title"), w.get("creator")]
            parts += list(w.get("aka") or [])
            parts += list(w.get("sources") or [])
            parts += list(w.get("who") or [])
            if not any(needle in (p or "").lower() for p in parts):
                continue
        if source and source not in (w.get("sources") or []):
            continue
        if strong_only and (w.get("strong") or 0) <= 0:
            continue
        if (w.get("episodes") or 0) < min_episodes:
            continue
        base.append(w)

    categories = dict(Counter(w.get("category") for w in base))
    if category:
        base = [w for w in base if w.get("category") == category]

    src_count: Counter[str] = Counter()
    for w in base:
        for name in w.get("sources") or []:
            src_count[name] += 1
    sources = [{"name": name, "n": n}
               for name, n in sorted(src_count.items(), key=lambda kv: (-kv[1], kv[0]))]

    if sort == "episodes":
        base.sort(key=lambda w: (-(w.get("episodes") or 0), -(w.get("score") or 0),
                                  (w.get("title") or "").lower()))
    elif sort == "recent":
        base.sort(key=lambda w: (w.get("last_mentioned") is not None,
                                 w.get("last_mentioned") or "",
                                 w.get("score") or 0), reverse=True)
    elif sort == "title":
        base.sort(key=lambda w: (w.get("title") or "").lower())
    else:
        base.sort(key=lambda w: (-(w.get("score") or 0), -(w.get("episodes") or 0),
                                  (w.get("title") or "").lower()))

    page = base[offset:offset + limit]
    return {
        "total": len(base),
        "categories": categories,
        "sources": sources,
        "works": [{k: v for k, v in w.items() if k != "mentions"} for w in page],
    }