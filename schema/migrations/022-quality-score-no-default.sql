-- Migration 022: quality_score zonder DEFAULT 5.
--
-- 017 gaf quality_score DEFAULT 5 en backfillde NULL -> 5. Daardoor is een
-- nooit-gescoord item niet te onderscheiden van een echte neutrale score.
-- Items die hun summary via de transcribe-callback kregen (podcasts/YouTube
-- via samenvat-agent) werden nooit gescoord en stonden stil op 5 — op
-- 2026-10-02 waren dat 3309 van de 5846 items van de laatste 60 dagen.
--
-- Ranking gebruikt al COALESCE(quality_score, 5), dus NULL gedraagt zich daar
-- identiek. /admin/quality-backfill met only_null=true pikt ze daarna op.

ALTER TABLE items ALTER COLUMN quality_score DROP DEFAULT;

-- Nooit-gescoord = default-5 zonder reason én zonder updated_at. Echte scores
-- hebben altijd quality_score_updated_at gezet: worker/backfill met reason
-- 'auto', handmatige correcties met hun eigen reason.
UPDATE items SET quality_score = NULL
WHERE quality_score = 5
  AND quality_score_reason IS NULL
  AND quality_score_updated_at IS NULL;
