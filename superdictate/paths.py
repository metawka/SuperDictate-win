"""Filesystem layout for the Windows port.

The macOS build keeps everything under ``~/Library/Application Support/
SuperDictate`` with the FluidAudio model cache in a sibling directory.
Windows has no equivalent split, so one ``%LOCALAPPDATA%\\SuperDictate``
tree holds settings, history and the ONNX model cache. Keeping the model
inside the same tree means an uninstall that spares user data also spares
the ~600 MB download, matching the macOS uninstall.sh behaviour.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "SuperDictate"
BUNDLE_ID = "com.local.superdictate"


def _local_app_data() -> Path:
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Local"


BASE_DIR = Path(os.environ.get("SUPERDICTATE_HOME") or (_local_app_data() / APP_NAME))

SETTINGS_FILE = BASE_DIR / "Settings.json"
HISTORY_FILE = BASE_DIR / "History.json"
USAGE_FILE = BASE_DIR / "Usage.json"
CORRECTIONS_FILE = BASE_DIR / "Corrections.json"
PENDING_DICTATION_FILE = BASE_DIR / "PendingDictation.raw"
LOG_DIR = BASE_DIR / "Logs"
LOG_FILE = LOG_DIR / "SuperDictate.log"
MODELS_DIR = BASE_DIR / "Models"
SINGLE_INSTANCE_MUTEX = "Global\\SuperDictate.SingleInstance"


def ensure_directories() -> None:
    for directory in (BASE_DIR, LOG_DIR, MODELS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def resource_path(*parts: str) -> Path:
    """Resolve a bundled resource both in-tree and inside a PyInstaller bundle."""
    import sys

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root.joinpath(*parts)
