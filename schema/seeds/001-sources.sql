-- Starter sources for Stroom.
-- Replace the TODO rows with your own feeds before running the pollers.

-- TODO: replace the playlist ID with your actual unlisted "Stroom" playlist.
INSERT INTO sources (kind, name, url, poll_interval_min) VALUES
  ('youtube', 'Stroom-inbox', 'https://www.youtube.com/playlist?list=PLREPLACEME', 30);

-- RSS feeds — one to start with. Add more later.
INSERT INTO sources (kind, name, url, poll_interval_min) VALUES
  ('rss', 'Craig Mod', 'https://craigmod.com/index.xml', 240);

-- Podcast feeds — one to start with. Add more later.
INSERT INTO sources (kind, name, url, poll_interval_min) VALUES
  ('podcast', 'Huberman Lab', 'https://feeds.megaphone.fm/hubermanlab', 60);
