-- Track how many times we've tried to transcribe an item; cap retries to avoid loops on permanent failures.
ALTER TABLE items ADD COLUMN IF NOT EXISTS transcribe_attempts INT NOT NULL DEFAULT 0;
