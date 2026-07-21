"""Small Windows integrations: output muting, feedback sounds, autostart
and single-instance enforcement.

Each of these replaces a macOS-specific mechanism:

===========================  ==========================================
macOS                        Windows
===========================  ==========================================
CoreAudio default device     ``IAudioEndpointVolume`` via pycaw
``NSSound`` system sounds    generated tones via ``winsound``
``~/Library/LaunchAgents``   ``HKCU\\...\\CurrentVersion\\Run``
PID file in Application      a named kernel mutex
Support
===========================  ==========================================
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import io
import math
import struct
import sys
import threading
import wave
from functools import lru_cache
from typing import Optional

from . import paths
from .logging_setup import get as get_logger

log = get_logger("system")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# -- system output mute --------------------------------------------------


class OutputMute:
    """Mutes the default playback device for the duration of a recording.

    macOS mutes so the microphone does not pick up whatever is playing.
    The same reasoning applies here, plus the restore-on-exit guarantee:
    if the app dies mid-recording the user is left with a muted machine,
    so the previous state is also restored from ``atexit``.
    """

    def __init__(self) -> None:
        self._previous: Optional[bool] = None
        self._lock = threading.Lock()

    def _endpoint(self):
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        speakers = AudioUtilities.GetSpeakers()
        interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))

    def mute(self) -> None:
        with self._lock:
            if self._previous is not None:
                return
            try:
                import comtypes

                comtypes.CoInitialize()
                volume = self._endpoint()
                self._previous = bool(volume.GetMute())
                if not self._previous:
                    volume.SetMute(1, None)
            except Exception as exc:
                log.warning("Could not mute system output: %s", exc)
                self._previous = None

    def restore(self) -> None:
        with self._lock:
            if self._previous is None:
                return
            was_muted = self._previous
            self._previous = None
            if was_muted:
                return
            try:
                import comtypes

                comtypes.CoInitialize()
                self._endpoint().SetMute(0, None)
            except Exception as exc:
                log.warning("Could not restore system output: %s", exc)


# -- feedback sounds -----------------------------------------------------


CUE_SAMPLE_RATE = 44100


@lru_cache(maxsize=8)
def _cue(segments: tuple[tuple[int, int], ...], volume: float = 0.22) -> bytes:
    """Render a sequence of (frequency Hz, duration ms) tones to a WAV.

    A frequency of zero is silence. The phase carries across segments and
    the whole clip gets a short attack and release, because a sine that
    starts or stops at a non-zero value clicks, and a click is exactly the
    kind of cheap-sounding detail these cues exist to avoid.
    """
    total = sum(CUE_SAMPLE_RATE * ms // 1000 for _, ms in segments)
    attack = int(CUE_SAMPLE_RATE * 0.004)
    release = int(CUE_SAMPLE_RATE * 0.020)
    frames = bytearray()
    phase = 0.0
    index = 0

    for frequency, milliseconds in segments:
        count = CUE_SAMPLE_RATE * milliseconds // 1000
        step = 2.0 * math.pi * frequency / CUE_SAMPLE_RATE
        for _ in range(count):
            if index < attack:
                envelope = index / attack
            elif index > total - release:
                envelope = max(0.0, (total - index) / release)
            else:
                envelope = 1.0
            sample = math.sin(phase) if frequency else 0.0
            frames += struct.pack("<h", int(32767 * volume * envelope * sample))
            phase += step
            index += 1

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(CUE_SAMPLE_RATE)
        out.writeframes(bytes(frames))
    return buffer.getvalue()


class Sounds:
    """Short non-blocking cues for start / stop / error.

    These used to be Windows system event sounds, which meant "recording
    started" was whatever the user's theme assigned to Asterisk: often a
    long chime, sometimes the same sound as an error dialog, and on a
    silent theme nothing at all. The cues are synthesised instead, so the
    pitch itself carries the meaning, rising to start and falling to stop,
    and they stay short enough not to bleed into the recording.
    """

    _EVENTS: dict[str, tuple[tuple[int, int], ...]] = {
        "start": ((660, 45), (990, 60)),
        "stop": ((990, 45), (660, 60)),
        "error": ((330, 90), (0, 45), (330, 110)),
        "rejected": ((420, 55),),
    }

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def play(self, event: str) -> None:
        if not self.enabled:
            return
        segments = self._EVENTS.get(event)
        if segments is None:
            return

        def worker() -> None:
            try:
                import winsound

                # SND_MEMORY with SND_ASYNC needs the buffer to outlive the
                # call; the lru_cache is what keeps it alive.
                winsound.PlaySound(_cue(segments),
                                   winsound.SND_MEMORY | winsound.SND_ASYNC)
            except Exception as exc:
                log.debug("Could not play the %s cue: %s", event, exc)

        threading.Thread(target=worker, name="sound", daemon=True).start()


# -- autostart -----------------------------------------------------------

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "D1CT"


def _launch_command() -> str:
    executable = sys.executable
    if getattr(sys, "frozen", False):
        return f'"{executable}"'
    script = paths.resource_path("main.py")
    return f'"{executable}" "{script}"'


def autostart_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _RUN_VALUE)
            return bool(value)
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        log.warning("Could not update autostart: %s", exc)
        return False


# -- window plumbing -----------------------------------------------------

# Declared rather than left to ctypes' c_int default, so handles survive
# intact on a 64-bit build.
user32.GetForegroundWindow.restype = wt.HWND
user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
user32.RegisterWindowMessageW.restype = wt.UINT
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL


# -- single instance -----------------------------------------------------


class SingleInstance:
    """A named mutex, checked before the UI is built.

    macOS writes a PID file and signals the running control panel; the
    Windows equivalent is a kernel mutex plus a broadcast window message
    so a second launch surfaces the existing window instead of racing it
    for the keyboard hook.
    """

    def __init__(self, name: str = paths.SINGLE_INSTANCE_MUTEX) -> None:
        self._handle = kernel32.CreateMutexW(None, False, name)
        # ctypes saves and restores the thread's last-error value around
        # every call when the library was opened with use_last_error, so
        # calling GetLastError() through it reads back ctypes' own restored
        # value rather than CreateMutexW's. ctypes.get_last_error() is the
        # one that returns what the call actually set.
        self.already_running = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


SHOW_PANEL_MESSAGE = "D1CT.ShowControlPanel"


def register_show_message() -> int:
    return user32.RegisterWindowMessageW(SHOW_PANEL_MESSAGE)


def broadcast_show_panel() -> None:
    HWND_BROADCAST = 0xFFFF
    user32.PostMessageW(HWND_BROADCAST, register_show_message(), 0, 0)
