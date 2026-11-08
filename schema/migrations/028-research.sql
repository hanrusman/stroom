-- Dossiers: brede onderzoeksvragen over het hele archief (services/research_service.py).
-- Eén run = één doorloop van plan → recall → screening → extractie → schrijven
-- → kritiek → herziening. Elke stap schrijft zijn resultaat weg, zodat een run
-- na een herstart verder kan waar hij was. Een vernieuwing (parent_id) hergebruikt
-- plan, screening en extracties van de vorige run.
CREATE TABLE IF NOT EXISTS research_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    parent_id uuid REFERENCES research_runs(id) ON DELETE SET NULL,
    question text NOT NULL,
    title text,
    -- queued | planning | recall | screening | extracting | deepening | writing
    -- | critiquing | revising | done | failed | cancelled
    status text NOT NULL DEFAULT 'queued',
    stage_detail text,
    plan jsonb,          -- {title, question, aspects[], queries[], include, exclude, model}
    options jsonb,
    progress jsonb,      -- {stage, done, total, ...}
    stats jsonb,         -- {llm_calls, llm_failures, by_model, secs}
    draft text,          -- eerste versie van het schrijfmodel
    critique jsonb,      -- {verdict, issues[]}
    report text,         -- herziene versie (markdown met [S12]-verwijzingen)
    sources jsonb,       -- [{ref, item_id, title, source, format, date, url, relevance, findings[], cited}]
    models jsonb,        -- welk model elke stap werkelijk deed
    followups jsonb NOT NULL DEFAULT '[]',  -- [{question, answer, model, at}]
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS research_runs_created ON research_runs(created_at DESC);

CREATE TABLE IF NOT EXISTS research_candidates (
    run_id uuid NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    recall_score real NOT NULL DEFAULT 0,
    queries text[] NOT NULL DEFAULT '{}',
    screen_score smallint,   -- 0-3, NULL = nog niet gescreend
    round smallint NOT NULL DEFAULT 0,  -- 0 = eerste zoekronde, 1 = verdieping
    PRIMARY KEY (run_id, item_id)
);

CREATE TABLE IF NOT EXISTS research_findings (
    run_id uuid NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    relevance smallint NOT NULL DEFAULT 0,
    findings jsonb NOT NULL DEFAULT '[]',
    model text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, item_id)
);
