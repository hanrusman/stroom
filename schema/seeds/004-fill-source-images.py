"""Pull the channel-level image for each source feed and store on sources.image_url."""
from __future__ import annotations
import sys, feedparser, psycopg


def channel_image(feed) -> str | None:
    f = feed.feed
    if getattr(f, "image", None) and getattr(f.image, "href", None):
        return f.image.href
    img = f.get("image")
    if isinstance(img, dict) and img.get("href"):
        return img["href"]
    if isinstance(img, dict) and img.get("url"):
        return img["url"]
    if f.get("itunes_image"):
        v = f["itunes_image"]
        if isinstance(v, dict):
            return v.get("href") or v.get("url")
    return None


def main() -> int:
    conn = psycopg.connect(autocommit=False)
    with conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, url FROM sources WHERE image_url IS NULL")
        for sid, name, url in cur.fetchall():
            print(f"[{name}] {url}")
            feed = feedparser.parse(url)
            img = channel_image(feed)
            if not img:
                print("  ! no channel image")
                continue
            cur.execute("UPDATE sources SET image_url=%s WHERE id=%s", (img, sid))
            print(f"  + {img}")
        conn.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
