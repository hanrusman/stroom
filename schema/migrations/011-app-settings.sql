-- App-wide settings (key/value).
CREATE TABLE IF NOT EXISTS app_settings (
  key        text PRIMARY KEY,
  value      jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO app_settings (key, value) VALUES
  ('model_defaults', '{"expand":"qwen","distill":"qwen","digest":"opus"}'::jsonb)
ON CONFLICT (key) DO NOTHING;
