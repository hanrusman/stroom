-- Small, persistent queue for the text-to-podcast test page.
CREATE TABLE IF NOT EXISTS podcast_tests (
    id uuid PRIMARY KEY,
    text text NOT NULL CHECK (length(text) BETWEEN 1 AND 4000),
    text_hash text NOT NULL,
    model text NOT NULL CHECK (model IN ('omnivoice', 'kittentts', 'cosyvoice')),
    voice text NOT NULL DEFAULT 'default',
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'rendering', 'ready', 'failed')),
    message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    elapsed_seconds double precision,
    audio_bytes bigint
);
CREATE INDEX IF NOT EXISTS podcast_tests_recent ON podcast_tests(created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS podcast_tests_pending
    ON podcast_tests(text_hash, model, voice) WHERE status IN ('queued', 'rendering');
