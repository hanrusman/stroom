-- Split 'queued' into separate transcribe/summarize queues.
-- Transcribe (A2 GPU, single concurrent) vs summarize (external LLM, parallel).
ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'transcribe_queued' BEFORE 'transcribing';
ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'summarize_queued' BEFORE 'summarizing';

CREATE INDEX IF NOT EXISTS idx_items_transcribe_queued ON items(queued_at)
  WHERE processing_status = 'transcribe_queued';

CREATE INDEX IF NOT EXISTS idx_items_summarize_queued ON items(queued_at)
  WHERE processing_status = 'summarize_queued';
