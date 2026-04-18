-- Stroom schema — Fase 1
-- 3 extensions, 8 enums, 8 tables, 3 views.

-- === Extensions ===
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- === Enums ===
CREATE TYPE content_kind       AS ENUM ('youtube','rss','podcast');
CREATE TYPE processing_status  AS ENUM ('pending','transcribing','summarizing','ready','failed');
CREATE TYPE item_status        AS ENUM ('new','pinned','later','archived');
CREATE TYPE insight_category   AS ENUM ('ideeën','quotes','film-tv','kids','podcasts','boeken');
CREATE TYPE episode_range      AS ENUM ('day','week','month');
CREATE TYPE episode_status     AS ENUM ('generating','ready','failed');
CREATE TYPE feed_event_type    AS ENUM ('new','pinned','later','archived','viewed');

-- === Tables ===

CREATE TABLE sources (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind               content_kind NOT NULL,
  name               TEXT NOT NULL,
  url                TEXT NOT NULL,
  poll_interval_min  INT  NOT NULL DEFAULT 60,
  last_polled_at     TIMESTAMPTZ,
  last_poll_status   TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE items (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id              UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  external_id            TEXT NOT NULL,
  type                   content_kind NOT NULL,
  title                  TEXT NOT NULL,
  description            TEXT,
  author                 TEXT,
  media_url              TEXT,
  thumbnail_url          TEXT,
  published_at           TIMESTAMPTZ,
  duration_seconds       INT,
  transcript             TEXT,
  summary                TEXT,
  summary_model          TEXT,
  summary_generated_at   TIMESTAMPTZ,
  processing_status      processing_status NOT NULL DEFAULT 'pending',
  processing_error       TEXT,
  status                 item_status NOT NULL DEFAULT 'new',
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_id, external_id)
);

CREATE TABLE insights (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id              UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  position             INT NOT NULL,
  text                 TEXT NOT NULL,
  suggested_category   insight_category,
  embedding            vector(768),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (item_id, position)
);

CREATE TABLE saves (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  insight_id        UUID NOT NULL REFERENCES insights(id) ON DELETE CASCADE,
  category          insight_category NOT NULL,
  note              TEXT,
  obsidian_synced   BOOLEAN NOT NULL DEFAULT FALSE,
  obsidian_path     TEXT,
  saved_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE feed_events (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id      UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  event_type   feed_event_type NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE episodes (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  range              episode_range NOT NULL,
  title              TEXT NOT NULL,
  script             TEXT,
  audio_url          TEXT,
  audio_size_bytes   BIGINT,
  duration_seconds   INT,
  status             episode_status NOT NULL DEFAULT 'generating',
  error              TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reflections (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content      TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE todos (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  insight_id        UUID NOT NULL REFERENCES insights(id) ON DELETE CASCADE,
  vikunja_task_id   BIGINT NOT NULL,
  title             TEXT NOT NULL,
  done              BOOLEAN NOT NULL DEFAULT FALSE,
  done_at           TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (vikunja_task_id)
);

-- === Indexes ===
CREATE INDEX idx_items_processing_status   ON items (processing_status);
CREATE INDEX idx_items_status              ON items (status);
CREATE INDEX idx_items_created_at_desc     ON items (created_at DESC);
CREATE INDEX idx_items_published_at_desc   ON items (published_at DESC NULLS LAST);
CREATE INDEX idx_items_title_trgm          ON items USING gin (title gin_trgm_ops);
CREATE INDEX idx_insights_item_id          ON insights (item_id);
CREATE INDEX idx_insights_embedding        ON insights USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_saves_unsynced            ON saves (saved_at) WHERE obsidian_synced = FALSE;
CREATE INDEX idx_feed_events_item_created  ON feed_events (item_id, created_at DESC);
CREATE INDEX idx_todos_insight_id          ON todos (insight_id);

-- === Views ===

CREATE VIEW v_processing_queue AS
SELECT
  i.id, i.source_id, i.external_id, i.type, i.title, i.media_url,
  i.processing_status, i.processing_error, i.created_at,
  s.name AS source_name
FROM items i
JOIN sources s ON s.id = i.source_id
WHERE i.processing_status IN ('pending','transcribing','summarizing')
ORDER BY i.created_at ASC;

CREATE VIEW v_stream AS
SELECT
  i.id, i.title, i.description, i.author,
  i.media_url, i.thumbnail_url, i.published_at, i.duration_seconds,
  i.summary, i.processing_status, i.status, i.type, i.created_at,
  s.name AS source_name,
  COUNT(ins.id) AS insight_count
FROM items i
JOIN sources s ON s.id = i.source_id
LEFT JOIN insights ins ON ins.item_id = i.id
WHERE i.processing_status = 'ready'
GROUP BY i.id, s.name
ORDER BY COALESCE(i.published_at, i.created_at) DESC;

CREATE VIEW v_obsidian_queue AS
SELECT
  sv.id           AS save_id,
  sv.category,
  sv.note,
  sv.saved_at,
  ins.id          AS insight_id,
  ins.text        AS insight_text,
  it.id           AS item_id,
  it.title        AS item_title,
  it.media_url    AS item_url,
  it.type         AS item_type,
  s.name          AS source_name
FROM saves sv
JOIN insights ins ON ins.id = sv.insight_id
JOIN items it    ON it.id  = ins.item_id
JOIN sources s   ON s.id   = it.source_id
WHERE sv.obsidian_synced = FALSE
ORDER BY sv.saved_at ASC;
