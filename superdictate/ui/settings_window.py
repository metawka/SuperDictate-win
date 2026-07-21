"""The settings window.

macOS puts the shortcuts, completion behaviour, capsule size, colours and
background behind the gear button, and (importantly) keeps every change
as a *draft* until "Save and restart" applies them together. That draft
model is preserved here: widgets mutate a local dict, and only Save writes
it back to :class:`~superdictate.settings.Settings` and asks the
controller to re-apply.

Windows-only additions live on the Advanced tab: the compute device (there
is no Neural Engine to default to) and the weight set, since the ONNX
model ships in two sizes.

Layout-wise every tab is a stack of titled cards, each card a two-column
grid of label and control, so related settings read as a group instead of
one long undifferentiated form.
"""

from __future__ import annotations

import html
from typing import Any, Optional

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .. import asr, audio, i18n
from ..hotkeys import HotkeyChoice, TriggerMode
from ..keynames import hotkey_name
from ..settings import (
    DICTATION_LANGUAGES,
    AccentColor,
    ColorSpec,
    CompletionBehavior,
    Correction,
    HUDSize,
    PasteSuffix,
    Settings,
    TextStyle,
)
from ..textproc import PRESET_FILLERS
from ..updater import PeriodicChecker
from . import icons
from .recorder import ShortcutRecorderDialog
from .rows import PRIMARY_ROLE, SECONDARY_ROLE, CorrectionRowDelegate
from .theme import Palette, palette, stylesheet


class ColorField(QWidget):
    """A colour, or two of them for a gradient.

    The eight presets that used to fill a combo box are still one click
    away inside the picker's own palette, but "розовый" is now whichever
    pink the user actually means rather than the one shipped in the enum.
    """

    def __init__(self, spec: ColorSpec, on_change, palette: Palette,
                 parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Plain")
        self._spec = spec
        self._on_change = on_change
        self._palette = palette

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._start_button = QPushButton()
        self._start_button.clicked.connect(lambda: self._pick(is_end=False))
        self._end_button = QPushButton()
        self._end_button.clicked.connect(lambda: self._pick(is_end=True))

        self._gradient = QCheckBox(i18n.tr("settings_color_gradient"))
        self._gradient.setChecked(spec.is_gradient)
        self._gradient.toggled.connect(self._toggle_gradient)

        row.addWidget(self._start_button, 1)
        row.addWidget(self._gradient)
        row.addWidget(self._end_button, 1)
        self._refresh()

    def _refresh(self) -> None:
        self._start_button.setText(self._spec.start.upper())
        self._start_button.setIcon(icons.swatch(self._spec.start, 13))
        gradient = self._spec.is_gradient
        self._end_button.setVisible(gradient)
        if gradient:
            self._end_button.setText(str(self._spec.end).upper())
            self._end_button.setIcon(icons.swatch(str(self._spec.end), 13))
        self._on_change(self._spec.to_json())

    def _toggle_gradient(self, enabled: bool) -> None:
        if enabled:
            # A gradient needs somewhere to go, and a second stop equal to
            # the first would just look like a broken picker.
            self._spec = ColorSpec(self._spec.start,
                                   self._spec.end or _shifted(self._spec.start))
        else:
            self._spec = ColorSpec(self._spec.start)
        self._refresh()

    def _pick(self, *, is_end: bool) -> None:
        current = QColor(self._spec.end if is_end else self._spec.start)
        chosen = QColorDialog.getColor(current, self,
                                       i18n.tr("settings_color_pick"))
        if not chosen.isValid():
            return
        value = chosen.name()
        self._spec = (ColorSpec(self._spec.start, value) if is_end
                      else ColorSpec(value, self._spec.end))
        self._refresh()


def _shifted(color: str) -> str:
    """A second stop far enough from the first to read as a gradient."""
    hue = QColor(color)
    return QColor.fromHsv((hue.hue() + 60) % 360 if hue.hue() >= 0 else 300,
                          max(80, hue.saturation()),
                          min(255, hue.value() + 20)).name()


class HintIcon(QLabel):
    """A question mark that explains the setting next to it on hover.

    The explanations used to sit under their settings as permanent grey
    paragraphs. Six of them turned a tab of switches into a page of prose,
    and the longest one (the text styles) described three modes the user
    had not chosen. The words are unchanged; they are one hover away now.
    """

    SIZE = 15

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Hint")
        self.setPixmap(icons.pixmap("help", palette().text_faint, self.SIZE, 1.7))
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._tip = ""
        self.set_text(text)

    def set_text(self, text: str) -> None:
        # Rich text on purpose: Qt only word-wraps a tooltip it considers
        # rich, and a four-line explanation on one line spans the screen.
        self._tip = f"<p style='margin:0'>{html.escape(text)}</p>"
        self.setToolTip(self._tip)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Shown by hand rather than left to Qt, whose wake-up delay is most
        # of a second: an icon whose only job is to be hovered should not
        # keep the reader waiting to find out what it says.
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height() + 2)),
                          self._tip, self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        QToolTip.hideText()
        super().leaveEvent(event)


