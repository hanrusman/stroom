-- 016: voeg queued_at toe voor digest unstuck mechanisme
-- Als een worker crasht voordat generation_started_at kan zetten,
-- kunnen we via queued_at detecteren of een rij te lang in de wachtrij staat.

ALTER TABLE topic_digests ADD COLUMN IF NOT EXISTS queued_at TIMESTAMPTZ;
ALTER TABLE lessons_digests ADD COLUMN IF NOT EXISTS queued_at TIMESTAMPTZ;
