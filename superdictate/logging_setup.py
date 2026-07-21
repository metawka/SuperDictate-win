"""Rotating file log plus stderr, mirroring ``~/Library/Logs/SuperDictate*`` (D1CT.log here)."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from . import paths

_configured = False


def configure(verbose: bool = False) -> logging.Logger:
    global _configured
    logger = logging.getLogger("superdictate")
    if _configured:
        return logger

    paths.ensure_directories()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        paths.LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # A windowed PyInstaller build has no stderr; guard so logging never
    # becomes the thing that crashes the app.
    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    logger.propagate = False
    _configured = True
    return logger


def get(name: str = "") -> logging.Logger:
    base = logging.getLogger("superdictate")
    return base.getChild(name) if name else base