def _with_hint(widget: QWidget, hint: QWidget, *, stretch: bool) -> QWidget:
    """Pair a control with its hint icon inside one grid cell."""
    holder = QWidget()
    # Named, and transparent by name: an unnamed QWidget inside a card takes
    # the window background from the stylesheet and paints a darker slab
    # across the row.
    holder.setObjectName("Hint")
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(widget, 1 if stretch else 0)
    if not stretch:
        row.addStretch(1)
    row.addWidget(hint, 0, Qt.AlignmentFlag.AlignVCenter)
    return holder


class Section(QWidget):
    """A titled card holding a two-column grid of settings."""

    def __init__(self, title: str, hint: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 13, 16, 14)
        outer.setSpacing(10)

        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        if hint:
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(7)
            header.addWidget(heading)
            header.addWidget(HintIcon(hint), 0, Qt.AlignmentFlag.AlignVCenter)
            header.addStretch(1)
            outer.addLayout(header)
        else:
            outer.addWidget(heading)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(10)
        self.grid.setColumnStretch(1, 1)
        outer.addLayout(self.grid)
        self._row = 0

    def add_row(self, label: Optional[str], widget: QWidget,
                hint: Optional[QWidget] = None) -> None:
        if hint is not None:
            widget = _with_hint(widget, hint, stretch=bool(label))
        if label:
            key = QLabel(label)
            key.setObjectName("Key")
            self.grid.addWidget(key, self._row, 0)
            self.grid.addWidget(widget, self._row, 1)
        else:
            self.grid.addWidget(widget, self._row, 0, 1, 2)
        self._row += 1


def _page(*sections: QWidget) -> QWidget:
    """Wrap sections in a scrollable page so a tall tab never clips."""
    inner = QWidget()
    layout = QVBoxLayout(inner)
    # No side margins: the dialog already insets the tab widget, and a
    # second inset made the cards look adrift in their own frame.
    layout.setContentsMargins(0, 12, 0, 0)
    layout.setSpacing(12)
    for section in sections:
        layout.addWidget(section)
    layout.addStretch(1)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(inner)
    return scroll


