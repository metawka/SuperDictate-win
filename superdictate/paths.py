"""Filesystem layout for the Windows port.

The macOS build keeps everything under ``~/Library/Application Support/
SuperDictate`` with the FluidAudio model cache in a sibling directory.
(The app was called SuperDictate here too, before 1.5.0.)
Windows has no equivalent split, so one ``%LOCALAPPDATA%\\D1CT`` tree holds
settings, history and the ONNX model cache. Keeping the model inside the
same tree means an uninstall that spares user data also spares the
~600 MB download, matching the macOS uninstall.sh behaviour.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "D1CT"
BUNDLE_ID = "com.local.d1ct"
# Where the app kept its data before the rename. Existing installs are
# moved on first launch so nobody re-downloads 640 MB of weights.
LEGACY_APP_NAME = "SuperDictate"


def _local_app_data() -> Path:
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Local"


_HOME_OVERRIDE = os.environ.get("D1CT_HOME") or os.environ.get("SUPERDICTATE_HOME")
BASE_DIR = Path(_HOME_OVERRIDE or (_local_app_data() / APP_NAME))
LEGACY_BASE_DIR = _local_app_data() / LEGACY_APP_NAME

SETTINGS_FILE = BASE_DIR / "Settings.json"
HISTORY_FILE = BASE_DIR / "History.json"
USAGE_FILE = BASE_DIR / "Usage.json"
CORRECTIONS_FILE = BASE_DIR / "Corrections.json"
PENDING_DICTATION_FILE = BASE_DIR / "PendingDictation.raw"
LOG_DIR = BASE_DIR / "Logs"
LOG_FILE = LOG_DIR / "D1CT.log"
MODELS_DIR = BASE_DIR / "Models"
CACHE_DIR = BASE_DIR / "Cache"
SINGLE_INSTANCE_MUTEX = "Global\\D1CT.SingleInstance"


def migrate_legacy_directory() -> bool:
    """Move a pre-rename data directory into place. Returns True if moved.

    Only ever runs when the new directory does not exist yet, so a user
    who has already started fresh never has old data pushed back at them.
    """
    if BASE_DIR.exists() or not LEGACY_BASE_DIR.exists():
        return False
    if BASE_DIR.resolve() == LEGACY_BASE_DIR.resolve():
        return False
    try:
        BASE_DIR.parent.mkdir(parents=True, exist_ok=True)
        os.replace(LEGACY_BASE_DIR, BASE_DIR)
        return True
    except OSError:
        return False


def ensure_directories() -> None:
    migrate_legacy_directory()
    for directory in (BASE_DIR, LOG_DIR, MODELS_DIR, CACHE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def resource_path(*parts: str) -> Path:
    """Resolve a bundled resource both in-tree and inside a PyInstaller bundle."""
    import sys

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root.joinpath(*parts)
