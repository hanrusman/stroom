"""Unit test voor de run-lock op /admin/cron/nightly.

Verifieert dat een tweede aanroep, terwijl er al een run bezig is, direct
no-opt ("already_running") in plaats van een concurrente refresh-loop te
starten — de fix tegen de contentie-spiraal die de transcribe-stap deed
verhongeren (overlappende uurlijkse light-cron + nachtelijke full).
"""
import asyncio
import sys

import pytest

sys.path.insert(0, "/app")

import main  # noqa: E402

pytestmark = pytest.mark.unit


def test_nightly_skips_when_already_running():
    """Vlag staat al op True → endpoint returnt meteen de skip-dict en raakt
    de session niet aan (vandaar session=None: zou crashen bij gebruik)."""
    main._nightly_running = True
    try:
        result = asyncio.run(main.admin_cron_nightly(light=True, session=None))
    finally:
        main._nightly_running = False
    assert result == {"ok": False, "skipped": "already_running", "light": True}


def test_nightly_flag_reset_after_skip():
    """De skip-aanroep gebeurt vóór de try/finally, dus mag de vlag van een
    lopende run niet per ongeluk terugzetten naar False."""
    main._nightly_running = True
    try:
        asyncio.run(main.admin_cron_nightly(light=False, session=None))
        assert main._nightly_running is True
    finally:
        main._nightly_running = False
