-- Quality score for items based on LLM evaluation
ALTER TABLE items ADD COLUMN IF NOT EXISTS quality_score SMALLINT DEFAULT 5;

-- Create index for efficient sorting by quality
CREATE INDEX IF NOT EXISTS idx_items_quality_score ON items(quality_score DESC, published_at DESC);

-- Backfill existing items with neutral score (will be rescored on next summarize)
UPDATE items SET quality_score = 5 WHERE quality_score IS NULL;
