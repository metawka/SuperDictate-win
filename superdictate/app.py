"""Application orchestration: the dictation state machine.

Everything the macOS ``AppDelegate`` coordinates lives here, the hotkey
listener, the recorder, the transcription worker, the HUD, the tray and
the windows, with one structural difference. macOS splits the product
into a background LaunchAgent plus a separate control panel process that
talk through a status file. On Windows a single process owns the keyboard
hook and the UI, and closing the control panel just hides a window; the
tray icon is what keeps the service alive. A named mutex replaces the PID
file so a second launch surfaces the running instance.

Thread layout:

* **Hook thread**, decodes hotkeys, never blocks (see :mod:`hotkeys`).
* **Qt thread**, all UI, plus recorder start/stop.
* **Model thread**, one worker draining a queue, so a second dictation
  started while the first is still transcribing simply queues up.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal

from . import asr, audio, i18n, inject, system, textproc
from .history import Corrections, History, HistoryEntry, UsageStats
from .hotkeys import Action, HotkeyListener
from .logging_setup import get as get_logger
from .settings import CompletionBehavior, Settings

log = get_logger("app")

# Live preview. The model is not a streaming one: each pass re-reads the
# audio from the start, so the cost grows with the length of the dictation
# and the interval has to grow with it. PREVIEW_DUTY is the share of one
# core the preview is allowed to keep busy; the rest of the time it waits.
PREVIEW_FIRST_DELAY = 1.0
PREVIEW_MIN_INTERVAL = 0.7
PREVIEW_MIN_AUDIO_SECONDS = 0.6
PREVIEW_WINDOW_SECONDS = 30.0
PREVIEW_DUTY = 0.5


class AppState(str, Enum):
    STARTING = "starting"
    DOWNLOADING = "downloading"
    LOADING = "loading"
    READY = "ready"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    FAILED = "failed"


@dataclass
class _Job:
    samples: np.ndarray
    behavior: CompletionBehavior
    enqueued_at: float
    recovered: bool = False


class DictationController(QObject):
    """Owns the dictation lifecycle and emits UI-facing signals."""

    state_changed = Signal(str)            # AppState value
    progress_changed = Signal(object)      # asr.Progress
    level_changed = Signal(float)
    preview_changed = Signal(str)         # partial text while recording
    transcript_ready = Signal(str)
    # Something is wrong with the machine, not with what was said: no
    # microphone, no keyboard hook, no model. These outlive the moment and
    # go to the Windows notification centre.
    error_raised = Signal(str)
    # The dictation itself came to nothing. Reported on the capsule, which
    # the user is already looking at, and gone a few seconds later.
    # Carries (icon name, message).
    dictation_failed = Signal(str, str)
    history_toggle_requested = Signal()
    settings_applied = Signal()

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.history = History()
        self.usage = UsageStats()
        self.corrections = Corrections()
        self.sounds = system.Sounds(settings.play_feedback_sounds)
        self.output_mute = system.OutputMute()

        self._state = AppState.STARTING
        self._state_lock = threading.Lock()
        self._jobs: "queue.Queue[Optional[_Job]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._model: Optional[asr.SpeechModel] = None
        self._preview_stop: Optional[threading.Event] = None
        self._terminating = False
        self.last_error: str = ""

        self.recorder = audio.Recorder(
            on_level=self._on_level,
            on_auto_stop=self._on_auto_stop,
        )
        self.recorder.silence_stop_enabled = self.settings.stop_on_silence
        self.recorder.silence_stop_seconds = self.settings.silence_stop_seconds
        self.listener = HotkeyListener(self._on_hotkey_actions)
        self._apply_hotkey_settings()
        self.listener.is_recording_active = lambda: self.state is AppState.RECORDING
        self.listener.can_start_recording = self._can_start_recording

        # Hook-thread callbacks are marshalled onto the Qt thread through
        # this queued signal; touching widgets from the hook thread would
        # be both a Qt violation and a hook-timeout risk.
        self._action_bridge = _ActionBridge()
        self._action_bridge.actions.connect(self._handle_actions,
                                            Qt.ConnectionType.QueuedConnection)

    # -- state --------------------------------------------------------

    @property
    def state(self) -> AppState:
        with self._state_lock:
            return self._state

    def _set_state(self, state: AppState) -> None:
        with self._state_lock:
            if self._state is state:
                return
            self._state = state
        self.state_changed.emit(state.value)

    def _can_start_recording(self) -> bool:
        return self.state is AppState.READY and not self._terminating

    # -- startup / shutdown -------------------------------------------

    def start(self) -> None:
        # A previous run killed from Task Manager can leave the foreground
        # app convinced a modifier is still down. Correct that before the
        # hook goes in, while nothing of ours is suppressing anything.
        stray = inject.clear_stuck_modifiers()
        if stray:
            log.debug("Cleared %d stray modifier(s) left over from a previous run",
                      len(stray))

        self.listener.start()
        if not self.listener.installed:
            log.error("Keyboard hook could not be installed")
            self.error_raised.emit(i18n.tr("error_hook"))

        self._worker = threading.Thread(target=self._worker_loop,
                                        name="transcription-worker", daemon=True)
        self._worker.start()
        threading.Thread(target=self._prepare_model, name="model-loader",
                         daemon=True).start()

    def shutdown(self) -> None:
        self._terminating = True
        self._stop_preview()
        try:
            if self.recorder.is_recording:
                self.recorder.discard()
        finally:
            self.output_mute.restore()
        self.listener.stop()
        self._jobs.put(None)
        if self._worker is not None:
            self._worker.join(timeout=3.0)
        if self._model is not None:
            self._model.unload()

    def _prepare_model(self) -> None:
        model = asr.SpeechModel(
            quantization=self.settings.model_quantization,
            compute_provider=self.settings.compute_provider,
        )
        self._model = model

        def on_progress(progress: asr.Progress) -> None:
            self.progress_changed.emit(progress)
            if progress.state is asr.State.DOWNLOADING:
                self._set_state(AppState.DOWNLOADING)
            elif progress.state is asr.State.LOADING:
                self._set_state(AppState.LOADING)

        if model.prepare(on_progress):
            self._set_state(AppState.READY)
            self._recover_pending_dictation()
        else:
            self.last_error = model.error or "unknown error"
            self._set_state(AppState.FAILED)
            self.error_raised.emit(self.last_error)

    def _recover_pending_dictation(self) -> None:
        """Transcribe audio a crash left behind, into history only.

        macOS restores the unfinished recording so the words are not lost;
        pasting it into whatever happens to be focused now would be worse
        than useless, so the recovered text goes to history and the user
        re-inserts it from there.
        """
        samples = audio.read_pending_dictation()
        audio.clear_pending_dictation()
        if samples is None:
            return
        log.info("Recovering %.1fs of audio from an interrupted session",
                 len(samples) / audio.SAMPLE_RATE)
        self._jobs.put(_Job(samples, self.settings.primary_completion_behavior,
                            time.monotonic(), recovered=True))

    # -- settings -----------------------------------------------------

    def apply_settings(self) -> None:
        """Re-read every live-adjustable preference. The macOS panel calls
        this "Save and restart"; nothing here needs a process restart
        except a model change, which reloads on its own."""
        self._apply_hotkey_settings()
        self.recorder.silence_stop_enabled = self.settings.stop_on_silence
        self.recorder.silence_stop_seconds = self.settings.silence_stop_seconds
        self.sounds.enabled = self.settings.play_feedback_sounds
        i18n.set_language(self.settings.interface_language)
        system.set_autostart(self.settings.start_at_login)
        self.settings_applied.emit()

    def _apply_hotkey_settings(self) -> None:
        self.listener.hotkey = self.settings.hotkey
        self.listener.history_hotkey = self.settings.history_hotkey
        self.listener.trigger_mode = self.settings.trigger_mode
        self.listener.reset_state()

    def reload_model(self) -> None:
        """Swap weights or compute device without restarting the app."""
        if self._model is not None:
            self._model.unload()
        self._set_state(AppState.STARTING)
        threading.Thread(target=self._prepare_model, name="model-loader",
                         daemon=True).start()

    # -- hotkey plumbing ----------------------------------------------

    def _on_hotkey_actions(self, actions) -> None:
        self._action_bridge.actions.emit([action.value for action in actions])

    def _handle_actions(self, action_values: list[str]) -> None:
        for value in action_values:
            action = Action(value)
            if action is Action.PRESS:
                self.begin_recording()
            elif action is Action.RELEASE:
                self.finish_recording(self.settings.primary_completion_behavior)
            elif action is Action.CANCEL:
                self.cancel_recording()
            elif action is Action.SHOW_HISTORY:
                self.history_toggle_requested.emit()
            elif action is Action.REJECTED_BUSY_PRESS:
                self.sounds.play("rejected")

    # -- recording ----------------------------------------------------

    def begin_recording(self) -> None:
        if not self._can_start_recording():
            self.sounds.play("rejected")
            return
        if self.settings.mute_while_recording:
            self.output_mute.mute()
        if not self.recorder.start(self.settings.input_device):
            self.output_mute.restore()
            message = self._microphone_error_message(self.recorder.last_error or "")
            self.last_error = message
            self.sounds.play("error")
            self.error_raised.emit(message)
            self.listener.reset_toggle()
            return
        self._set_state(AppState.RECORDING)
        self.sounds.play("start")
        self._start_preview()

    @staticmethod
    def _microphone_error_message(reason: str) -> str:
        """Name the actual cause instead of always blaming permissions."""
        lowered = reason.lower()
        if "denied" in lowered or "access" in lowered or "-9996" in lowered:
            return i18n.tr("error_microphone_denied")
        if "unanticipated host" in lowered or "device unavailable" in lowered:
            return i18n.tr("error_microphone_busy")
        return i18n.tr("error_microphone", reason=reason or "?")

    def finish_recording(self, behavior: CompletionBehavior) -> None:
        if self.state is not AppState.RECORDING:
            return
        self._stop_preview(clear=False)
        samples = self.recorder.stop()
        self.output_mute.restore()
        audio.clear_pending_dictation()
        self.sounds.play("stop")

        duration = len(samples) / audio.SAMPLE_RATE
        if duration < audio.MIN_CLIP_SECONDS:
            log.info("Discarding %.2fs clip (below %.2fs minimum)",
                     duration, audio.MIN_CLIP_SECONDS)
            # Same cleanup as a cancel. Without it the toggle stays flipped
            # on, so the next press emits a discarded .release and the
            # hotkey looks dead until it is pressed a third time.
            self.listener.reset_toggle()
            self._set_state(AppState.READY)
            self.dictation_failed.emit("clock", i18n.tr("error_too_short"))
            return

        self._set_state(AppState.TRANSCRIBING)
        self._jobs.put(_Job(samples, behavior, time.monotonic()))

    def cancel_recording(self) -> None:
        if self.state is not AppState.RECORDING:
            return
        self._stop_preview()
        self.recorder.discard()
        self.output_mute.restore()
        self.listener.reset_toggle()
        self._set_state(AppState.READY)
        log.info("Recording cancelled")

    def _on_level(self, level: float) -> None:
        self.level_changed.emit(level)

    def _on_auto_stop(self) -> None:
        log.info("Auto-stopping after %d minutes", audio.MAX_RECORDING_SECONDS // 60)
        self._action_bridge.actions.emit([Action.RELEASE.value])

    # -- live preview --------------------------------------------------

    def _start_preview(self) -> None:
        if not self.settings.live_preview:
            return
        stop = threading.Event()
        self._preview_stop = stop
        threading.Thread(target=self._preview_loop, args=(stop,),
                         name="live-preview", daemon=True).start()

    def _stop_preview(self, *, clear: bool = True) -> None:
        """End the preview loop. ``clear`` also wipes what it last showed.

        A finished recording keeps its last preview on screen: the words
        are about to be replaced by the real transcription, and blanking
        the bubble for the second or two in between reads as the app
        having thrown the dictation away.
        """
        stop, self._preview_stop = self._preview_stop, None
        if stop is not None:
            stop.set()
            if clear:
                self.preview_changed.emit("")

    def _preview_loop(self, stop: threading.Event) -> None:
        """Re-transcribe the recording so far, over and over, until it ends.

        Only the last :data:`PREVIEW_WINDOW_SECONDS` are read. Beyond that
        a single pass costs more than the interval between passes, and the
        point of the preview is to be roughly current, not complete: the
        real transcription runs on the whole clip when recording stops.
        """
        delay = PREVIEW_FIRST_DELAY
        while not stop.wait(delay):
            if not self.recorder.is_recording:
                return
            model = self._model
            if model is None or not model.is_ready:
                return

            samples = self.recorder.snapshot(PREVIEW_WINDOW_SECONDS)
            if len(samples) < PREVIEW_MIN_AUDIO_SECONDS * audio.SAMPLE_RATE:
                delay = PREVIEW_MIN_INTERVAL
                continue

            outcome = model.transcribe_preview(samples)
            if outcome is None:
                delay = PREVIEW_MIN_INTERVAL
                continue
            raw, inference_seconds = outcome
            if stop.is_set():
                return

            text, _, _ = textproc.process_transcript(
                raw,
                language=self.settings.dictation_language,
                corrections=self.corrections.all(),
                strip_fillers=self.settings.remove_filler_words,
                digits=self.settings.numbers_as_digits,
                style=self.settings.text_style,
            )
            if text and self.recorder.elapsed > PREVIEW_WINDOW_SECONDS:
                text = "… " + text
            self.preview_changed.emit(text)

            delay = max(PREVIEW_MIN_INTERVAL,
                        inference_seconds * (1.0 - PREVIEW_DUTY) / PREVIEW_DUTY)

    # -- transcription worker -----------------------------------------

    def _worker_loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                self._run_job(job)
            except Exception as exc:
                log.exception("Transcription failed")
                self.last_error = str(exc)
                self.sounds.play("error")
                self.error_raised.emit(str(exc))
            finally:
                if not self._terminating:
                    self._set_state(AppState.READY)

    def _run_job(self, job: _Job) -> None:
        model = self._model
        if model is None or not model.is_ready:
            raise RuntimeError("Speech model is not ready")

        result = model.transcribe(job.samples, job.enqueued_at)
        text, applied, removed = textproc.process_transcript(
            result.text,
            language=self.settings.dictation_language,
            corrections=self.corrections.all(),
            strip_fillers=self.settings.remove_filler_words,
            digits=self.settings.numbers_as_digits,
            style=self.settings.text_style,
        )
        log.info(
            "Transcribed %.1fs of audio in %.2fs (RTF %.2f, %d corrections, "
            "%d fillers removed)",
            result.audio_seconds, result.inference_seconds,
            result.realtime_factor, applied, removed,
        )

        if not text:
            self.dictation_failed.emit("mic", i18n.tr("error_no_speech"))
            return

        # The preview stopped a beat before the recording did, so its last
        # words are missing. This is the same sentence, complete.
        if self.settings.live_preview and not job.recovered:
            self.preview_changed.emit(text)

        self.history.add(HistoryEntry(
            text=text,
            created_at=time.time(),
            audio_seconds=result.audio_seconds,
            transcription_seconds=result.inference_seconds,
        ))
        self.usage.record(text, result.audio_seconds)
        self.transcript_ready.emit(text)

        if job.recovered:
            # Recovered audio never auto-pastes; see _recover_pending_dictation.
            return

        payload = text + self.settings.paste_suffix.text
        inject.paste_text(
            payload,
            press_enter=job.behavior.presses_enter,
            enter_delay_ms=self.settings.enter_delay_milliseconds,
        )

    # -- manual insertion (history window) -----------------------------

    def insert_text(self, text: str) -> None:
        inject.paste_text(text + self.settings.paste_suffix.text)


class _ActionBridge(QObject):
    actions = Signal(list)
