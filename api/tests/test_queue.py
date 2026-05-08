"""Tests for split queue processing (A2 GPU vs external LLM).

Covers:
- A2 GPU queue: transcribe_queued -> transcribing
- Qwen LLM queue: summarize_queued -> summarizing
- Queue progression via cron endpoints (internal token auth)
"""
import pytest

pytestmark = pytest.mark.integration


class TestA2GpuQueue:
    """Tests for transcription queue (A2 GPU - WhisperX)."""

    def test_transcribe_podcasts_cron_queues_items(self, http_client, auth_headers):
        """Transcribe podcasts cron should queue items for A2 GPU processing."""
        r = http_client.post("/admin/cron/transcribe-podcasts?hours=168", headers=auth_headers)
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"

        data = r.json()
        assert data["ok"] is True
        assert "queued" in data
        assert isinstance(data["queued"], int)
        assert data["queue_started"] in (True, False)

    def test_transcribe_videos_cron_queues_items(self, http_client, auth_headers):
        """Transcribe videos cron should queue items for A2 GPU processing."""
        r = http_client.post("/admin/cron/transcribe-videos?hours=168", headers=auth_headers)
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"

        data = r.json()
        assert data["ok"] is True
        assert "queued" in data
        assert isinstance(data["queued"], int)
        assert data["queue_started"] in (True, False)

    def test_transcribe_queue_respects_concurrency_limit(self, http_client, auth_headers):
        """Transcribe cron should handle GPU concurrency (only 1 active at a time)."""
        # Run twice to test idempotency
        r1 = http_client.post("/admin/cron/transcribe-podcasts?hours=24", headers=auth_headers)
        assert r1.status_code == 200
        first_queued = r1.json()["queued"]

        r2 = http_client.post("/admin/cron/transcribe-podcasts?hours=24", headers=auth_headers)
        assert r2.status_code == 200
        second_queued = r2.json()["queued"]

        # Second run should queue 0 or fewer items (already queued items filtered out)
        assert second_queued <= first_queued, (
            f"Second run queued more ({second_queued}) than first ({first_queued}) — "
            "concurrency filter may be broken"
        )


class TestQwenLlmQueue:
    """Tests for summarization queue (external LLM - Qwen)."""

    def test_summarize_articles_cron_queues_items(self, http_client, auth_headers):
        """Summarize articles cron should queue items for LLM processing."""
        r = http_client.post("/admin/cron/summarize-articles?hours=168", headers=auth_headers)
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"

        data = r.json()
        assert data["ok"] is True
        assert "articles_kicked" in data
        assert isinstance(data["articles_kicked"], int)

    def test_summarize_cron_is_idempotent(self, http_client, auth_headers):
        """Running summarize cron twice should not re-queue same items."""
        r1 = http_client.post("/admin/cron/summarize-articles?hours=24", headers=auth_headers)
        assert r1.status_code == 200
        first_kicked = r1.json()["articles_kicked"]

        r2 = http_client.post("/admin/cron/summarize-articles?hours=24", headers=auth_headers)
        assert r2.status_code == 200
        second_kicked = r2.json()["articles_kicked"]

        # Second run should queue equal or fewer items
        assert second_kicked <= first_kicked, (
            f"Second run kicked more ({second_kicked}) than first ({first_kicked}) — "
            "idempotency filter may be broken"
        )

    def test_summarize_handles_empty_queue(self, http_client, auth_headers):
        """Summarize cron should handle case where nothing needs summarization."""
        # Use a very short time window to likely get no results
        r = http_client.post("/admin/cron/summarize-articles?hours=1", headers=auth_headers)
        assert r.status_code == 200

        data = r.json()
        assert data["ok"] is True
        assert "articles_kicked" in data
        # Should be 0 or some number, not an error
        assert isinstance(data["articles_kicked"], int)


class TestQueueEndpointsAuth:
    """Tests for queue endpoint authentication."""

    def test_queue_endpoints_require_auth(self, http_client):
        """Queue endpoints should require authentication."""
        # Without auth headers
        r = http_client.post("/admin/cron/transcribe-podcasts?hours=24")
        assert r.status_code == 401

        r = http_client.post("/admin/cron/summarize-articles?hours=24")
        assert r.status_code == 401

        r = http_client.post("/admin/queue/restart")
        assert r.status_code == 401

        # With wrong token
        bad_headers = {"x-stroom-internal-token": "invalid-token"}
        r = http_client.post("/admin/cron/nightly", headers=bad_headers)
        assert r.status_code == 401
