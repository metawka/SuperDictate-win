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

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
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
    QVBoxLayout,
    QWidget,
)

from .. import asr, audio, i18n
from ..hotkeys import HotkeyChoice, TriggerMode
from ..keynames import hotkey_name
from ..settings import (
    DICTATION_LANGUAGES,
    AccentColor,
    CompletionBehavior,
    Correction,
    HUDBackground,
    HUDSize,
    PasteSuffix,
    Settings,
    TextStyle,
)
from . import icons
from .recorder import ShortcutRecorderDialog
from .theme import palette, stylesheet


class Section(QWidget):
    """A titled card holding a two-column grid of settings."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 13, 16, 14)
        outer.setSpacing(10)

        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        outer.addWidget(heading)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(10)
        self.grid.setColumnStretch(1, 1)
        outer.addLayout(self.grid)
        self._row = 0

    def add_row(self, label: Optional[str], widget: QWidget) -> None:
        if label:
            key = QLabel(label)
            key.setObjectName("Key")
            self.grid.addWidget(key, self._row, 0)
            self.grid.addWidget(widget, self._row, 1)
        else:
            self.grid.addWidget(widget, self._row, 0, 1, 2)
        self._row += 1

    def add_caption(self, text: str) -> None:
        caption = QLabel(text)
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        self.grid.addWidget(caption, self._row, 0, 1, 2)
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

        note = QLabel(i18n.tr("settings_draft_note"))
        note.setObjectName("Caption")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText(i18n.tr("settings_save_restart"))
        save.setObjectName("Primary")
        save.setIcon(icons.icon("check", "#ffffff", 16))
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
        self._text_style = self._combo(
            recognition, "settings_text_style", "text_style",
            [(TextStyle.FORMAL.value, i18n.tr("settings_text_style_formal")),
             (TextStyle.STANDARD.value, i18n.tr("settings_text_style_standard")),
             (TextStyle.INFORMAL.value, i18n.tr("settings_text_style_informal"))],
        )
        recognition.add_caption(i18n.tr("settings_text_style_hint"))
        self._fillers = self._checkbox(
            recognition, "settings_remove_fillers", "remove_filler_words")

        capture = Section(i18n.tr("settings_section_capture"))
        devices = [("", i18n.tr("settings_device_default"))]
        devices += [(device.name, device.name) for device in audio.list_input_devices()]
        self._device = self._combo(
            capture, "settings_input_device", "input_device", devices)

        self._stop_on_silence = self._checkbox(
            capture, "settings_stop_on_silence", "stop_on_silence")
        self._silence_seconds = QDoubleSpinBox()
        self._silence_seconds.setRange(1.0, 10.0)
        self._silence_seconds.setSingleStep(0.5)
        self._silence_seconds.setDecimals(1)
        self._silence_seconds.setValue(float(self._draft.get("silence_stop_seconds", 2.5)))
        self._silence_seconds.valueChanged.connect(
            lambda value: self._draft.update(silence_stop_seconds=value))
        self._silence_seconds.setEnabled(bool(self._draft.get("stop_on_silence")))
        self._stop_on_silence.toggled.connect(self._silence_seconds.setEnabled)
        capture.add_row(i18n.tr("settings_silence_seconds"), self._silence_seconds)
        capture.add_caption(i18n.tr("settings_stop_on_silence_hint"))

        self._mute = self._checkbox(capture, "settings_mute", "mute_while_recording")
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
        colors = [(color.value, i18n.tr(f"color_{color.value}"))
                  for color in AccentColor]
        self._hud_recording = self._combo(
            hud, "settings_hud_recording_color", "hud_recording_color", colors)
        self._hud_transcribing = self._combo(
            hud, "settings_hud_transcribing_color", "hud_transcribing_color", colors)
        self._hud_background = self._combo(
            hud, "settings_hud_background", "hud_background_style",
            [(HUDBackground.SYSTEM.value, i18n.tr("settings_hud_background_system")),
             (HUDBackground.DARK.value, i18n.tr("settings_hud_background_dark")),
             (HUDBackground.LIGHT.value, i18n.tr("settings_hud_background_light"))],
        )
        self._colorize_combo(self._hud_recording)
        self._colorize_combo(self._hud_transcribing)
        return _page(general, hud)

    def _build_corrections_tab(self) -> QWidget:
        section = Section(i18n.tr("settings_tab_corrections"))
        section.add_caption(i18n.tr("corrections_note"))

        self._corrections_list = QListWidget()
        self._corrections_list.setIconSize(icons.icon_size(14))
        self._corrections_list.setMinimumHeight(220)
        for correction in self._corrections.all():
            self._add_correction_item(correction)
        section.add_row(None, self._corrections_list)

        editor = QWidget()
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

    # -- widget helpers -----------------------------------------------

    def _muted_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Caption")
        label.setWordWrap(True)
        return label

    def _colorize_combo(self, combo: QComboBox) -> None:
        """Show the accent colours as swatches, not just their names."""
        for index in range(combo.count()):
            value = combo.itemData(index)
            try:
                color = AccentColor(value)
            except ValueError:
                continue
            combo.setItemIcon(index, icons.swatch(color.hex, 13))

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
               options: list[tuple[str, str]]) -> QComboBox:
        combo = QComboBox()
        for value, label in options:
            combo.addItem(label, value)
        current = str(self._draft.get(draft_key, ""))
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _, c=combo, k=draft_key: self._draft.update({k: c.currentData()}))
        section.add_row(i18n.tr(label_key), combo)
        return combo

    def _checkbox(self, section: Section, label_key: str, draft_key: str) -> QCheckBox:
        box = QCheckBox(i18n.tr(label_key))
        box.setChecked(bool(self._draft.get(draft_key)))
        box.toggled.connect(lambda value, k=draft_key: self._draft.update({k: value}))
        section.add_row(None, box)
        return box

    def _add_correction_item(self, correction: Correction) -> None:
        item = QListWidgetItem(f"{correction.source}  →  {correction.replacement}")
        item.setIcon(icons.icon("replace", self._palette.text_faint, 14))
        item.setData(Qt.ItemDataRole.UserRole, correction)
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
