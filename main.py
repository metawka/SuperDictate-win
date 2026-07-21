"""Entry point.

Usage::

    python main.py                 # normal launch (tray + control panel)
    python main.py --minimized     # launch to tray only, for autostart
    python main.py --self-test     # run the built-in checks and exit

``--self-test`` mirrors the macOS ``Parakey --self-test all``: it exercises
the pure logic (hotkey state machine, transcript processing, settings
round-trip) without touching the microphone, the keyboard hook or the
model, so CI can run it headlessly.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from superdictate import i18n, paths
from superdictate.app import AppState, DictationController
from superdictate.logging_setup import configure, get as get_logger
from superdictate.settings import Settings
from superdictate.system import SingleInstance, broadcast_show_panel
from superdictate.ui.history_window import HistoryWindow
from superdictate.ui.panel import ControlPanel
from superdictate.ui.settings_window import SettingsWindow
from superdictate.ui.theme import stylesheet
from superdictate.ui.tray import Tray, build_icon
from superdictate.version import VERSION


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        from superdictate.selftest import run_all

        return 0 if run_all() else 1

    paths.ensure_directories()
    log = configure(verbose="--verbose" in argv)
    log.info("D1CT %s starting", VERSION)

    instance = SingleInstance()
    if instance.already_running:
        log.info("Another instance is running; asking it to show its panel")
        broadcast_show_panel()
        return 0

    app = QApplication(argv)
    app.setApplicationName("D1CT")
    # No display name: Qt would append " - D1CT" to every window title, and
    # the control panel already says "D1CT 1.5.0".
    app.setWindowIcon(build_icon())
    # One stylesheet for every window, so dialogs opened later inherit the
    # same look instead of falling back to the raw Windows theme.
    app.setStyleSheet(stylesheet())
    # The tray icon is the service; windows come and go.
    app.setQuitOnLastWindowClosed(False)

    settings = Settings()
    i18n.set_language(settings.interface_language)

    controller = DictationController(settings)

    windows = _Windows(controller)
    tray = Tray(
        controller,
        on_panel=windows.show_panel,
        on_settings=windows.show_settings,
        on_history=windows.toggle_history,
        on_quit=lambda: _quit(app, controller, instance),
    )
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("No system tray available; the control panel is the only surface")
    tray.show()

    controller.history_toggle_requested.connect(windows.toggle_history)
    # On-screen rather than through the Windows notification centre: a
    # banner that Focus Assist defers is a banner the user never sees.
    controller.error_raised.connect(windows.show_warning)
    controller.transcript_ready.connect(lambda _: windows.refresh_history())
    controller.state_changed.connect(windows.on_state_changed)
    controller.level_changed.connect(windows.on_level)

    controller.start()

    if "--minimized" not in argv:
        windows.show_panel()

    app.aboutToQuit.connect(lambda: controller.shutdown())
    return app.exec()


class _Windows:
    """Lazily-built windows, so startup only pays for the tray."""

    def __init__(self, controller) -> None:
        self._controller = controller
        self._panel = None
        self._settings_window = None
        self._history = None
        self._hud = None
        self._toasts = None

    # -- notifications --------------------------------------------------

    @property
    def toasts(self):
        if self._toasts is None:
            from superdictate.ui.toast import ToastManager

            self._toasts = ToastManager()
        return self._toasts

    def show_warning(self, message: str) -> None:
        from superdictate.ui.toast import Level

        self.toasts.show(message, Level.WARNING)

    # -- panel / settings / history ------------------------------------

    def show_panel(self) -> None:
        if self._panel is None:
            self._panel = ControlPanel(
                self._controller, self.show_settings, self.toggle_history
            )
        self._panel.show()
        self._panel.raise_()
        self._panel.activateWindow()

    def show_settings(self) -> None:
        window = SettingsWindow(
            self._controller.settings,
            self._controller.corrections,
            self._controller,
            self._panel,
        )
        window.exec()
        if self._panel is not None:
            self._panel.refresh()
        self._apply_hud_settings()

    def toggle_history(self) -> None:
        if self._history is None:
            self._history = HistoryWindow(self._controller)
        self._history.present()

    def refresh_history(self) -> None:
        if self._history is not None and self._history.isVisible():
            self._history.reload()

    # -- HUD ------------------------------------------------------------

    @property
    def hud(self):
        if self._hud is None:
            from superdictate.ui.hud import RecordingHUD

            self._hud = RecordingHUD()
            self._apply_hud_settings()
        return self._hud

    def _apply_hud_settings(self) -> None:
        if self._hud is None:
            return
        settings = self._controller.settings
        self._hud.configure(
            size=settings.hud_size,
            recording=settings.hud_recording_color,
            transcribing=settings.hud_transcribing_color,
            background=settings.hud_background_style,
        )

    def on_state_changed(self, value: str) -> None:
        if not self._controller.settings.show_recording_waveform:
            if self._hud is not None:
                self._hud.hide_hud()
            return
        state = AppState(value)
        if state is AppState.RECORDING:
            self.hud.show_recording()
        elif state is AppState.TRANSCRIBING:
            self.hud.show_transcribing()
        elif self._hud is not None:
            self._hud.hide_hud()

    def on_level(self, level: float) -> None:
        if self._hud is not None:
            self._hud.set_level(level)


def _quit(app: QApplication, controller, instance: SingleInstance) -> None:
    controller.shutdown()
    instance.release()
    app.quit()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
