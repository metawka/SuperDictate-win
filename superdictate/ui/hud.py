"""The floating recording capsule.

A frameless, translucent, always-on-top window that shows a live waveform
while recording and a travelling shimmer while transcribing, the macOS
recording HUD, with its geometry constants carried over verbatim
(64x38 base, the same size multipliers, the same animate-in/out timings).

Two Windows-specific requirements shape the implementation:

* **It must never take focus.** The paste goes to whatever window the
  user was typing in, so the HUD carries ``WS_EX_NOACTIVATE`` and
  ``WS_EX_TRANSPARENT``: clicks fall through to the app underneath and
  focus never moves.
* **It must not appear in the taskbar or Alt+Tab.** ``Qt.Tool`` plus
  ``WS_EX_TOOLWINDOW`` handles that.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import math
import random
from typing import Optional

from PySide6.QtCore import (
    Property,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from ..settings import AccentColor, ColorSpec, HUDBackground, HUDSize

BASE_WIDTH = 64.0
BASE_HEIGHT = 38.0
ANIMATE_IN_SECONDS = 0.32
ANIMATE_OUT_SECONDS = 0.23
# Only needed to catch a screen change or a taskbar resize mid-recording.
TARGET_REFRESH_INTERVAL_MS = 700
BOTTOM_MARGIN = 24
FRAME_INTERVAL_MS = 16  # ~60 fps
BAR_COUNT = 5

user32 = ctypes.WinDLL("user32", use_last_error=True)
# The HWND argument must be declared, or ctypes passes it as a c_int.
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wt.LONG
user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, wt.LONG]
user32.SetWindowLongW.restype = wt.LONG
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080


class RecordingHUD(QWidget):
    """States: hidden -> recording -> transcribing -> hidden."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._mode = "hidden"
        self._level = 0.0
        self._smoothed_level = 0.0
        self._phase = 0.0
        self._opacity = 0.0
        self._bar_levels = [0.15] * BAR_COUNT

        self.size_preset = HUDSize.STANDARD
        self.recording_color = ColorSpec.of(AccentColor.RED)
        self.transcribing_color = ColorSpec.of(AccentColor.BLUE)
        self.background_style = HUDBackground.SYSTEM

        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(FRAME_INTERVAL_MS)
        self._frame_timer.timeout.connect(self._tick)

        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(TARGET_REFRESH_INTERVAL_MS)
        self._follow_timer.timeout.connect(self._reposition)

        self._fade = QPropertyAnimation(self, b"fadeOpacity", self)
        self._fade.finished.connect(self._fade_finished)

        self._apply_size()

    # -- configuration ------------------------------------------------

    def configure(self, *, size: HUDSize, recording: ColorSpec,
                  transcribing: ColorSpec, background: HUDBackground) -> None:
        self.size_preset = size
        self.recording_color = recording
        self.transcribing_color = transcribing
        self.background_style = background
        self._apply_size()
        self.update()

    def _apply_size(self) -> None:
        scale = self.size_preset.scale
        self.resize(int(BASE_WIDTH * scale), int(BASE_HEIGHT * scale))

    # -- fade property ------------------------------------------------

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = value
        self.setWindowOpacity(value)

    fadeOpacity = Property(float, _get_opacity, _set_opacity)

    # -- state --------------------------------------------------------

    def show_recording(self) -> None:
        self._mode = "recording"
        self._bar_levels = [0.15] * BAR_COUNT
        self._reposition()
        self._make_click_through()
        self.show()
        self._frame_timer.start()
        self._follow_timer.start()
        self._animate_to(1.0, ANIMATE_IN_SECONDS)

    def show_transcribing(self) -> None:
        if self._mode == "hidden":
            self.show_recording()
        self._mode = "transcribing"
        self.update()

    def hide_hud(self) -> None:
        if self._mode == "hidden":
            return
        self._mode = "hiding"
        self._follow_timer.stop()
        self._animate_to(0.0, ANIMATE_OUT_SECONDS)

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))

    def _animate_to(self, target: float, seconds: float) -> None:
        self._fade.stop()
        self._fade.setDuration(int(seconds * 1000))
        self._fade.setStartValue(self._opacity)
        self._fade.setEndValue(target)
        self._fade.start()

    def _fade_finished(self) -> None:
        if self._opacity <= 0.01:
            self._mode = "hidden"
            self._frame_timer.stop()
            self.hide()

    # -- placement ----------------------------------------------------

    def _reposition(self) -> None:
        """Bottom centre of the active screen, always.

        The capsule used to follow the text caret. In practice that made
        it jump to wherever a window happened to put its cursor, docking
        it to the top of some apps, and it moved while you spoke. A fixed
        spot above the taskbar is predictable and never covers what you
        are typing into.
        """
        screen = (QApplication.screenAt(_cursor_position())
                  or QApplication.primaryScreen())
        area = screen.availableGeometry()
        target = QPoint(
            area.center().x() - self.width() // 2,
            area.bottom() - self.height() - BOTTOM_MARGIN,
        )
        target = _clamped_to_screen(target, self.width(), self.height())
        if target != self.pos():
            self.move(target)

    def _make_click_through(self) -> None:
        """Qt's transparent-for-mouse-events is per-widget; the window
        itself still activates on click without these extended styles."""
        try:
            handle = int(self.winId())
        except Exception:
            return
        style = user32.GetWindowLongW(handle, GWL_EXSTYLE)
        user32.SetWindowLongW(
            handle, GWL_EXSTYLE,
            style | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW,
        )

    # -- animation ----------------------------------------------------

    def _tick(self) -> None:
        if self._mode == "recording":
            # Ease toward the measured level so a single loud syllable
            # doesn't snap every bar to full height.
            self._smoothed_level += (self._level - self._smoothed_level) * 0.35
            self._phase += 0.16 + self._smoothed_level * 0.10
            for index in range(BAR_COUNT):
                wave = 0.5 + 0.5 * math.sin(self._phase * (1.0 + index * 0.22) + index)
                target = 0.12 + self._smoothed_level * wave * 1.5
                target += random.uniform(-0.02, 0.02)
                self._bar_levels[index] += (
                    max(0.08, min(1.0, target)) - self._bar_levels[index]
                ) * 0.4
        elif self._mode == "transcribing":
            self._phase += 0.11
            for index in range(BAR_COUNT):
                wave = 0.5 + 0.5 * math.sin(self._phase * 2.0 - index * 0.9)
                self._bar_levels[index] += (0.2 + wave * 0.55 - self._bar_levels[index]) * 0.3
        self.update()

    # -- painting -----------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        radius = rect.height() / 2.0

        background, border = self._background_colors()
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, background)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)

        spec = (self.recording_color if self._mode == "recording"
                else self.transcribing_color)

        scale = self.size_preset.scale
        bar_width = 3.0 * scale
        gap = 3.2 * scale
        total_width = BAR_COUNT * bar_width + (BAR_COUNT - 1) * gap
        left = (self.width() - total_width) / 2.0
        max_height = self.height() * 0.52
        center_y = self.height() / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        if spec.is_gradient:
            # Across the whole run of bars rather than per bar, so the
            # ramp reads as one object instead of five striped ones.
            ramp = QLinearGradient(QPointF(left, 0.0),
                                   QPointF(left + total_width, 0.0))
            ramp.setColorAt(0.0, QColor(spec.start))
            ramp.setColorAt(1.0, QColor(spec.end))
            painter.setBrush(ramp)
        else:
            painter.setBrush(QColor(spec.start))
        for index, level in enumerate(self._bar_levels):
            height = max(bar_width, max_height * level)
            bar = QRectF(
                left + index * (bar_width + gap),
                center_y - height / 2.0,
                bar_width,
                height,
            )
            painter.drawRoundedRect(bar, bar_width / 2.0, bar_width / 2.0)
        painter.end()

    def _background_colors(self) -> tuple[QColor, QColor]:
        style = self.background_style
        if style is HUDBackground.SYSTEM:
            dark = _system_is_dark()
        else:
            dark = style is HUDBackground.DARK
        if dark:
            return QColor(28, 28, 30, 214), QColor(255, 255, 255, 38)
        return QColor(250, 250, 252, 224), QColor(0, 0, 0, 30)


def _system_is_dark() -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return not bool(value)
    except OSError:
        return True


def _cursor_position() -> QPoint:
    from PySide6.QtGui import QCursor

    return QCursor.pos()


def _clamped_to_screen(point: QPoint, width: int, height: int) -> QPoint:
    screen = QApplication.screenAt(point) or QApplication.primaryScreen()
    area = screen.availableGeometry()
    x = max(area.left(), min(point.x(), area.right() - width))
    y = max(area.top(), min(point.y(), area.bottom() - height))
    return QPoint(int(x), int(y))
