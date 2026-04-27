"""Backfill items.thumbnail_url door og:image / twitter:image van media_url te scrapen.

Run binnen de stroom-api container (heeft DATABASE_URL + httpx + psycopg2):
    docker cp 008-fill-item-thumbnails.py stroom-api:/tmp/
    docker exec stroom-api python /tmp/008-fill-item-thumbnails.py [--limit N] [--type rss|podcast]
"""
from __future__ import annotations
import argparse, os, re, sys, time
import httpx
import psycopg2

OG_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']', re.I),
]


def find_image(html: str) -> str | None:
    for pat in OG_PATTERNS:
        m = pat.search(html)
        if m:
            return m.group(1).strip()
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500, help="max items per run")
    ap.add_argument("--type", choices=["rss", "podcast", "youtube"], help="filter on item type")
    ap.add_argument("--sleep", type=float, default=0.5, help="seconds between requests")
    args = ap.parse_args()

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    where = "thumbnail_url IS NULL AND media_url IS NOT NULL"
    params: list = []
    if args.type:
        where += " AND type = %s"
        params.append(args.type)
    cur.execute(f"SELECT id, title, media_url FROM items WHERE {where} ORDER BY published_at DESC NULLS LAST LIMIT %s",
                params + [args.limit])
    rows = cur.fetchall()
    print(f"items zonder thumbnail: {len(rows)}", flush=True)

    headers = {"User-Agent": "StroomBot/1.0 (+image-backfill)"}
    ok = miss = err = 0
    with httpx.Client(headers=headers, timeout=12.0, follow_redirects=True) as client:
        for iid, title, url in rows:
            try:
                r = client.get(url)
                if r.status_code != 200:
                    err += 1
                    print(f"  [{r.status_code}] {title[:60]}", flush=True)
                    continue
                ctype = r.headers.get("content-type", "")
                if "html" not in ctype:
                    miss += 1
                    continue
                # Beperk tot eerste 200KB — og-tags staan altijd in <head>.
                img = find_image(r.text[:200_000])
                if img:
                    if img.startswith("//"):
                        img = "https:" + img
                    elif img.startswith("/"):
                        from urllib.parse import urljoin
                        img = urljoin(url, img)
                    cur.execute("UPDATE items SET thumbnail_url=%s WHERE id=%s", (img, iid))
                    conn.commit()
                    ok += 1
                    print(f"  ok: {title[:60]}", flush=True)
                else:
                    miss += 1
            except Exception as e:
                err += 1
                print(f"  err: {title[:60]} → {e}", flush=True)
            time.sleep(args.sleep)

    print(f"\nfilled={ok} no-image={miss} errors={err}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
