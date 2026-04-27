-- Tweede batch sources (verified URLs only).
-- Idempotent: ON CONFLICT DO NOTHING op sources.url is er niet, dus we matchen op naam.

BEGIN;

INSERT INTO sources (kind, name, url, poll_interval_min) VALUES
  ('rss',     'The Pragmatic Engineer', 'https://newsletter.pragmaticengineer.com/feed',         180),
  ('rss',     'Tweakers',                'https://feeds.feedburner.com/tweakers/mixed',           60),
  ('rss',     'Wired',                   'https://www.wired.com/feed/rss',                        120),
  ('rss',     'Hacker News Top',         'https://hnrss.org/frontpage',                           60),
  ('rss',     'Stratechery',             'https://stratechery.com/feed/',                         360),
  ('rss',     'NU.nl',                   'https://www.nu.nl/rss/Algemeen',                        30),
  ('rss',     'RTL Nieuws',              'https://www.rtlnieuws.nl/rss.xml',                      60),
  ('rss',     'CNN International',       'http://rss.cnn.com/rss/edition.rss',                    60),
  ('rss',     'Wielerflits',             'https://www.wielerflits.nl/feed/',                      60),
  ('rss',     'Motorsport.com',          'https://www.motorsport.com/rss/all/news/',              60),
  ('rss',     'HR Tech Feed',            'https://hrtechfeed.com/feed/',                          240),
  ('podcast', 'WorkLife with Adam Grant','https://feeds.feedburner.com/WorkLifeWithAdamGrant',    240)
ON CONFLICT DO NOTHING;

INSERT INTO source_topics (source_id, topic_id)
SELECT s.id, t.id FROM sources s, topics t
WHERE (s.name='The Pragmatic Engineer'  AND t.slug IN ('ai','tech'))
   OR (s.name='Tweakers'                AND t.slug='tech')
   OR (s.name='Wired'                   AND t.slug='tech')
   OR (s.name='Hacker News Top'         AND t.slug='tech')
   OR (s.name='Stratechery'             AND t.slug='tech')
   OR (s.name='NU.nl'                   AND t.slug='nl-news')
   OR (s.name='RTL Nieuws'              AND t.slug='nl-news')
   OR (s.name='CNN International'       AND t.slug='international-news')
   OR (s.name='Wielerflits'             AND t.slug='sports')
   OR (s.name='Motorsport.com'          AND t.slug='sports')
   OR (s.name='HR Tech Feed'            AND t.slug='hr-tech')
   OR (s.name='WorkLife with Adam Grant' AND t.slug='misc')
ON CONFLICT DO NOTHING;

COMMIT;
