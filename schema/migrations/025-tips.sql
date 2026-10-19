-- Migration 025: tips-mining — aanbevelingen (boeken, software, films, …) uit
-- transcripten. Zie docs/tips-mining.md.
--
-- Alleen nieuwe tabellen; raakt `items` niet en is dus zonder lock te draaien.

-- Eén rij per gevonden tip per transcriptvenster.
CREATE TABLE IF NOT EXISTS tip_mentions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id         UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    window_offset   INT  NOT NULL,
    category        TEXT NOT NULL,
    title           TEXT NOT NULL,
    title_key       TEXT NOT NULL,          -- genormaliseerde titel; werk = (category, title_key)
    creator         TEXT,
    recommended_by  TEXT,
    strength        TEXT NOT NULL CHECK (strength IN ('strong', 'medium', 'weak')),
    why             TEXT,
    quote           TEXT,
    model           TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tip_mentions_item ON tip_mentions (item_id);
CREATE INDEX IF NOT EXISTS idx_tip_mentions_work ON tip_mentions (category, title_key);

-- Oordeel van het verificatiemodel per werk: echt werk of ruis, plus canonieke
-- titel/maker/categorie. Een werk is (category, title_key): het boek Dune en de
-- film Dune zijn twee werken.
CREATE TABLE IF NOT EXISTS tip_works (
    category        TEXT NOT NULL,       -- categorie zoals in tip_mentions
    title_key       TEXT NOT NULL,
    keep            BOOLEAN NOT NULL,
    title           TEXT,
    creator         TEXT,
    canon_category  TEXT,                -- categorie volgens het verificatiemodel
    confidence      TEXT,
    model           TEXT,
    verified_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (category, title_key)
);

-- Welke items gescand zijn. `failed` wordt na 24 uur opnieuw geprobeerd, max 3×.
CREATE TABLE IF NOT EXISTS tip_scans (
    item_id     UUID PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    status      TEXT NOT NULL CHECK (status IN ('done', 'failed')),
    windows     INT  NOT NULL DEFAULT 0,
    attempts    INT  NOT NULL DEFAULT 0,
    model       TEXT,
    error       TEXT,
    scanned_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
