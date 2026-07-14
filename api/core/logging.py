"""Logging-setup (verbeterplan R3): levels + logger-namen i.p.v. print()."""
from __future__ import annotations

import logging
import os
import sys


def setup_logging(level: str | None = None) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    ))
    root = logging.getLogger()
    root.setLevel(level or os.environ.get("STROOM_LOG_LEVEL", "INFO"))
    root.handlers = [handler]
    # httpx is spraakzaam op INFO
    logging.getLogger("httpx").setLevel(logging.WARNING)
