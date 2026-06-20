"""Integration tests for POST /admin/cron/nightly.

These run against the live stroom-api inside its container. They do NOT
isolate state — running them does perform real feed-refreshes and may queue
real items. The tests are designed to be safe to re-run: idempotent calls
end with `candidates_queued == 0` once the queue is drained.

Opmerking: een test die monkey-patch doet op _refresh_one om de per-bron
watchdog te valideren kan niet zonder een aparte pytest-runner in het
container-proces (en dat raakt andere tests). Daarom valideren we de watchdog
apart in de live-verificatie (zie plan robust-wiggling-beacon.md, stap 7)
door een echte nightly curl te triggeren en te kijken dat ie binnen
budget terugkomt. Hier beperken we ons tot response-shape + health-check.
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
    # Huidige response shape (post 2026-04 refactor): per-content_kind velden,
    # geen generieke candidates_queued meer.
    for key in ("ok", "sources_refreshed", "refresh_errors",
                "new_items_inserted", "podcasts_queued", "videos_queued",
                "articles_summarize_kicked", "digests_started"):
        assert key in body, f"missing key: {key}"
    assert body["ok"] is True
    assert isinstance(body["sources_refreshed"], int)
    for k in ("podcasts_queued", "videos_queued",
              "articles_summarize_kicked", "digests_started"):
        assert isinstance(body[k], int), f"{k} is niet int: {body[k]!r}"
    assert body["sources_refreshed"] >= 0


def test_cron_second_run_does_not_requeue_existing(http_client, auth_headers):
    """Items already in queued/transcribing/summarizing must NOT be re-queued.

    We kijken naar articles_summarize_kicked (was candidates_queued): mag niet
    groeien tussen twee runs omdat de NOT IN (queued, …) filter dat blokkeert.
    Real-world feeds kunnen nieuwe items brengen dus we eisen geen ==0, alleen
    dat de tweede run niet méér kicked dan de eerste (modulo feed-noise).
    """
    r1 = http_client.post("/admin/cron/nightly", headers=auth_headers)
    assert r1.status_code == 200, r1.text
    first = r1.json()["articles_summarize_kicked"]

    r2 = http_client.post("/admin/cron/nightly", headers=auth_headers)
    assert r2.status_code == 200, r2.text
    second = r2.json()["articles_summarize_kicked"]

    if first > 0:
        assert second <= first, (
            f"Second run kicked more items ({second}) than first ({first}) — "
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


def test_cron_last_result_returns_snapshot(http_client, auth_headers):
    """/admin/cron/last-result is de monitoring-endpoint die externe monitors
    kunnen pollen. Shape is vastgelegd zodat Netdata/dashboards niet breken
    als we ooit velden hernoemen. De health-assertions zijn de regression
    guards tegen het 2026-06-20 incident."""
    r = http_client.get("/admin/cron/last-result", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("ok", "now", "sources_total", "sources_over_24h",
                "oldest_last_polled_seconds", "pool", "processing", "sources"):
        assert key in body, f"missing key: {key}"
    assert body["ok"] is True
    assert isinstance(body["sources"], list)
    assert isinstance(body["pool"], dict)
    assert isinstance(body["processing"], dict)
    # Health assertion: als deze faalt is het systeem écht verstopt. De
    # self-clean in _cron_unstuck ruimt dit op; deze test vangt het geval
    # dat iemand per ongeluk de cleanup verwijdert.
    assert body["pool"].get("idle in transaction", 0) <= 2, (
        f"Meer dan 2 idle-in-transaction sessies: {body['pool']}. "
        f"Dat is precies het patroon dat 2026-06-20 de nightly liet hangen."
    )
