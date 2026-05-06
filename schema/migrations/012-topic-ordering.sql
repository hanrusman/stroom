-- Topics ordering: sort_order column. Lower = first.
ALTER TABLE topics ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;

-- Backfill from current alphabetical order, spaced by 10 to leave room for inserts.
WITH ordered AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY name) * 10 AS pos
  FROM topics
)
UPDATE topics t SET sort_order = o.pos
FROM ordered o
WHERE t.id = o.id AND t.sort_order = 0;

CREATE INDEX IF NOT EXISTS idx_topics_sort_order ON topics(sort_order, name);
