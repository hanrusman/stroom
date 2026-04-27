-- Huygens: topics taxonomy + format axis on items.
-- - topics: themes shown as Huygens pages (AI, urbanism, ...)
-- - source_topics: default topics inherited by every new item from a source
-- - item_topics: per-item topics (overrides/refines inheritance)
-- - items.format: how the item renders in the UI rail (article/podcast/video/short),
--   independent of sources.kind (where it came from).

BEGIN;

CREATE TABLE topics (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug       text UNIQUE NOT NULL,
  name       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE source_topics (
  source_id uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  topic_id  uuid NOT NULL REFERENCES topics(id)  ON DELETE CASCADE,
  PRIMARY KEY (source_id, topic_id)
);

CREATE TABLE item_topics (
  item_id  uuid NOT NULL REFERENCES items(id)  ON DELETE CASCADE,
  topic_id uuid NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  PRIMARY KEY (item_id, topic_id)
);
CREATE INDEX idx_item_topics_topic ON item_topics(topic_id);

CREATE TYPE item_format AS ENUM ('article','podcast','video','short');
ALTER TABLE items ADD COLUMN format item_format;
CREATE INDEX idx_items_format ON items(format);

COMMIT;
