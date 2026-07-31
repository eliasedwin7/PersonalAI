"""Application logging for the Nexus desktop app."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from personalai.core import config as config_mod

LOG_DIR = config_mod.APP_DIR / "logs"
LOG_FILE = LOG_DIR / "nexus.log"


def configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(isinstance(handler, RotatingFileHandler) for handler in root.handlers):
        return
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    def log_uncaught(exc_type, exc, tb):
        logging.getLogger("personalai").exception(
            "Uncaught exception", exc_info=(exc_type, exc, tb)
        )
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = log_uncaught