class SettingsWindow(QDialog):
    def __init__(self, settings: Settings, corrections, controller, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("settings_title"))
        # Wide enough for all five tabs. Narrower and Qt hides the last one
        # behind scroll arrows, which is how a settings dialog loses a tab
        # nobody ever finds.
        self.setMinimumSize(720, 620)
        self.resize(760, 700)

        self._settings = settings
        self._corrections = corrections
        self._controller = controller
        self._draft: dict[str, Any] = settings.snapshot()
        self._palette = palette()
        self.setStyleSheet(stylesheet(self._palette))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self._tabs = QTabWidget()
        self._tabs.setIconSize(icons.icon_size(16))
        self._tabs.tabBar().setUsesScrollButtons(False)
        self._tabs.tabBar().setExpanding(False)
        muted = self._palette.text_muted
        tabs = (
            ("keyboard", "settings_tab_hotkeys", self._build_shortcuts_tab),
            ("mic", "settings_tab_dictation", self._build_dictation_tab),
            ("palette", "settings_tab_appearance", self._build_appearance_tab),
            ("replace", "settings_tab_corrections", self._build_corrections_tab),
            ("sliders", "settings_tab_advanced", self._build_advanced_tab),
        )
        for icon_name, label_key, builder in tabs:
            self._tabs.addTab(builder(), icons.icon(icon_name, muted, 16),
                              i18n.tr(label_key))
        layout.addWidget(self._tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText(i18n.tr("settings_save_restart"))
        save.setObjectName("Primary")
        save.setIcon(icons.icon("check", self._palette.accent_text, 16))
        save.setIconSize(icons.icon_size(16))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            i18n.tr("settings_cancel"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- tabs ---------------------------------------------------------

    def _build_shortcuts_tab(self) -> QWidget:
        keys = Section(i18n.tr("settings_tab_hotkeys"))
        self._hotkey_button = self._shortcut_row(
            keys, "settings_primary_hotkey", "hotkey")
        self._history_hotkey_button = self._shortcut_row(
            keys, "settings_history_hotkey", "history_hotkey")

        behaviour = Section(i18n.tr("settings_section_behaviour"))
        self._trigger = self._combo(
            behaviour, "settings_trigger_mode", "trigger_mode",
            [(TriggerMode.TOGGLE.value, i18n.tr("settings_trigger_toggle")),
             (TriggerMode.HOLD.value, i18n.tr("settings_trigger_hold"))],
        )
        self._completion = self._combo(
            behaviour, "settings_completion", "primary_completion_behavior",
            [(CompletionBehavior.INSERT.value, i18n.tr("settings_completion_insert")),
             (CompletionBehavior.INSERT_AND_ENTER.value,
              i18n.tr("settings_completion_enter"))],
        )
        self._enter_delay = QSpinBox()
        self._enter_delay.setRange(0, 500)
        self._enter_delay.setSingleStep(10)
        self._enter_delay.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        # No suffix: the row label already carries the unit, and a hard-coded
        # English one sat badly next to a Russian label.
        self._enter_delay.setValue(int(self._draft["enter_delay_milliseconds"]))
        self._enter_delay.valueChanged.connect(
            lambda value: self._draft.update(enter_delay_milliseconds=value))
        behaviour.add_row(i18n.tr("settings_enter_delay"), self._enter_delay)
        return _page(keys, behaviour)

    def _build_dictation_tab(self) -> QWidget:
        recognition = Section(i18n.tr("settings_section_recognition"))
        self._language = self._combo(
            recognition, "settings_language", "dictation_language",
            [(code, label) for code, label in DICTATION_LANGUAGES],
        )
        self._suffix = self._combo(
            recognition, "settings_paste_suffix", "paste_suffix",
            [(PasteSuffix.SPACE.value, i18n.tr("settings_suffix_space")),
             (PasteSuffix.NONE.value, i18n.tr("settings_suffix_none")),
             (PasteSuffix.NEWLINE.value, i18n.tr("settings_suffix_newline"))],
        )
        # The style hint describes the chosen style only: four descriptions
        # at once made the reader find their own in a paragraph.
        self._text_style_hint = HintIcon()
        self._text_style = QComboBox()
        for style in (TextStyle.FORMAL, TextStyle.STANDARD,
                      TextStyle.INFORMAL, TextStyle.CASUAL):
            self._text_style.addItem(
                i18n.tr(f"settings_text_style_{style.value}"), style.value)
        index = self._text_style.findData(str(self._draft.get("text_style", "")))
        self._text_style.setCurrentIndex(index if index >= 0 else 0)
        self._text_style.currentIndexChanged.connect(self._text_style_changed)
        recognition.add_row(i18n.tr("settings_text_style"), self._text_style,
                            self._text_style_hint)
        self._text_style_changed()

        self._fillers = self._filler_row(recognition)
        self._digits = self._checkbox(
            recognition, "settings_numbers_as_digits", "numbers_as_digits",
            i18n.tr("settings_numbers_as_digits_hint"))

        capture = Section(i18n.tr("settings_section_capture"))
        devices = [("", i18n.tr("settings_device_default"))]
        devices += [(device.name, device.name) for device in audio.list_input_devices()]
        self._device = self._combo(
            capture, "settings_input_device", "input_device", devices)

        self._stop_on_silence = self._checkbox(
            capture, "settings_stop_on_silence", "stop_on_silence",
            i18n.tr("settings_stop_on_silence_hint"))
        self._silence_seconds = QDoubleSpinBox()
        self._silence_seconds.setRange(1.0, 10.0)
        self._silence_seconds.setSingleStep(0.5)
        self._silence_seconds.setDecimals(1)
        # Same reason as the stylesheet rule: Qt's native spin arrows do not
        # follow the theme and looked stuck on.
        self._silence_seconds.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._silence_seconds.setValue(float(self._draft.get("silence_stop_seconds", 2.5)))
        self._silence_seconds.valueChanged.connect(
            lambda value: self._draft.update(silence_stop_seconds=value))
        self._silence_seconds.setEnabled(bool(self._draft.get("stop_on_silence")))
        self._stop_on_silence.toggled.connect(self._silence_seconds.setEnabled)
        capture.add_row(i18n.tr("settings_silence_seconds"), self._silence_seconds)

        self._mute = self._checkbox(capture, "settings_mute", "mute_while_recording")
        self._pause_media = self._checkbox(
            capture, "settings_pause_media", "pause_media_while_recording",
            hint=i18n.tr("settings_pause_media_hint"))
        self._sounds = self._checkbox(capture, "settings_sounds", "play_feedback_sounds")

        history = Section(i18n.tr("settings_tab_dictation"))
        limits = [("off", i18n.tr("settings_history_off"))]
        limits += [(value, i18n.tr("settings_history_last", n=value))
                   for value in ("1", "5", "10")]
        self._history_limit = self._combo(
            history, "settings_history_limit", "recent_transcript_limit", limits)
        return _page(recognition, capture, history)

    def _build_appearance_tab(self) -> QWidget:
        general = Section(i18n.tr("settings_tab_appearance"))
        self._interface_language = self._combo(
            general, "settings_interface_language", "interface_language",
            [("ru", "Русский"), ("en", "English")],
        )
        self._waveform = self._checkbox(
            general, "settings_waveform", "show_recording_waveform")

        hud = Section("HUD")
        self._hud_size = self._combo(
            hud, "settings_hud_size", "hud_size",
            [(HUDSize.COMPACT.value, i18n.tr("settings_hud_size_compact")),
             (HUDSize.STANDARD.value, i18n.tr("settings_hud_size_standard")),
             (HUDSize.LARGE.value, i18n.tr("settings_hud_size_large"))],
        )
        self._color_row(hud, "settings_hud_recording_color",
                        "hud_recording_color", AccentColor.RED,
                        hint=i18n.tr("settings_color_hint"))
        self._color_row(hud, "settings_hud_transcribing_color",
                        "hud_transcribing_color", AccentColor.BLUE,
                        hint=i18n.tr("settings_color_hint"))
        self._live_preview = self._checkbox(
            hud, "settings_live_preview", "live_preview",
            i18n.tr("settings_live_preview_hint"))
        return _page(general, hud)

    def _build_corrections_tab(self) -> QWidget:
        section = Section(i18n.tr("settings_tab_corrections"),
                          i18n.tr("corrections_note"))

        self._corrections_list = QListWidget()
        self._corrections_list.setItemDelegate(
            CorrectionRowDelegate(self._palette, self._corrections_list))
        self._corrections_list.setMouseTracking(True)
        self._corrections_list.setUniformItemSizes(True)
        self._corrections_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._corrections_list.setMinimumHeight(220)
        for correction in self._corrections.all():
            self._add_correction_item(correction)
        section.add_row(None, self._corrections_list)

        editor = QWidget()
        editor.setObjectName("Plain")
        row = QHBoxLayout(editor)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._correction_source = QLineEdit()
        self._correction_source.setPlaceholderText(i18n.tr("corrections_source"))
        self._correction_replacement = QLineEdit()
        self._correction_replacement.setPlaceholderText(i18n.tr("corrections_replacement"))
        add = QPushButton(i18n.tr("corrections_add"))
        add.setIcon(icons.icon("plus", self._palette.text_muted, 15))
        add.clicked.connect(self._add_correction)
        remove = QPushButton(i18n.tr("corrections_remove"))
        remove.setIcon(icons.icon("trash", self._palette.text_muted, 15))
        remove.clicked.connect(self._remove_correction)
        row.addWidget(self._correction_source, 2)
        row.addWidget(self._correction_replacement, 2)
        row.addWidget(add)
        row.addWidget(remove)
        section.add_row(None, editor)
        return _page(section)

    def _build_advanced_tab(self) -> QWidget:
        system = Section(i18n.tr("settings_tab_advanced"))
        self._autostart = self._checkbox(
            system, "settings_autostart", "start_at_login")
        self._updates = self._checkbox(
            system, "settings_check_updates", "check_for_updates")

        # Moved off the control panel, which is a status window, not a
        # place to run errands from.
        self._update_button = QPushButton(i18n.tr("panel_check_updates"))
        self._update_button.setIcon(icons.icon("download", self._palette.text_muted, 15))
        self._update_button.clicked.connect(self._check_updates)
        self._update_label = self._muted_label("")
        system.add_row(None, self._update_button)
        system.add_row(None, self._update_label)

        engine = Section(i18n.tr("panel_model"))
        self._quantization = self._combo(
            engine, "settings_model_quality", "model_quantization",
            [(asr.QUANTIZATION_INT8, i18n.tr("settings_model_int8")),
             (asr.QUANTIZATION_FULL, i18n.tr("settings_model_full"))],
        )

        providers = asr.available_providers()
        compute_options = [("auto", i18n.tr("settings_compute_auto"))]
        if "CUDAExecutionProvider" in providers:
            compute_options.append(("cuda", i18n.tr("settings_compute_cuda")))
        compute_options.append(("cpu", i18n.tr("settings_compute_cpu")))
        self._compute = self._combo(engine, "settings_compute", "compute_provider",
                                    compute_options)
        engine.add_row("ONNX Runtime", self._muted_label(", ".join(providers) or "-"))
        return _page(system, engine)

    def _text_style_changed(self) -> None:
        value = str(self._text_style.currentData())
        self._draft.update(text_style=value)
        self._text_style_hint.set_text(
            i18n.tr(f"settings_text_style_{value}_hint"))

    # -- updates ------------------------------------------------------

    def _check_updates(self) -> None:
        self._update_label.setText(i18n.tr("update_checking"))
        self._update_button.setEnabled(False)
        # The check is a blocking HTTPS request; letting the label paint
        # first is the difference between "Проверка" and a frozen dialog.
        QTimer.singleShot(0, self._run_update_check)

    def _run_update_check(self) -> None:
        try:
            info = PeriodicChecker().maybe_check(force=True)
        finally:
            self._update_button.setEnabled(True)

        if info is None:
            self._update_label.setText(i18n.tr("update_failed"))
        elif not info.is_newer:
            self._update_label.setText(i18n.tr("update_none"))
        elif not info.has_windows_asset:
            # Nothing to install, so nothing to open: the page would only
            # offer a build for another platform.
            self._update_label.setText(
                f"{i18n.tr('update_available', version=info.version)}, "
                f"{i18n.tr('update_no_windows_build')}"
            )
        else:
            # The check was asked for by hand, and what follows a found
            # update is always the same page. Opening it here saves the
            # step; the label still says what was found, in case the
            # browser opens behind this window.
            opened = QDesktopServices.openUrl(QUrl(info.page_url))
            self._update_label.setText(i18n.tr(
                "update_opened" if opened else "update_available",
                version=info.version))

    # -- widget helpers -----------------------------------------------

    def _muted_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Caption")
        label.setWordWrap(True)
        return label

    def _color_row(self, section: Section, label_key: str, draft_key: str,
                   fallback: AccentColor,
                   hint: Optional[str] = None) -> ColorField:
        spec = ColorSpec.parse(self._draft.get(draft_key), ColorSpec.of(fallback))
        field = ColorField(spec,
                           lambda value, k=draft_key: self._draft.update({k: value}),
                           self._palette)
        section.add_row(i18n.tr(label_key), field,
                        HintIcon(hint) if hint else None)
        return field

    def _shortcut_row(self, section: Section, label_key: str,
                      draft_key: str) -> QPushButton:
        choice = HotkeyChoice.from_json(self._draft[draft_key],
                                        getattr(self._settings, draft_key))
        button = QPushButton(hotkey_name(choice, i18n.language()))
        button.setIcon(icons.icon("keyboard", self._palette.text_muted, 15))
        button.clicked.connect(lambda: self._record_shortcut(draft_key, button))
        section.add_row(i18n.tr(label_key), button)
        return button

    def _record_shortcut(self, draft_key: str, button: QPushButton) -> None:
        current = HotkeyChoice.from_json(self._draft[draft_key],
                                         getattr(self._settings, draft_key))
        # Global dictation must not fire from keys typed into the recorder.
        self._controller.listener.paused = True
        try:
            dialog = ShortcutRecorderDialog(current, self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected:
                self._draft[draft_key] = dialog.selected.to_json()
                button.setText(hotkey_name(dialog.selected, i18n.language()))
        finally:
            self._controller.listener.paused = False
            self._controller.listener.reset_state()

    def _combo(self, section: Section, label_key: str, draft_key: str,
               options: list[tuple[str, str]],
               hint: Optional[str] = None) -> QComboBox:
        combo = QComboBox()
        for value, label in options:
            combo.addItem(label, value)
        current = str(self._draft.get(draft_key, ""))
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _, c=combo, k=draft_key: self._draft.update({k: c.currentData()}))
        section.add_row(i18n.tr(label_key), combo,
                        HintIcon(hint) if hint else None)
        return combo

    def _checkbox(self, section: Section, label_key: str, draft_key: str,
                  hint: Optional[str] = None) -> QCheckBox:
        box = QCheckBox(i18n.tr(label_key))
        box.setChecked(bool(self._draft.get(draft_key)))
        box.toggled.connect(lambda value, k=draft_key: self._draft.update({k: value}))
        section.add_row(None, box, HintIcon(hint) if hint else None)
        return box

    # -- filler words -------------------------------------------------

    def _filler_row(self, section: Section) -> QCheckBox:
        """The switch, plus a list of words folded away behind an arrow.

        The old row named two English sounds in its label and offered
        nothing else: "Убирать слова-паразиты (um, uh)". What it actually
        removed was six English interjections, which is close to useless
        for dictation in Russian. The words are now a list you can see and
        change — but they stay folded, because thirty checkboxes unfolded
        by default would bury every setting under them.
        """
        master = QCheckBox(i18n.tr("settings_remove_fillers"))
        master.setChecked(bool(self._draft.get("remove_filler_words")))
        master.toggled.connect(
            lambda value: self._draft.update(remove_filler_words=value))

        self._filler_toggle = QPushButton(i18n.tr("settings_fillers_list"))
        self._filler_toggle.setObjectName("Link")
        self._filler_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filler_toggle.clicked.connect(self._toggle_filler_panel)

        header = QWidget()
        header.setObjectName("Plain")
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(master)
        row.addWidget(self._filler_toggle)
        row.addStretch(1)
        section.add_row(None, header)

        self._filler_panel = QWidget()
        self._filler_panel.setObjectName("Plain")
        panel = QVBoxLayout(self._filler_panel)
        panel.setContentsMargins(0, 2, 0, 4)
        panel.setSpacing(8)
        note = QLabel(i18n.tr("settings_fillers_note"))
        note.setObjectName("Caption")
        note.setWordWrap(True)
        panel.addWidget(note)

        self._filler_grid = QGridLayout()
        self._filler_grid.setHorizontalSpacing(12)
        self._filler_grid.setVerticalSpacing(4)
        panel.addLayout(self._filler_grid)

        adder = QHBoxLayout()
        adder.setContentsMargins(0, 0, 0, 0)
        adder.setSpacing(8)
        self._filler_input = QLineEdit()
        self._filler_input.setPlaceholderText(i18n.tr("settings_fillers_add"))
        self._filler_input.returnPressed.connect(self._add_filler_word)
        add = QPushButton(i18n.tr("corrections_add"))
        add.setIcon(icons.icon("plus", self._palette.text_muted, 15))
        add.clicked.connect(self._add_filler_word)
        adder.addWidget(self._filler_input, 1)
        adder.addWidget(add)
        panel.addLayout(adder)

        self._filler_panel.setVisible(False)
        section.add_row(None, self._filler_panel)

        stored = [str(word) for word in self._draft.get("filler_words") or []]
        self._filler_enabled = {word.lower() for word in stored}
        known = {word for word, _ in PRESET_FILLERS}
        self._filler_custom = [word for word in stored
                               if word.lower() not in known]
        self._rebuild_filler_grid()
        self._update_filler_toggle()

        master.toggled.connect(self._filler_panel.setEnabled)
        self._filler_panel.setEnabled(master.isChecked())
        return master

    def _toggle_filler_panel(self) -> None:
        # isHidden, not isVisible: a widget on a tab that is not the current
        # one is not visible either, and asking the wrong question there
        # makes the first click on the arrow do nothing.
        self._filler_panel.setVisible(self._filler_panel.isHidden())
        self._update_filler_toggle()
        # The dialog is fixed-height until something asks it not to be, so
        # unfolding into a scroll area needs the layout re-run.
        self._filler_panel.updateGeometry()

    def _update_filler_toggle(self) -> None:
        expanded = not self._filler_panel.isHidden()
        self._filler_toggle.setIcon(icons.icon(
            "chevron-down" if expanded else "chevron-right",
            self._palette.text_muted, 14))
        self._filler_toggle.setText(i18n.tr(
            "settings_fillers_list_count", count=len(self._filler_enabled)))

    def _rebuild_filler_grid(self) -> None:
        while self._filler_grid.count():
            item = self._filler_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        words = [word for word, _ in PRESET_FILLERS] + self._filler_custom
        custom = {word.lower() for word in self._filler_custom}
        # Four across: the words are short, and three columns made the list
        # thirteen rows tall, which is most of the dialog for one setting.
        columns = 4
        for index, word in enumerate(words):
            box = QCheckBox(word)
            box.setChecked(word.lower() in self._filler_enabled)
            box.toggled.connect(
                lambda value, w=word: self._set_filler_enabled(w, value))
            if word.lower() in custom:
                cell = QWidget()
                cell.setObjectName("Plain")
                line = QHBoxLayout(cell)
                line.setContentsMargins(0, 0, 0, 0)
                line.setSpacing(4)
                drop = QPushButton()
                drop.setObjectName("Link")
                drop.setIcon(icons.icon("close", self._palette.text_faint, 12))
                drop.setCursor(Qt.CursorShape.PointingHandCursor)
                drop.setToolTip(i18n.tr("corrections_remove"))
                drop.clicked.connect(lambda _=False, w=word: self._drop_filler_word(w))
                line.addWidget(box)
                line.addWidget(drop)
                line.addStretch(1)
                widget: QWidget = cell
            else:
                widget = box
            self._filler_grid.addWidget(widget, index // columns, index % columns)

    def _set_filler_enabled(self, word: str, enabled: bool) -> None:
        if enabled:
            self._filler_enabled.add(word.lower())
        else:
            self._filler_enabled.discard(word.lower())
        self._store_filler_words()
        self._update_filler_toggle()

    def _add_filler_word(self) -> None:
        word = " ".join(self._filler_input.text().split()).lower()
        self._filler_input.clear()
        known = {w.lower() for w, _ in PRESET_FILLERS} | {
            w.lower() for w in self._filler_custom}
        if not word:
            return
        if word not in known:
            self._filler_custom.append(word)
        # A word typed in is a word wanted: adding it also ticks it, and
        # typing one that is already on the list ticks that one instead of
        # silently doing nothing.
        self._filler_enabled.add(word)
        self._store_filler_words()
        self._rebuild_filler_grid()
        self._update_filler_toggle()

    def _drop_filler_word(self, word: str) -> None:
        self._filler_custom = [w for w in self._filler_custom
                               if w.lower() != word.lower()]
        self._filler_enabled.discard(word.lower())
        self._store_filler_words()
        self._rebuild_filler_grid()
        self._update_filler_toggle()

    def _store_filler_words(self) -> None:
        """Saved in list order, presets first, so the file stays readable."""
        words = [word for word, _ in PRESET_FILLERS] + self._filler_custom
        self._draft.update(filler_words=[
            word for word in words if word.lower() in self._filler_enabled])

    def _add_correction_item(self, correction: Correction) -> None:
        item = QListWidgetItem()
        item.setData(PRIMARY_ROLE, correction.source)
        item.setData(SECONDARY_ROLE, correction.replacement)
        item.setData(Qt.ItemDataRole.UserRole, correction)
        item.setToolTip(f"{correction.source} → {correction.replacement}")
        self._corrections_list.addItem(item)

    def _add_correction(self) -> None:
        source = self._correction_source.text().strip()
        replacement = self._correction_replacement.text().strip()
        if not source or not replacement:
            return
        self._add_correction_item(Correction(source, replacement))
        self._correction_source.clear()
        self._correction_replacement.clear()

    def _remove_correction(self) -> None:
        for item in self._corrections_list.selectedItems():
            self._corrections_list.takeItem(self._corrections_list.row(item))

    # -- save ---------------------------------------------------------

    def _save(self) -> None:
        previous = self._settings.snapshot()
        self._settings.apply(self._draft)

        items = [self._corrections_list.item(index).data(Qt.ItemDataRole.UserRole)
                 for index in range(self._corrections_list.count())]
        self._corrections.replace_all(items)

        self._controller.apply_settings()

        model_changed = (
            previous.get("model_quantization") != self._draft.get("model_quantization")
            or previous.get("compute_provider") != self._draft.get("compute_provider")
        )
        if model_changed:
            self._controller.reload_model()
        self.accept()
