-- 009: digest-generatie wordt async (504-fix voor lange Qwen-runs).
-- Tracking: is_generating + when started + last error.

ALTER TABLE topic_digests ADD COLUMN IF NOT EXISTS is_generating BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE topic_digests ADD COLUMN IF NOT EXISTS generation_started_at TIMESTAMPTZ;
ALTER TABLE topic_digests ADD COLUMN IF NOT EXISTS error TEXT;

-- markdown mag leeg zijn tijdens eerste generatie.
ALTER TABLE topic_digests ALTER COLUMN markdown DROP NOT NULL;
ALTER TABLE topic_digests ALTER COLUMN item_count DROP NOT NULL;
