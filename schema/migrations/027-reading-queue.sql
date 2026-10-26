-- Personal reading/listening queue, independent of bookmarks and processing jobs.
CREATE TABLE IF NOT EXISTS reading_queue (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    position bigint GENERATED ALWAYS AS IDENTITY,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, item_id)
);
CREATE INDEX IF NOT EXISTS reading_queue_order ON reading_queue(user_id, position);
-- Item status is shared by the existing application. Archive consistently removes
-- it from every personal queue, including archives made by background jobs.
CREATE OR REPLACE FUNCTION remove_archived_reading_queue() RETURNS trigger AS $$
BEGIN
    IF NEW.status::text = 'archived' THEN
        DELETE FROM reading_queue WHERE item_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS reading_queue_archive ON items;
CREATE TRIGGER reading_queue_archive AFTER UPDATE OF status ON items
    FOR EACH ROW EXECUTE FUNCTION remove_archived_reading_queue();
