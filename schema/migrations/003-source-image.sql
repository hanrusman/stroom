-- Channel-level artwork for podcasts (and any source that has it).
-- Used as fallback when an item has no per-episode thumbnail.

ALTER TABLE sources ADD COLUMN image_url text;
