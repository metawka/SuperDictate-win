"""System tray icon.

This is the Windows counterpart of the macOS menu bar item, and it is
what keeps the app alive: closing every window leaves the tray icon, the
keyboard hook and the loaded model in place.

The icon is drawn rather than loaded, so it stays crisp at any DPI and
can recolour itself per state — grey while the model loads, red while
recording, blue while transcribing — which is the same signalling the
macOS menubar template images provide.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import i18n
from ..app import AppState

_STATE_COLORS = {
    AppState.STARTING: "#8e8e93",
    AppState.DOWNLOADING: "#8e8e93",
    AppState.LOADING: "#8e8e93",
    AppState.READY: "#f2f2f7",
    AppState.RECORDING: "#ff453a",
    AppState.TRANSCRIBING: "#0a84ff",
    AppState.FAILED: "#ff9f0a",
}


def build_icon(color: str = "#f2f2f7", size: int = 64) -> QIcon:
    """A microphone glyph: rounded capsule, stand, and base."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))

    unit = size / 64.0
    capsule = QRectF(24 * unit, 10 * unit, 16 * unit, 26 * unit)
    path = QPainterPath()
    path.addRoundedRect(capsule, 8 * unit, 8 * unit)
    painter.drawPath(path)

    arc = QPainterPath()
    arc.moveTo(18 * unit, 30 * unit)
    arc.arcTo(QRectF(18 * unit, 20 * unit, 28 * unit, 26 * unit), 180, 180)
    painter.setPen(QColor(color))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    pen = painter.pen()
    pen.setWidthF(3.4 * unit)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawPath(arc)
    painter.drawLine(int(32 * unit), int(46 * unit), int(32 * unit), int(54 * unit))
    painter.drawLine(int(24 * unit), int(54 * unit), int(40 * unit), int(54 * unit))
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    def __init__(self, controller, *, on_panel, on_settings, on_history, on_quit) -> None:
        super().__init__()
        self._controller = controller
        self._on_panel = on_panel

        menu = QMenu()
        self._toggle_action = QAction(i18n.tr("tray_start"), menu)
        self._toggle_action.triggered.connect(self._toggle_dictation)
        menu.addAction(self._toggle_action)
        menu.addSeparator()

        for label_key, handler in (
            ("tray_open_panel", on_panel),
            ("tray_settings", on_settings),
            ("tray_history", on_history),
        ):
            action = QAction(i18n.tr(label_key), menu)
            action.triggered.connect(lambda _=False, h=handler: h())
            menu.addAction(action)

        menu.addSeparator()
        quit_action = QAction(i18n.tr("tray_quit"), menu)
        quit_action.triggered.connect(lambda: on_quit())
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        controller.state_changed.connect(self._on_state_changed)
        self._apply_state(controller.state)

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._on_panel()

    def _toggle_dictation(self) -> None:
        if self._controller.state is AppState.RECORDING:
            self._controller.finish_recording(
                self._controller.settings.primary_completion_behavior)
        else:
            self._controller.begin_recording()

    def _on_state_changed(self, value: str) -> None:
        self._apply_state(AppState(value))

    def _apply_state(self, state: AppState) -> None:
        self.setIcon(build_icon(_STATE_COLORS.get(state, "#f2f2f7")))
        label = {
            AppState.STARTING: "status_starting",
            AppState.DOWNLOADING: "status_downloading",
            AppState.LOADING: "status_loading",
            AppState.READY: "status_ready",
            AppState.RECORDING: "status_recording",
            AppState.TRANSCRIBING: "status_transcribing",
            AppState.FAILED: "status_failed",
        }.get(state, "status_starting")
        self.setToolTip(f"{i18n.tr('app_name')} — {i18n.tr(label)}")
        self._toggle_action.setText(
            i18n.tr("tray_stop") if state is AppState.RECORDING
            else i18n.tr("tray_start")
        )
        self._toggle_action.setEnabled(state in (AppState.READY, AppState.RECORDING))
