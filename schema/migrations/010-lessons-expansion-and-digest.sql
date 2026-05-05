-- 010: per-les verdieping + cross-item lessen-digest.
-- expansion: cached LLM-uitwerking van een les (1-2 alinea's).
-- lessons_digests: gegroepeerde digest van useful/not-useful lessen in venster.

ALTER TABLE lessons ADD COLUMN IF NOT EXISTS expansion TEXT;
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS expansion_model TEXT;
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS expansion_generated_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS lessons_digests (
  window_hours          INT  NOT NULL,
  rating                SMALLINT NOT NULL,  -- 1=useful, -1=not, 0=alles
  markdown              TEXT,
  lesson_count          INT,
  model                 TEXT,
  generated_at          TIMESTAMPTZ,
  is_generating         BOOLEAN NOT NULL DEFAULT false,
  generation_started_at TIMESTAMPTZ,
  error                 TEXT,
  PRIMARY KEY (window_hours, rating)
);
