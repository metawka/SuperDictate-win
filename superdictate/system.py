"""Small Windows integrations: output muting, feedback sounds, autostart,
caret location, and single-instance enforcement.

Each of these replaces a macOS-specific mechanism:

===========================  ==========================================
macOS                        Windows
===========================  ==========================================
CoreAudio default device     ``IAudioEndpointVolume`` via pycaw
``NSSound`` system sounds    ``winsound`` system events
``~/Library/LaunchAgents``   ``HKCU\\...\\CurrentVersion\\Run``
Accessibility caret bounds   ``GetGUIThreadInfo`` caret rect
PID file in Application      a named kernel mutex
Support
===========================  ==========================================
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import threading
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


class Sounds:
    """Short non-blocking cues for start / stop / error.

    Windows system event sounds are used rather than bundled WAVs so the
    cues respect the user's sound scheme and stay silent when they have
    chosen "No Sounds".
    """

    _EVENTS = {
        "start": "SystemAsterisk",
        "stop": "SystemExclamation",
        "error": "SystemHand",
        "rejected": "SystemQuestion",
    }

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def play(self, event: str) -> None:
        if not self.enabled:
            return
        alias = self._EVENTS.get(event)
        if alias is None:
            return

        def worker() -> None:
            try:
                import winsound

                winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass

        threading.Thread(target=worker, name="sound", daemon=True).start()


# -- autostart -----------------------------------------------------------

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "SuperDictate"


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


# -- caret location ------------------------------------------------------


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("flags", wt.DWORD),
        ("hwndActive", wt.HWND),
        ("hwndFocus", wt.HWND),
        ("hwndCapture", wt.HWND),
        ("hwndMenuOwner", wt.HWND),
        ("hwndMoveSize", wt.HWND),
        ("hwndCaret", wt.HWND),
        ("rcCaret", wt.RECT),
    ]


# Declared rather than left to ctypes' c_int default, so handles survive
# intact on a 64-bit build.
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetGUIThreadInfo.argtypes = [wt.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = wt.BOOL
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.ClientToScreen.restype = wt.BOOL
user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
user32.RegisterWindowMessageW.restype = wt.UINT
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL


def caret_screen_position() -> Optional[tuple[int, int]]:
    """Screen coordinates of the focused window's caret, if it exposes one.

    Password fields, Chromium-based apps and anything drawing its own text
    cursor report nothing — the same limitation the macOS build documents
    for apps that hide Accessibility data. Callers fall back to a fixed
    screen position.
    """
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return None
    thread_id = user32.GetWindowThreadProcessId(foreground, None)
    if not thread_id or not user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
        return None
    if not info.hwndCaret:
        return None

    point = wt.POINT(info.rcCaret.left, info.rcCaret.bottom)
    if not user32.ClientToScreen(info.hwndCaret, ctypes.byref(point)):
        return None
    if point.x == 0 and point.y == 0:
        return None
    return int(point.x), int(point.y)


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


SHOW_PANEL_MESSAGE = "SuperDictate.ShowControlPanel"


def register_show_message() -> int:
    return user32.RegisterWindowMessageW(SHOW_PANEL_MESSAGE)


def broadcast_show_panel() -> None:
    HWND_BROADCAST = 0xFFFF
    user32.PostMessageW(HWND_BROADCAST, register_show_message(), 0, 0)
