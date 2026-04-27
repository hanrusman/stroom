"""Pull the 3 most recent items from each topic-tagged source and write them
to items + item_topics. Idempotent on (source_id, external_id).

Run via:
    docker run --rm --network personal_net \
      -v /opt/stacks/vps-stacks/stroom-src/schema/seeds:/seeds \
      -e PGHOST=stroom-db -e PGUSER=stroom -e PGDATABASE=stroom \
      -e PGPASSWORD=... \
      python:3.12-slim sh -c "pip install -q feedparser psycopg[binary] && python /seeds/003-ingest-recent-items.py"
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import feedparser
import psycopg

PER_SOURCE = 10

KIND_TO_FORMAT = {"rss": "article", "podcast": "podcast", "youtube": "video"}


def to_dt(struct_time) -> datetime | None:
    if not struct_time:
        return None
    return datetime(*struct_time[:6], tzinfo=timezone.utc)


def first_text(entry, *keys) -> str | None:
    for k in keys:
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list) and v and isinstance(v[0], dict) and v[0].get("value"):
            return v[0]["value"].strip()
    return None


def media_url(entry) -> str | None:
    for enc in entry.get("enclosures") or []:
        if enc.get("url"):
            return enc["url"]
    if entry.get("media_content"):
        for mc in entry["media_content"]:
            if mc.get("url"):
                return mc["url"]
    return entry.get("link")


def thumb_url(entry) -> str | None:
    if entry.get("media_thumbnail"):
        return entry["media_thumbnail"][0].get("url")
    return None


def main() -> int:
    conn = psycopg.connect(autocommit=False)
    with conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.name, s.kind::text, s.url
            FROM sources s
            WHERE EXISTS (SELECT 1 FROM source_topics st WHERE st.source_id = s.id)
            """
        )
        sources = cur.fetchall()

        for sid, name, kind, url in sources:
            print(f"[{name}] fetching {url}")
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                print(f"  ! parse error: {feed.bozo_exception}")
                continue

            fmt = KIND_TO_FORMAT.get(kind, "article")
            inserted = 0
            for entry in feed.entries[:PER_SOURCE]:
                ext_id = entry.get("id") or entry.get("link")
                if not ext_id:
                    continue
                title = first_text(entry, "title") or "(untitled)"
                desc = first_text(entry, "summary", "description")
                author = first_text(entry, "author")
                published = to_dt(entry.get("published_parsed") or entry.get("updated_parsed"))

                cur.execute(
                    """
                    INSERT INTO items
                        (source_id, external_id, type, format, title, description,
                         author, media_url, thumbnail_url, published_at,
                         processing_status, status)
                    VALUES (%s, %s, %s::content_kind, %s::item_format, %s, %s,
                            %s, %s, %s, %s, 'ready', 'new')
                    ON CONFLICT (source_id, external_id) DO NOTHING
                    RETURNING id
                    """,
                    (sid, ext_id, kind, fmt, title, desc, author,
                     media_url(entry), thumb_url(entry), published),
                )
                row = cur.fetchone()
                if not row:
                    continue
                item_id = row[0]
                cur.execute(
                    """
                    INSERT INTO item_topics (item_id, topic_id)
                    SELECT %s, st.topic_id FROM source_topics st WHERE st.source_id = %s
                    """,
                    (item_id, sid),
                )
                inserted += 1
            print(f"  + {inserted} new items")
        conn.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
