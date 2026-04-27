-- Huygens seed: 9 topics + 6 starter sources + topic mapping.
-- Idempotent via ON CONFLICT.

BEGIN;

INSERT INTO topics (slug, name) VALUES
  ('ai',                 'AI'),
  ('tech',               'Tech'),
  ('nl-news',            'NL News'),
  ('politics-nl',        'Politics NL'),
  ('international-news', 'International News'),
  ('health',             'Health'),
  ('sports',             'Sports'),
  ('hr-tech',            'HR-tech'),
  ('misc',               'Misc')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO sources (kind, name, url, poll_interval_min) VALUES
  ('rss',     'Simon Willison''s Weblog', 'https://simonwillison.net/atom/everything/',                         60),
  ('podcast', 'Latent Space',              'https://api.substack.com/feed/podcast/1084089.rss',                  240),
  ('youtube', 'Nate B Jones',              'https://www.youtube.com/feeds/videos.xml?channel_id=UC0C-17n9iuUQPylguM1d-lQ', 240),
  ('rss',     'NOS Nieuws',                'https://feeds.nos.nl/nosnieuwsalgemeen',                            30),
  ('podcast', 'Hard Fork',                 'https://feeds.simplecast.com/l2i9YnTd',                             240),
  ('rss',     'Josh Bersin',               'https://joshbersin.com/feed/',                                      240)
ON CONFLICT DO NOTHING;

INSERT INTO source_topics (source_id, topic_id)
SELECT s.id, t.id FROM sources s, topics t
WHERE (s.name='Huberman Lab'              AND t.slug='health')
   OR (s.name='Simon Willison''s Weblog'  AND t.slug='ai')
   OR (s.name='Latent Space'              AND t.slug='ai')
   OR (s.name='Nate B Jones'              AND t.slug='ai')
   OR (s.name='NOS Nieuws'                AND t.slug='nl-news')
   OR (s.name='Hard Fork'                 AND t.slug='tech')
   OR (s.name='Josh Bersin'               AND t.slug='hr-tech')
ON CONFLICT DO NOTHING;

COMMIT;
