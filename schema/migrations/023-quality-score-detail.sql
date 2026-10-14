-- Migration 023: uitleg bij de auto-score.
--
-- De decision-scorer (services/decision_scorer.py, nimble op de A2) geeft geen
-- tekstuele uitleg, wel deelscores (quality/interest/clickbait), de
-- kansverdeling per niveau en confidence. Die komen hier, zodat de UI kan
-- tonen waarom een item zijn score kreeg. {"error": ...} = dit item kon niet
-- gescoord worden; de batch slaat het daarna over.

ALTER TABLE items ADD COLUMN IF NOT EXISTS quality_score_detail JSONB;
