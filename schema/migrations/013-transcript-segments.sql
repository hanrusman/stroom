-- Word/segment-level transcript timing for click-to-seek in podcast/video items.
-- Shape: [{"start": float_seconds, "end": float_seconds, "text": str, "speaker": optional str}]
ALTER TABLE items ADD COLUMN IF NOT EXISTS transcript_segments JSONB;
