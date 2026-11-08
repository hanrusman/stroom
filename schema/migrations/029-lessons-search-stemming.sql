-- Migration 029: lessons doorzoekbaar met NL+EN-stemming.
--
-- GET /internal/lessons/search (Okavango's search_stroom_lessons) deed een
-- ILIKE op de hele vraag, dus 'inkoop software open standaarden' vond alleen
-- lessen waarin die vier woorden letterlijk achter elkaar stonden. Nu krijgen
-- lessons dezelfde soort tsvector als items (migratie 024): elk veld in
-- 'dutch' en 'english', samengevoegd met behoud van woordposities
-- (stroom_tsv_merge uit 024), en de vraag gaat door services/search_query.
-- Gewichten: title A, body B, expansion C. Vereist migratie 024.
--
-- Geen GENERATED-kolom: die herschrijft de tabel onder een exclusieve lock,
-- en lokaal duurde dat voor 47k lessen met elk een expansion van ~4500 tekens
-- bijna 2 minuten. Daarom net als 024: gewone kolom + trigger, backfill in
-- batches met een COMMIT per batch en de index CONCURRENTLY. Lessen zonder
-- search_tsv (nog niet gebackfilld) worden tijdens het draaien even niet
-- gevonden.
--
-- Draai dit bestand met psql buiten een transactie (geen -1/--single-
-- transaction): de DO-backfill commit zelf en CREATE INDEX CONCURRENTLY
-- mag niet in een transactie.

CREATE OR REPLACE FUNCTION stroom_lessons_tsv(title text, body text, expansion text)
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT setweight(stroom_tsv_merge(to_tsvector('dutch', coalesce(title, '')),
                                    to_tsvector('english', coalesce(title, ''))), 'A')
      || setweight(stroom_tsv_merge(to_tsvector('dutch', coalesce(body, '')),
                                    to_tsvector('english', coalesce(body, ''))), 'B')
      || setweight(stroom_tsv_merge(to_tsvector('dutch', coalesce(expansion, '')),
                                    to_tsvector('english', coalesce(expansion, ''))), 'C')
$$;

ALTER TABLE lessons ADD COLUMN IF NOT EXISTS search_tsv tsvector;

CREATE OR REPLACE FUNCTION lessons_search_tsv_trg() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.search_tsv := stroom_lessons_tsv(NEW.title, NEW.body, NEW.expansion);
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS lessons_search_tsv ON lessons;
CREATE TRIGGER lessons_search_tsv
  BEFORE INSERT OR UPDATE OF title, body, expansion ON lessons
  FOR EACH ROW EXECUTE FUNCTION lessons_search_tsv_trg();

DO $$
DECLARE n int;
BEGIN
  LOOP
    UPDATE lessons SET search_tsv = stroom_lessons_tsv(title, body, expansion)
    WHERE id IN (SELECT id FROM lessons WHERE search_tsv IS NULL LIMIT 500);
    GET DIAGNOSTICS n = ROW_COUNT;
    COMMIT;
    EXIT WHEN n = 0;
  END LOOP;
END $$;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lessons_search_tsv
  ON lessons USING gin (search_tsv);
