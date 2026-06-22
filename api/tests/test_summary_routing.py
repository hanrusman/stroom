"""Unit tests voor de samenvatting-routing helper.

Verifieert dat `_pick_summary_route` lange transcripties (podcast/video > 10 min,
of >20k chars als duration onbekend) naar `cloud-kimi` routeert met een
gestructureerde prompt, en korte content op `stroom-bulk` met de bestaande
12k-trim laat.
"""
import sys
import pytest

sys.path.insert(0, "/app")

from main import (  # noqa: E402
    _pick_summary_route,
    _SHORT_SUMMARY_SYSTEM,
    _LONG_SUMMARY_SYSTEM,
    _ARTICLE_SUMMARY_SYSTEM,
    LONG_TRANSCRIPT_DURATION_SECONDS,
    LONG_TRANSCRIPT_CHAR_FALLBACK,
    LONG_TRANSCRIPT_MAX_CHARS,
    LONG_TRANSCRIPT_MODEL,
)

pytestmark = pytest.mark.unit


class TestPickSummaryRoute:
    def test_short_text_and_short_duration_uses_bulk(self):
        """Klassiek artikel: stroom-bulk + 12k trim + korte prompt."""
        route = _pick_summary_route("een korte tekst van een paar regels.", duration_seconds=120)
        assert route["model"] == "stroom-bulk"
        assert route["is_long"] is False
        assert route["timeout"] == 180.0
        assert route["system_prompt"] == _SHORT_SUMMARY_SYSTEM
        assert len(route["cleaned"]) <= 12000

    def test_no_duration_short_text_uses_bulk(self):
        """Articles hebben geen duration_seconds — moet defaulten naar bulk."""
        route = _pick_summary_route("klein artikel", duration_seconds=None)
        assert route["model"] == "stroom-bulk"
        assert route["is_long"] is False

    def test_long_duration_routes_to_cloud_kimi(self):
        """3-uur podcast (10800s) → cloud-kimi met long-prompt."""
        route = _pick_summary_route("zelfs als de tekst kort is, lange duration → long",
                                    duration_seconds=10800)
        assert route["model"] == LONG_TRANSCRIPT_MODEL
        assert route["is_long"] is True
        assert route["timeout"] == 600.0
        assert route["system_prompt"] == _LONG_SUMMARY_SYSTEM

    def test_duration_at_boundary(self):
        """Exact 600s = grens, moet long zijn (>=)."""
        route = _pick_summary_route("text", duration_seconds=LONG_TRANSCRIPT_DURATION_SECONDS)
        assert route["is_long"] is True

    def test_duration_just_below_boundary(self):
        """599s = nog short."""
        route = _pick_summary_route("text", duration_seconds=LONG_TRANSCRIPT_DURATION_SECONDS - 1)
        assert route["is_long"] is False

    def test_char_fallback_when_duration_unknown(self):
        """Artikel zonder duration maar zeer lang → cloud-kimi (char-fallback)."""
        long_text = "x " * (LONG_TRANSCRIPT_CHAR_FALLBACK)  # 2 chars per iter
        route = _pick_summary_route(long_text, duration_seconds=None)
        assert route["is_long"] is True
        assert route["model"] == LONG_TRANSCRIPT_MODEL

    def test_char_fallback_at_exact_threshold(self):
        """Exact threshold chars → long (>=)."""
        text = "a" * LONG_TRANSCRIPT_CHAR_FALLBACK
        route = _pick_summary_route(text, duration_seconds=None)
        assert route["is_long"] is True

    def test_short_duration_with_long_text_still_long(self):
        """Korte duration maar mega-lange transcript-string (bv corrupt duration meta)
        → moet veilig naar cloud-kimi om geen context-truncatie te krijgen."""
        long_text = "y" * (LONG_TRANSCRIPT_CHAR_FALLBACK + 100)
        route = _pick_summary_route(long_text, duration_seconds=30)
        assert route["is_long"] is True

    def test_long_text_truncated_to_max_chars(self):
        """Mega-mega-transcript wordt afgekapt op LONG_TRANSCRIPT_MAX_CHARS."""
        huge = "z" * (LONG_TRANSCRIPT_MAX_CHARS * 2)
        route = _pick_summary_route(huge, duration_seconds=10800)
        assert len(route["cleaned"]) == LONG_TRANSCRIPT_MAX_CHARS

    def test_whitespace_collapsed(self):
        """Multiple whitespace wordt geknald naar één spatie (NLP-cleanup)."""
        msgy = "hallo\n\n\nwereld\t\twat\n  extra spaties"
        route = _pick_summary_route(msgy, duration_seconds=60)
        assert "  " not in route["cleaned"]
        assert "\n" not in route["cleaned"]
        assert "\t" not in route["cleaned"]

    def test_zero_duration_treated_as_unknown(self):
        """duration=0 (zoals 'onbekend' bij sommige feeds) moet niet als 'long' tellen
        op basis van duration alleen — alleen char-fallback bepaalt."""
        route = _pick_summary_route("kort", duration_seconds=0)
        assert route["is_long"] is False


class TestArticleRoute:
    def test_article_uses_structured_prompt_on_bulk(self):
        """Normaal tekstartikel: eigen gestructureerde prompt op stroom-bulk,
        niet de 3-zinnen short-prompt van de transcript-routing."""
        route = _pick_summary_route("een normaal artikel " * 50, duration_seconds=None,
                                    is_article=True)
        assert route["model"] == "stroom-bulk"
        assert route["is_long"] is False
        assert route["system_prompt"] == _ARTICLE_SUMMARY_SYSTEM
        assert route["timeout"] == 180.0
        assert len(route["cleaned"]) <= 12000

    def test_article_ignores_duration(self):
        """Artikelen hebben geen betekenisvolle duration; een toevallige hoge
        duration mag de artikel-route niet naar de long-transcript-prompt duwen."""
        route = _pick_summary_route("kort artikel", duration_seconds=10800, is_article=True)
        assert route["is_long"] is False
        assert route["model"] == "stroom-bulk"
        assert route["system_prompt"] == _ARTICLE_SUMMARY_SYSTEM

    def test_long_article_routes_to_cloud_with_article_prompt(self):
        """Longread (>20k chars) → cloud-model met groot context-window, maar
        nog steeds de artikel-prompt (geen transcript-prompt)."""
        long_text = "x " * LONG_TRANSCRIPT_CHAR_FALLBACK
        route = _pick_summary_route(long_text, duration_seconds=None, is_article=True)
        assert route["is_long"] is True
        assert route["model"] == LONG_TRANSCRIPT_MODEL
        assert route["system_prompt"] == _ARTICLE_SUMMARY_SYSTEM
        assert route["timeout"] == 600.0

    def test_long_article_truncated_to_max_chars(self):
        huge = "z" * (LONG_TRANSCRIPT_MAX_CHARS * 2)
        route = _pick_summary_route(huge, duration_seconds=None, is_article=True)
        assert len(route["cleaned"]) == LONG_TRANSCRIPT_MAX_CHARS
