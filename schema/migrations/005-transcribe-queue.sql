-- Add 'queued' to processing_status enum + queued_at column for FIFO ordering.
ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'queued' BEFORE 'transcribing';

ALTER TABLE items ADD COLUMN IF NOT EXISTS queued_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_items_queued_at ON items(queued_at)
  WHERE processing_status = 'queued';
