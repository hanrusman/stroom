-- 007: lessons-curatie + scheduled_for op items
-- Lessons: binaire ✓/✗ curatie van Kernlessen uit summarize.py output.
-- scheduled_for: optionele datum bij item_status='later'.

CREATE TABLE IF NOT EXISTS lessons (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id     UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  idx         INT  NOT NULL,
  title       TEXT NOT NULL,
  body        TEXT NOT NULL,
  rating      SMALLINT,             -- NULL=ongekureerd, 1=nuttig, -1=niet
  rated_at    TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (item_id, idx)
);

CREATE INDEX IF NOT EXISTS idx_lessons_item_id ON lessons (item_id);
CREATE INDEX IF NOT EXISTS idx_lessons_rating  ON lessons (rating) WHERE rating IS NOT NULL;

ALTER TABLE items ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_items_scheduled_for ON items (scheduled_for) WHERE scheduled_for IS NOT NULL;
