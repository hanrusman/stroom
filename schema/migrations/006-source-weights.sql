-- Source-level controls voor admin-scherm:
--  - weight: 1-10, default 5. Beïnvloedt ranking: hogere weight = item komt eerder bovenaan
--  - max_per_rail: max items per source per rail (null = geen cap)
--  - active: false = source verdwijnt uit feed zonder data te verliezen

ALTER TABLE sources ADD COLUMN IF NOT EXISTS weight integer NOT NULL DEFAULT 5
    CHECK (weight BETWEEN 1 AND 10);
ALTER TABLE sources ADD COLUMN IF NOT EXISTS max_per_rail integer
    CHECK (max_per_rail IS NULL OR max_per_rail > 0);
ALTER TABLE sources ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;

CREATE INDEX IF NOT EXISTS idx_sources_active ON sources(active) WHERE active;
