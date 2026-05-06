-- Store questions asked about items with their answers
CREATE TABLE IF NOT EXISTS item_questions (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id        uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question       text NOT NULL,
    answer         text NOT NULL,
    model          text,
    sources_used   text[],  -- which sources were used: transcript, description, summary, lessons
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_item_questions_item
    ON item_questions(item_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_item_questions_user
    ON item_questions(user_id, created_at DESC);
