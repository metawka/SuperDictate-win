"""Persistent settings.

macOS leans on ``NSUserDefaults``; the Windows port writes one JSON file
with the same key set, atomically (temp file + ``os.replace``) so a crash
mid-write can never truncate the user's configuration. Every getter has an
inline default, matching the macOS ``Settings`` class where a missing key
returns the default rather than being pre-registered.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from . import paths
from .hotkeys import (
    DEFAULT_ENTER_HOTKEY,
    DEFAULT_HISTORY_HOTKEY,
    DEFAULT_HOTKEY,
    HotkeyChoice,
    TriggerMode,
)


class CompletionBehavior(str, Enum):
    INSERT = "insert"
    INSERT_AND_ENTER = "insert_and_enter"

    @property
    def presses_enter(self) -> bool:
        return self is CompletionBehavior.INSERT_AND_ENTER

    @property
    def opposite(self) -> "CompletionBehavior":
        return (
            CompletionBehavior.INSERT_AND_ENTER
            if self is CompletionBehavior.INSERT
            else CompletionBehavior.INSERT
        )


class PasteSuffix(str, Enum):
    SPACE = "space"
    NONE = "none"
    NEWLINE = "newline"

    @property
    def text(self) -> str:
        return {"space": " ", "none": "", "newline": "\n"}[self.value]


class HUDSize(str, Enum):
    COMPACT = "compact"
    STANDARD = "standard"
    LARGE = "large"

    @property
    def scale(self) -> float:
        return {"compact": 1.15, "standard": 1.5, "large": 1.85}[self.value]


class HUDBackground(str, Enum):
    SYSTEM = "system"
    DARK = "dark"
    LIGHT = "light"


class AccentColor(str, Enum):
    RED = "red"
    ORANGE = "orange"
    PINK = "pink"
    PURPLE = "purple"
    BLUE = "blue"
    CYAN = "cyan"
    GREEN = "green"
    WHITE = "white"

    @property
    def rgb(self) -> tuple[int, int, int]:
        return {
            "red": (255, 69, 58),
            "orange": (255, 159, 10),
            "pink": (255, 55, 95),
            "purple": (191, 90, 242),
            "blue": (0, 112, 255),
            "cyan": (100, 210, 255),
            "green": (48, 209, 88),
            "white": (255, 255, 255),
        }[self.value]

    @property
    def hex(self) -> str:
        return "#%02x%02x%02x" % self.rgb


# Matches the macOS DictationLanguage enum: the 25-language Parakeet TDT v3
# decoder, narrowed to the languages the macOS UI exposes.
DICTATION_LANGUAGES: list[tuple[str, str]] = [
    ("auto", "Автоопределение / Auto-detect"),
    ("en", "English"),
    ("es", "Español"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("it", "Italiano"),
    ("pt", "Português"),
    ("ro", "Română"),
    ("pl", "Polski"),
    ("cs", "Čeština"),
    ("sk", "Slovenčina"),
    ("sl", "Slovenščina"),
    ("hr", "Hrvatski"),
    ("bs", "Bosanski"),
    ("ru", "Русский"),
    ("uk", "Українська"),
    ("be", "Беларуская"),
    ("bg", "Български"),
    ("sr", "Српски"),
]

RECENT_LIMITS = ["off", "1", "5", "10"]
DEFAULT_RECENT_LIMIT = "10"
HISTORY_ARCHIVE_MAX_ENTRIES = 200


@dataclass
class Correction:
    source: str
    replacement: str

    def to_json(self) -> dict:
        return {"source": self.source, "replacement": self.replacement}


_DEFAULTS: dict[str, Any] = {
    "hotkey": DEFAULT_HOTKEY.to_json(),
    "enter_hotkey": DEFAULT_ENTER_HOTKEY.to_json(),
    "history_hotkey": DEFAULT_HISTORY_HOTKEY.to_json(),
    "primary_completion_behavior": CompletionBehavior.INSERT.value,
    "alternate_completion_enabled": True,
    "interface_language": "ru",
    "trigger_mode": TriggerMode.TOGGLE.value,
    "paste_suffix": PasteSuffix.SPACE.value,
    "enter_delay_milliseconds": 120,
    "recent_transcript_limit": DEFAULT_RECENT_LIMIT,
    "show_recording_waveform": True,
    "hud_recording_color": AccentColor.RED.value,
    "hud_transcribing_color": AccentColor.BLUE.value,
    "hud_background_style": HUDBackground.SYSTEM.value,
    "hud_size": HUDSize.STANDARD.value,
    "mute_while_recording": False,
    "play_feedback_sounds": True,
    "input_device": "",  # empty = system default
    "check_for_updates": True,
    "dictation_language": "auto",
    "remove_filler_words": False,
    "stop_on_silence": False,
    "silence_stop_seconds": 2.5,
    "start_at_login": False,
    "compute_provider": "auto",  # auto | cuda | cpu
    "model_quantization": "int8",  # int8 | full
    "last_seen_version": "",
    "skipped_versions": [],
    "update_reminder_paused_version": "",
    "update_reminder_paused_until": 0.0,
}


class Settings:
    def __init__(self, path: Optional[os.PathLike] = None) -> None:
        self._path = paths.SETTINGS_FILE if path is None else path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = dict(_DEFAULTS)
        self.load()

    # -- persistence -------------------------------------------------

    def load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(stored, dict):
            return
        with self._lock:
            for key, value in stored.items():
                if key in _DEFAULTS:
                    self._data[key] = value

    def save(self) -> None:
        paths.ensure_directories()
        with self._lock:
            snapshot = dict(self._data)
        temp = f"{self._path}.tmp"
        try:
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, ensure_ascii=False, indent=2)
            os.replace(temp, self._path)
        except OSError:
            try:
                os.unlink(temp)
            except OSError:
                pass

    def _get(self, key: str) -> Any:
        with self._lock:
            return self._data.get(key, _DEFAULTS[key])

    def _set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def apply(self, changes: dict[str, Any]) -> None:
        """Apply a whole draft at once — the macOS `Save and restart` flow."""
        with self._lock:
            for key, value in changes.items():
                if key in _DEFAULTS:
                    self._data[key] = value
        self.save()

    # -- typed accessors ---------------------------------------------

    @property
    def hotkey(self) -> HotkeyChoice:
        return HotkeyChoice.from_json(self._get("hotkey"), DEFAULT_HOTKEY)

    @property
    def enter_hotkey(self) -> HotkeyChoice:
        return HotkeyChoice.from_json(self._get("enter_hotkey"), DEFAULT_ENTER_HOTKEY)

    @property
    def history_hotkey(self) -> HotkeyChoice:
        return HotkeyChoice.from_json(self._get("history_hotkey"), DEFAULT_HISTORY_HOTKEY)

    @property
    def primary_completion_behavior(self) -> CompletionBehavior:
        return _enum_or(CompletionBehavior, self._get("primary_completion_behavior"),
                        CompletionBehavior.INSERT)

    @property
    def alternate_completion_enabled(self) -> bool:
        return bool(self._get("alternate_completion_enabled"))

    @property
    def interface_language(self) -> str:
        value = self._get("interface_language")
        return value if value in ("ru", "en") else "ru"

    @property
    def trigger_mode(self) -> TriggerMode:
        return _enum_or(TriggerMode, self._get("trigger_mode"), TriggerMode.TOGGLE)

    @property
    def paste_suffix(self) -> PasteSuffix:
        return _enum_or(PasteSuffix, self._get("paste_suffix"), PasteSuffix.SPACE)

    @property
    def enter_delay_milliseconds(self) -> int:
        try:
            return max(0, min(500, int(self._get("enter_delay_milliseconds"))))
        except (TypeError, ValueError):
            return 120

    @property
    def recent_transcript_limit(self) -> int:
        raw = str(self._get("recent_transcript_limit"))
        return {"off": 0, "1": 1, "5": 5, "10": 10}.get(raw, 10)

    @property
    def show_recording_waveform(self) -> bool:
        return bool(self._get("show_recording_waveform"))

    @property
    def hud_recording_color(self) -> AccentColor:
        return _enum_or(AccentColor, self._get("hud_recording_color"), AccentColor.RED)

    @property
    def hud_transcribing_color(self) -> AccentColor:
        return _enum_or(AccentColor, self._get("hud_transcribing_color"), AccentColor.BLUE)

    @property
    def hud_background_style(self) -> HUDBackground:
        return _enum_or(HUDBackground, self._get("hud_background_style"), HUDBackground.SYSTEM)

    @property
    def hud_size(self) -> HUDSize:
        return _enum_or(HUDSize, self._get("hud_size"), HUDSize.STANDARD)

    @property
    def mute_while_recording(self) -> bool:
        return bool(self._get("mute_while_recording"))

    @property
    def play_feedback_sounds(self) -> bool:
        return bool(self._get("play_feedback_sounds"))

    @property
    def input_device(self) -> str:
        return str(self._get("input_device") or "")

    @property
    def check_for_updates(self) -> bool:
        return bool(self._get("check_for_updates"))

    @property
    def dictation_language(self) -> str:
        value = str(self._get("dictation_language"))
        return value if value in {code for code, _ in DICTATION_LANGUAGES} else "auto"

    @property
    def remove_filler_words(self) -> bool:
        return bool(self._get("remove_filler_words"))

    @property
    def stop_on_silence(self) -> bool:
        return bool(self._get("stop_on_silence"))

    @property
    def silence_stop_seconds(self) -> float:
        try:
            return max(1.0, min(10.0, float(self._get("silence_stop_seconds"))))
        except (TypeError, ValueError):
            return 2.5

    @property
    def start_at_login(self) -> bool:
        return bool(self._get("start_at_login"))

    @property
    def model_quantization(self) -> str:
        value = str(self._get("model_quantization"))
        return value if value in ("int8", "full") else "int8"

    @property
    def compute_provider(self) -> str:
        value = str(self._get("compute_provider"))
        return value if value in ("auto", "cuda", "cpu") else "auto"

    @property
    def last_seen_version(self) -> str:
        return str(self._get("last_seen_version") or "")

    @last_seen_version.setter
    def last_seen_version(self, value: str) -> None:
        self._set("last_seen_version", value)
        self.save()

    @property
    def skipped_versions(self) -> list[str]:
        value = self._get("skipped_versions")
        return [str(v) for v in value] if isinstance(value, list) else []

    def skip_version(self, version: str) -> None:
        versions = self.skipped_versions
        if version not in versions:
            versions.append(version)
        self._set("skipped_versions", versions[-20:])
        self.save()


def _enum_or(enum_cls, raw: Any, fallback):
    try:
        return enum_cls(raw)
    except (ValueError, TypeError):
        return fallback
