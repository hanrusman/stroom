-- 020: Add Vikunja task tracking to lessons
-- Tracks which lessons have been sent to Vikunja inbox

ALTER TABLE lessons ADD COLUMN IF NOT EXISTS vikunja_task_id BIGINT;
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS vikunja_sent_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_lessons_vikunja_sent ON lessons (vikunja_sent_at) WHERE vikunja_sent_at IS NOT NULL;
