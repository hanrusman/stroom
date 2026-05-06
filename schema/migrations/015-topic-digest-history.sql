-- History van topic-digests, één rij per geslaagde generatie.
-- topic_digests blijft voor de "huidige" rij + is_generating state.
CREATE TABLE IF NOT EXISTS topic_digest_runs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  topic_id      uuid NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  window_hours  integer NOT NULL,
  generated_at  timestamptz NOT NULL DEFAULT now(),
  model         text,
  item_count    integer,
  markdown      text NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_topic_digest_runs_lookup
  ON topic_digest_runs(topic_id, window_hours, generated_at DESC);

-- Backfill: zet de huidige rij in de history zodat we niet leeg beginnen.
INSERT INTO topic_digest_runs (topic_id, window_hours, generated_at, model, item_count, markdown)
SELECT topic_id, window_hours, generated_at, model, item_count, markdown
FROM topic_digests
WHERE markdown IS NOT NULL AND markdown <> ''
ON CONFLICT DO NOTHING;
