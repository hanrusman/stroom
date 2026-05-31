-- Migration 021: heartbeat-based liveness voor stuck-detection.
--
-- Vervangt de deadline-gebaseerde queued_at-check in _cron_unstuck door een
-- liveness-signaal dat samenvat-agent elke 30s update tijdens lange transcribes.
-- Een item geldt pas als 'stuck' wanneer er CRON_STUCK_MIN minuten geen progress
-- is. Een 4-uurs Acquired-podcast die normaal door-pingt overleeft moeiteloos,
-- maar een gecrashte job wordt binnen 5 min gedetecteerd.
--
-- Geen index: items-tabel is <10k rijen, en de cron-query is al gefilterd op
-- processing_status. Sequential scan is goedkoper dan het bijhouden van een
-- index op een veld dat elke 30s update.

ALTER TABLE items ADD COLUMN IF NOT EXISTS last_progress_at TIMESTAMPTZ;

-- Backfill: geef items die op het moment van migration in-flight zijn een
-- 'alive' timestamp. Zonder dit zou de nieuwe CRON_STUCK_MIN=5 ze meteen
-- naar failed zetten omdat ze nog geen heartbeat hebben gehad. Eenmalig.
UPDATE items SET last_progress_at = now()
WHERE last_progress_at IS NULL
  AND processing_status IN (
    'queued'::processing_status,
    'transcribe_queued'::processing_status,
    'summarize_queued'::processing_status,
    'transcribing'::processing_status,
    'summarizing'::processing_status
  );
