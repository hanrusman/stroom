"""Unit tests for pure helper functions in main.py.

These don't touch the DB or HTTP — just verify input → output behaviour.
"""
import sys
import pytest

# main.py lives at /app/main.py inside the container; pytest runs with cwd=/app
sys.path.insert(0, "/app")

from main import _feed_media_url, _feed_thumb_url, _feed_first_text  # noqa: E402

pytestmark = pytest.mark.unit


class TestFeedMediaUrl:
    def test_prefers_enclosure(self):
        entry = {
            "enclosures": [{"url": "https://cdn.example.com/audio.mp3", "type": "audio/mpeg"}],
            "media_content": [{"url": "https://other.example.com/x.mp3"}],
            "link": "https://example.com/article",
        }
        assert _feed_media_url(entry) == "https://cdn.example.com/audio.mp3"

    def test_falls_back_to_media_content(self):
        entry = {
            "media_content": [{"url": "https://example.com/audio.mp3"}],
            "link": "https://example.com/article",
        }
        assert _feed_media_url(entry) == "https://example.com/audio.mp3"

    def test_falls_back_to_link_when_no_media(self):
        entry = {"link": "https://example.com/article"}
        assert _feed_media_url(entry) == "https://example.com/article"

    def test_returns_none_when_empty(self):
        # empty dict has no link → .get returns None
        assert _feed_media_url({}) is None

    def test_skips_enclosure_without_url(self):
        entry = {
            "enclosures": [{"type": "audio/mpeg"}],  # no url
            "media_content": [{"url": "https://example.com/m.mp3"}],
        }
        assert _feed_media_url(entry) == "https://example.com/m.mp3"


class TestFeedThumbUrl:
    def test_returns_first_thumbnail(self):
        entry = {"media_thumbnail": [{"url": "https://example.com/thumb.jpg"}]}
        assert _feed_thumb_url(entry) == "https://example.com/thumb.jpg"

    def test_returns_none_when_no_thumbnail(self):
        assert _feed_thumb_url({}) is None


class TestFeedFirstText:
    def test_returns_first_present_field(self):
        entry = {"summary": "short", "description": "longer text"}
        # _feed_first_text(entry, "summary", "description") should return summary
        assert _feed_first_text(entry, "summary", "description") == "short"

    def test_falls_back_to_next_field(self):
        entry = {"description": "fallback"}
        assert _feed_first_text(entry, "summary", "description") == "fallback"

    def test_returns_none_when_no_field_present(self):
        assert _feed_first_text({}, "summary", "description") is None
