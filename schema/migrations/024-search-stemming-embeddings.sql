-- Migration 024: zoeken met stemming + semantische zoekvectoren.
--
-- 1. Stemming. search_tsv gebruikte config 'simple' (geen stemming), dus
--    'verkiezing' vond 'verkiezingen' niet. Op 2026-10-12 vond 'verkiezing'
--    met 'dutch' 414 items op alleen titel+samenvatting, tegen 135 met 'simple'
--    op alles. Content is gemengd NL/EN en er is geen taalkolom, dus we
--    indexeren elk veld in beide talen.
--
--    stroom_tsv_merge voegt de NL- en EN-vector van een veld samen met behoud
--    van de woordposities. Met `||` zouden de Engelse posities achter de hele
--    Nederlandse vector komen en in lange transcripts vastlopen op het
--    maximum (16383), waardoor Engelse frases daar niet meer matchen.
--
--    stroom_tsquery() zet de zoekvraag om: de positieve termen in NL OF EN,
--    de uitsluitingen (-woord, -"frase") in NL EN EN. Anders zou de andere
--    taaltak een uitgesloten item alsnog doorlaten.
--
--    Alles herberekenen kost ~16 min CPU (5%-steekproef 2026-10-12: 49 s; de
--    merge verdubbelt de kosten t.o.v. `||`). Een nieuwe GENERATED-kolom zou de
--    tabel al die tijd exclusief locken en de API en de transcribe-callbacks
--    laten vastlopen. Daarom: gewone kolom + trigger, backfill in batches met
--    een COMMIT per batch, index CONCURRENTLY en pas dan een korte swap.
--    search_tsv stond niet in eerdere migraties (was handmatig aangemaakt als
--    GENERATED-kolom); na de swap is hij een gewone kolom die de trigger bijhoudt.
--
--    Draai dit bestand met psql buiten een transactie (geen -1/--single-
--    transaction): de DO-backfill commit zelf en CREATE INDEX CONCURRENTLY
--    mag niet in een transactie.
--
-- 2. Semantisch zoeken. search_embedding = multilingual-e5-small (384 dim) van
--    stroom_search_passage(), gemaakt door de stroom-embed sidecar.
--    services/search_index.py vult hem in de achtergrond. De trigger verhoogt
--    search_source_version zodra de passage verandert (titel, summary,
--    description of transcript-begin); de vector is actueel zolang
--    search_embedded_version daaraan gelijk is.

CREATE OR REPLACE FUNCTION stroom_tsquery_excl(q text) RETURNS tsquery
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN n <> '' AND numnode(x) > 0 THEN x END
  FROM (SELECT n, CASE WHEN n <> '' THEN websearch_to_tsquery('dutch', n)
                                      || websearch_to_tsquery('english', n) END AS x
        FROM (SELECT coalesce(string_agg(m[2], ' or '), '') AS n
              FROM regexp_matches(q, '(^|\s)-("[^"]*"|[^\s"]+)', 'g') AS m) neg) t
$$;

CREATE OR REPLACE FUNCTION stroom_tsquery(q text) RETURNS tsquery
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN ex IS NULL THEN pos ELSE pos && !! ex END
  FROM (SELECT websearch_to_tsquery('dutch', p) || websearch_to_tsquery('english', p) AS pos,
               stroom_tsquery_excl(q) AS ex
        FROM (SELECT regexp_replace(q, '(^|\s)-("[^"]*"|[^\s"]+)', '\1', 'g') AS p) s) t
$$;

CREATE OR REPLACE FUNCTION stroom_tsv_merge(a tsvector, b tsvector) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT coalesce(string_agg(
           '''' || replace(replace(lexeme, '\', '\\'), '''', '''''') || ''':' || pos, ' '
         )::tsvector, ''::tsvector)
  FROM (SELECT lexeme, array_to_string((array_agg(DISTINCT p ORDER BY p))[1:256], ',') AS pos
        FROM (SELECT u.lexeme, unnest(u.positions) AS p
              FROM (SELECT * FROM unnest(a) UNION ALL SELECT * FROM unnest(b)) u) x
        GROUP BY lexeme) y
$$;

CREATE OR REPLACE FUNCTION stroom_search_tsv(title text, summary text,
                                             transcript text, description text)
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT setweight(stroom_tsv_merge(to_tsvector('dutch', coalesce(title, '')),
                                    to_tsvector('english', coalesce(title, ''))), 'A')
      || setweight(stroom_tsv_merge(to_tsvector('dutch', coalesce(summary, '')),
                                    to_tsvector('english', coalesce(summary, ''))), 'B')
      || setweight(stroom_tsv_merge(to_tsvector('dutch', coalesce(transcript, '')),
                                    to_tsvector('english', coalesce(transcript, ''))), 'C')
      || setweight(stroom_tsv_merge(to_tsvector('dutch', coalesce(description, '')),
                                    to_tsvector('english', coalesce(description, ''))), 'D')
$$;

-- De tekst die embed wordt. e5 truncatet zelf op 512 tokens, dus meer dan
-- ~2000 tekens van de body heeft geen zin.
CREATE OR REPLACE FUNCTION stroom_search_passage(title text, summary text,
                                                 description text, transcript text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT btrim(coalesce(title, '') || E'\n\n' ||
               left(coalesce(nullif(summary, ''), nullif(description, ''),
                             left(transcript, 2000), ''), 2000), E' \n')
$$;

ALTER TABLE items ADD COLUMN IF NOT EXISTS search_tsv_stem tsvector;
ALTER TABLE items ADD COLUMN IF NOT EXISTS search_embedding vector(384);
ALTER TABLE items ADD COLUMN IF NOT EXISTS search_source_version INT NOT NULL DEFAULT 0;
ALTER TABLE items ADD COLUMN IF NOT EXISTS search_embedded_version INT;

CREATE OR REPLACE FUNCTION items_search_tsv_trg() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.search_tsv_stem := stroom_search_tsv(NEW.title, NEW.summary,
                                           NEW.transcript, NEW.description);
  IF TG_OP = 'UPDATE' AND
     stroom_search_passage(NEW.title, NEW.summary, NEW.description, NEW.transcript)
       IS DISTINCT FROM
     stroom_search_passage(OLD.title, OLD.summary, OLD.description, OLD.transcript) THEN
    NEW.search_source_version := OLD.search_source_version + 1;
  END IF;
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
  IF TG_OP = 'UPDATE' AND
     stroom_search_passage(NEW.title, NEW.summary, NEW.description, NEW.transcript)
       IS DISTINCT FROM
     stroom_search_passage(OLD.title, OLD.summary, OLD.description, OLD.transcript) THEN
    NEW.search_source_version := OLD.search_source_version + 1;
  END IF;
  RETURN NEW;
END $$;
COMMIT;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_items_search_embedding
  ON items USING hnsw (search_embedding vector_cosine_ops);
