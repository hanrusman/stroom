-- 008: per-topic dagdigest, opgeslagen, te verversen via knop in UI.
-- Eén rij per topic; refresh = UPDATE.

CREATE TABLE IF NOT EXISTS topic_digests (
  topic_id      UUID PRIMARY KEY REFERENCES topics(id) ON DELETE CASCADE,
  markdown      TEXT NOT NULL,
  item_count    INT  NOT NULL,
  model         TEXT,
  window_hours  INT  NOT NULL DEFAULT 24,
  generated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
