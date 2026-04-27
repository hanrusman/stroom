"""Integration tests for POST /admin/cron/nightly.

These run against the live stroom-api inside its container. They do NOT
isolate state — running them does perform real feed-refreshes and may queue
real items. The tests are designed to be safe to re-run: idempotent calls
end with `candidates_queued == 0` once the queue is drained.
"""
import pytest

pytestmark = pytest.mark.integration


def test_cron_requires_internal_token(http_client):
    r = http_client.post("/admin/cron/nightly")
    assert r.status_code == 401


def test_cron_rejects_wrong_token(http_client):
    r = http_client.post(
        "/admin/cron/nightly",
        headers={"x-stroom-internal-token": "definitely-not-the-token"},
    )
    assert r.status_code == 401


def test_cron_returns_expected_shape(http_client, auth_headers):
    r = http_client.post("/admin/cron/nightly", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("ok", "sources_refreshed", "refresh_errors",
                "new_items_inserted", "candidates_queued", "queue_started"):
        assert key in body, f"missing key: {key}"
    assert body["ok"] is True
    assert isinstance(body["sources_refreshed"], int)
    assert isinstance(body["candidates_queued"], int)
    assert body["sources_refreshed"] >= 0
    assert body["candidates_queued"] >= 0


def test_cron_second_run_does_not_requeue_existing(http_client, auth_headers):
    """Items already in queued/transcribing/summarizing must NOT be re-queued.

    Note: between the two runs new items can legitimately arrive in feeds, so
    we don't assert candidates_queued == 0 — we assert that the *count* shrinks
    or stays equal, never grows because we re-queued things we shouldn't have."""
    r1 = http_client.post("/admin/cron/nightly", headers=auth_headers)
    assert r1.status_code == 200, r1.text
    first = r1.json()["candidates_queued"]

    r2 = http_client.post("/admin/cron/nightly", headers=auth_headers)
    assert r2.status_code == 200, r2.text
    second = r2.json()["candidates_queued"]

    # Real-world feeds can deliver new items between runs. Allow a small drift
    # but flag if the second run re-queues a substantial chunk (> 50%).
    if first > 0:
        assert second <= first, (
            f"Second run queued more items ({second}) than first ({first}) — "
            "the NOT IN (queued, transcribing, summarizing) filter is broken"
        )


def test_cron_refresh_errors_are_bounded(http_client, auth_headers):
    """A single broken feed must not cause the whole cron to fail; per-source
    errors are counted and reported but the overall response is still 200."""
    r = http_client.post("/admin/cron/nightly", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["refresh_errors"] <= body["sources_refreshed"], (
        "More errors than sources processed — accounting is broken"
    )
