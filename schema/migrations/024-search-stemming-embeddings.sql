-- Migration 024: zoeken met stemming + semantische zoekvectoren.
--
-- 1. Stemming. search_tsv gebruikte config 'simple' (geen stemming), dus
--    'verkiezing' vond 'verkiezingen' niet. Op 2026-10-12 vond 'verkiezing'
--    met 'dutch' 414 items op alleen titel+samenvatting, tegen 135 met 'simple'
--    op alles. Content is gemengd NL/EN en er is geen taalkolom, dus we
--    indexeren elk veld in beide talen; de grootste tsvector groeit daardoor
--    maar ~5% (de meeste lexemen vallen samen). stroom_tsquery() zet de
--    zoekvraag op dezelfde manier om: de NL-variant OF de EN-variant.
--
--    Alles herberekenen kost ~8 min CPU (5%-steekproef: 23 s). Een nieuwe
--    GENERATED-kolom zou de tabel al die tijd exclusief locken en de API en de
--    transcribe-callbacks laten vastlopen. Daarom: gewone kolom + trigger,
--    backfill in batches met een COMMIT per batch, index CONCURRENTLY en pas
--    dan een korte swap. search_tsv stond niet in eerdere migraties (was
--    handmatig aangemaakt als GENERATED-kolom); na de swap is hij een gewone
--    kolom die de trigger bijhoudt.
--
--    Draai dit bestand met psql buiten een transactie (geen -1/--single-
--    transaction): de DO-backfill commit zelf en CREATE INDEX CONCURRENTLY
--    mag niet in een transactie.
--
-- 2. Semantisch zoeken. search_embedding = multilingual-e5-small (384 dim) van
--    titel + samenvatting (of description/transcript-begin), gemaakt door de
--    stroom-embed sidecar. services/search_index.py vult hem in de achtergrond
--    en maakt hem opnieuw zodra summary_generated_at na search_embedded_at ligt.

CREATE OR REPLACE FUNCTION stroom_tsquery(q text) RETURNS tsquery
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT websearch_to_tsquery('dutch', q) || websearch_to_tsquery('english', q)
$$;

CREATE OR REPLACE FUNCTION stroom_search_tsv(title text, summary text,
                                             transcript text, description text)
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT setweight(to_tsvector('dutch',   coalesce(title, '')),       'A')
      || setweight(to_tsvector('english', coalesce(title, '')),       'A')
      || setweight(to_tsvector('dutch',   coalesce(summary, '')),     'B')
      || setweight(to_tsvector('english', coalesce(summary, '')),     'B')
      || setweight(to_tsvector('dutch',   coalesce(transcript, '')),  'C')
      || setweight(to_tsvector('english', coalesce(transcript, '')),  'C')
      || setweight(to_tsvector('dutch',   coalesce(description, '')), 'D')
      || setweight(to_tsvector('english', coalesce(description, '')), 'D')
$$;

ALTER TABLE items ADD COLUMN IF NOT EXISTS search_tsv_stem tsvector;

CREATE OR REPLACE FUNCTION items_search_tsv_trg() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.search_tsv_stem := stroom_search_tsv(NEW.title, NEW.summary,
                                           NEW.transcript, NEW.description);
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS items_search_tsv ON items;
CREATE TRIGGER items_search_tsv
  BEFORE INSERT OR UPDATE OF title, summary, transcript, description ON items
  FOR EACH ROW EXECUTE FUNCTION items_search_tsv_trg();

DO $$
DECLARE n int;
BEGIN
  LOOP
    UPDATE items SET search_tsv_stem = stroom_search_tsv(title, summary, transcript, description)
    WHERE id IN (SELECT id FROM items WHERE search_tsv_stem IS NULL LIMIT 200);
    GET DIAGNOSTICS n = ROW_COUNT;
    COMMIT;
    EXIT WHEN n = 0;
  END LOOP;
END $$;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_items_search_tsv_stem
  ON items USING gin (search_tsv_stem);

-- Swap: alleen catalogus-werk, dus een lock van een fractie van een seconde.
BEGIN;
DROP INDEX IF EXISTS idx_items_search_tsv;
ALTER TABLE items DROP COLUMN IF EXISTS search_tsv;
ALTER TABLE items RENAME COLUMN search_tsv_stem TO search_tsv;
ALTER INDEX idx_items_search_tsv_stem RENAME TO idx_items_search_tsv;
CREATE OR REPLACE FUNCTION items_search_tsv_trg() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.search_tsv := stroom_search_tsv(NEW.title, NEW.summary,
                                      NEW.transcript, NEW.description);
  RETURN NEW;
END $$;
COMMIT;

ALTER TABLE items ADD COLUMN IF NOT EXISTS search_embedding vector(384);
ALTER TABLE items ADD COLUMN IF NOT EXISTS search_embedded_at TIMESTAMPTZ;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_items_search_embedding
  ON items USING hnsw (search_embedding vector_cosine_ops);
