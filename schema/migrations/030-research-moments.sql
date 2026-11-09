-- Momenten per bron in een dossier: waar in de aflevering een bevinding
-- gezegd wordt (voor terugluisteren in de speler). Cache per run, sleutel =
-- item_id, waarde = lijst per bevinding: {"t": seconden, "exact": bool} of null.
-- Zie api/services/research_moments.py. Idempotent.
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS moments jsonb NOT NULL DEFAULT '{}'::jsonb;
