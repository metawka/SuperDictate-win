"""Built-in checks, the counterpart of ``Parakey --self-test all``.

Everything here is pure logic: no microphone, no keyboard hook, no model,
no Qt. That is deliberate — these are the parts a port is most likely to
get subtly wrong, and they are the parts that can be verified on a
headless runner.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .hotkeys import (
    MOD_ALT,
    MOD_CTRL,
    MOD_SHIFT,
    VK_ESCAPE,
    VK_LCONTROL,
    VK_RCONTROL,
    VK_RMENU,
    VK_RSHIFT,
    Action,
    HotkeyChoice,
    HotkeyStateMachine,
    TriggerMode,
    _Event,
    _is_modifier_prefix,
)
from .settings import Correction
from .textproc import (
    apply_corrections,
    process_transcript,
    remove_filler_words,
    repair_model_text,
)

_failures: list[str] = []


def _check(name: str, actual, expected) -> None:
    if actual != expected:
        _failures.append(f"{name}\n    expected: {expected!r}\n    actual:   {actual!r}")


# -- hotkey state machine -------------------------------------------------

HOTKEY = HotkeyChoice(VK_RCONTROL)
ENTER_HOTKEY = HotkeyChoice(VK_RCONTROL, MOD_ALT)
HISTORY_HOTKEY = HotkeyChoice(VK_RCONTROL, MOD_SHIFT)


def _machine() -> HotkeyStateMachine:
    return HotkeyStateMachine()


def _feed(machine, vk, down, modifiers, *, mode=TriggerMode.TOGGLE,
          recording=False, can_start=True, repeat=False):
    return machine.transition(
        _Event(vk=vk, is_down=down, modifiers=modifiers, is_repeat=repeat),
        hotkey=HOTKEY,
        enter_hotkey=ENTER_HOTKEY,
        alternate_completion_enabled=True,
        history_hotkey=HISTORY_HOTKEY,
        trigger_mode=mode,
        is_recording=recording,
        can_start_recording=can_start,
    )


def test_toggle_starts_and_stops() -> None:
    machine = _machine()
    first = _feed(machine, VK_RCONTROL, True, MOD_CTRL)
    _check("toggle: first press starts", first.actions, [Action.PRESS])
    _check("toggle: press is suppressed", first.suppress, True)

    _feed(machine, VK_RCONTROL, False, 0, recording=True)
    second = _feed(machine, VK_RCONTROL, True, MOD_CTRL, recording=True)
    _check("toggle: second press stops", second.actions, [Action.RELEASE])


def test_toggle_does_not_flip_when_busy() -> None:
    machine = _machine()
    busy = _feed(machine, VK_RCONTROL, True, MOD_CTRL, can_start=False)
    _check("toggle: busy press is rejected", busy.actions, [Action.REJECTED_BUSY_PRESS])
    _feed(machine, VK_RCONTROL, False, 0, can_start=False)
    # The rejected press must not have flipped the toggle, so the next
    # press still starts rather than emitting a discarded release.
    ready = _feed(machine, VK_RCONTROL, True, MOD_CTRL)
    _check("toggle: next press still starts", ready.actions, [Action.PRESS])


def test_hold_press_and_release() -> None:
    machine = _machine()
    press = _feed(machine, VK_RCONTROL, True, MOD_CTRL, mode=TriggerMode.HOLD)
    _check("hold: press", press.actions, [Action.PRESS])
    release = _feed(machine, VK_RCONTROL, False, 0, mode=TriggerMode.HOLD, recording=True)
    _check("hold: release", release.actions, [Action.RELEASE])


def test_left_control_does_not_trigger() -> None:
    machine = _machine()
    result = _feed(machine, VK_LCONTROL, True, MOD_CTRL)
    _check("left control passes through", (result.suppress, result.actions), (False, []))


def test_alternate_finish_needs_recording() -> None:
    machine = _machine()
    idle = _feed(machine, VK_RMENU, True, MOD_ALT)
    _check("alternate: ignored while idle", idle.actions, [])

    machine = _machine()
    _feed(machine, VK_RMENU, True, MOD_ALT, recording=True)
    result = _feed(machine, VK_RCONTROL, True, MOD_ALT | MOD_CTRL, recording=True)
    _check("alternate: chord finishes recording", result.actions,
           [Action.RELEASE_ALTERNATE])


def test_history_chord() -> None:
    machine = _machine()
    _feed(machine, VK_RSHIFT, True, MOD_SHIFT)
    result = _feed(machine, VK_RCONTROL, True, MOD_SHIFT | MOD_CTRL)
    _check("history: chord opens history", result.actions, [Action.SHOW_HISTORY])


def test_escape_cancels_only_while_recording() -> None:
    machine = _machine()
    idle = _feed(machine, VK_ESCAPE, True, 0)
    _check("escape: passes through when idle", (idle.suppress, idle.actions), (False, []))

    machine = _machine()
    active = _feed(machine, VK_ESCAPE, True, 0, recording=True)
    _check("escape: cancels while recording", active.actions, [Action.CANCEL])


def test_modifiers_are_never_swallowed() -> None:
    """Regression: the history chord must not cost the user the Shift key.

    History is "Shift + Right Ctrl", so Shift belongs to a shortcut — but
    suppressing it would break capital letters and Shift-click everywhere
    until the app quits. Only the chord's primary key may be eaten.
    """
    from .hotkeys import VK_LSHIFT, VK_RMENU

    for name, vk, mask in (("left shift", VK_LSHIFT, MOD_SHIFT),
                           ("right shift", VK_RSHIFT, MOD_SHIFT),
                           ("right alt", VK_RMENU, MOD_ALT)):
        machine = _machine()
        down = _feed(machine, vk, True, mask)
        _check(f"{name} down reaches the app", down.suppress, False)
        up = _feed(machine, vk, False, 0)
        _check(f"{name} up reaches the app", up.suppress, False)

    # Even mid-chord: Shift goes through, only Right Ctrl is eaten.
    machine = _machine()
    shift = _feed(machine, VK_RSHIFT, True, MOD_SHIFT)
    _check("shift before the chord passes", shift.suppress, False)
    chord = _feed(machine, VK_RCONTROL, True, MOD_SHIFT | MOD_CTRL)
    _check("chord primary is suppressed", chord.suppress, True)
    _check("chord opens history", chord.actions, [Action.SHOW_HISTORY])
    release = _feed(machine, VK_RSHIFT, False, 0)
    _check("shift release still reaches the app", release.suppress, False)


def test_modifier_prefix_detection() -> None:
    from .hotkeys import VK_LMENU

    # The default pair is not a prefix relationship: Ctrl is the chord's
    # primary key, not one of its required modifiers.
    _check("prefix: default shortcuts coexist",
           _is_modifier_prefix(HOTKEY, ENTER_HOTKEY), False)
    # But a bare Alt hotkey would fire on the way into "Alt + Right Ctrl".
    _check("prefix: bare Alt shadows an Alt chord",
           _is_modifier_prefix(HotkeyChoice(VK_LMENU), ENTER_HOTKEY), True)
    _check("prefix: a chord is never a prefix",
           _is_modifier_prefix(HotkeyChoice(VK_RMENU, MOD_SHIFT), ENTER_HOTKEY), False)


# -- transcript processing ------------------------------------------------


def test_unk_repair() -> None:
    _check("unk: russian yo", repair_model_text("ещ<unk>", "ru"), "ещё")
    _check("unk: capital after sentence end",
           repair_model_text("Да. <unk>лка", "ru"), "Да. Ёлка")
    _check("unk: dropped for latin languages",
           repair_model_text("hello <unk> world", "en"), "hello world")


def test_corrections() -> None:
    corrections = [Correction("гит хаб", "GitHub"), Correction("гит", "git")]
    text, count = apply_corrections("открой гит хаб и гит статус", corrections)
    _check("corrections: longest match wins", text, "открой GitHub и git статус")
    _check("corrections: count", count, 2)

    text, _ = apply_corrections("подгитовка", corrections)
    _check("corrections: respects word boundaries", text, "подгитовка")


def test_filler_removal() -> None:
    text, count = remove_filler_words("Um, hello uh world.")
    _check("fillers: removed and repunctuated", text, "Hello world.")
    _check("fillers: count", count, 2)

    text, _ = remove_filler_words("I did err on the side of caution")
    _check("fillers: 'err' survives", text, "I did err on the side of caution")

    text, _ = remove_filler_words("uh-huh, sure")
    _check("fillers: hyphenated interjections survive", text, "uh-huh, sure")


def test_pipeline_order() -> None:
    # An explicit correction must win over filler stripping.
    text, applied, removed = process_transcript(
        "um, ГитХаб",
        language="ru",
        corrections=[Correction("ГитХаб", "GitHub")],
        strip_fillers=True,
    )
    _check("pipeline: correction applied", "GitHub" in text, True)
    _check("pipeline: filler removed", removed, 1)
    _check("pipeline: correction counted", applied, 1)


# -- settings round trip --------------------------------------------------


def test_settings_round_trip() -> None:
    from .settings import Settings

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "Settings.json"
        settings = Settings(path)
        settings.apply({
            "hotkey": HotkeyChoice(VK_RSHIFT, MOD_CTRL).to_json(),
            "enter_delay_milliseconds": 9000,   # out of range, must clamp
            "interface_language": "en",
            "unknown_key": "ignored",
        })

        reloaded = Settings(path)
        _check("settings: hotkey persisted", reloaded.hotkey,
               HotkeyChoice(VK_RSHIFT, MOD_CTRL))
        _check("settings: enter delay clamped", reloaded.enter_delay_milliseconds, 500)
        _check("settings: language persisted", reloaded.interface_language, "en")
        _check("settings: unknown keys dropped",
               "unknown_key" in reloaded.snapshot(), False)


def test_hotkey_json_guards() -> None:
    fallback = HotkeyChoice(VK_RCONTROL)
    _check("hotkey json: escape rejected",
           HotkeyChoice.from_json({"vk": VK_ESCAPE}, fallback), fallback)
    _check("hotkey json: garbage rejected",
           HotkeyChoice.from_json("nonsense", fallback), fallback)
    _check("hotkey json: self-modifier stripped",
           HotkeyChoice.from_json({"vk": VK_RCONTROL, "modifiers": MOD_CTRL}, fallback),
           HotkeyChoice(VK_RCONTROL, 0))


# -- runner ---------------------------------------------------------------

_TESTS = [
    test_toggle_starts_and_stops,
    test_toggle_does_not_flip_when_busy,
    test_hold_press_and_release,
    test_left_control_does_not_trigger,
    test_alternate_finish_needs_recording,
    test_history_chord,
    test_escape_cancels_only_while_recording,
    test_modifiers_are_never_swallowed,
    test_modifier_prefix_detection,
    test_unk_repair,
    test_corrections,
    test_filler_removal,
    test_pipeline_order,
    test_settings_round_trip,
    test_hotkey_json_guards,
]


def run_all() -> bool:
    _failures.clear()
    errored = 0
    for test in _TESTS:
        try:
            test()
        except Exception as exc:  # a crashing test is a failing test
            errored += 1
            _failures.append(f"{test.__name__} raised {type(exc).__name__}: {exc}")

    if _failures:
        print(f"FAILED — {len(_failures)} problem(s) in {len(_TESTS)} tests\n")
        for failure in _failures:
            print(f"  * {failure}")
        return False
    print(f"OK — {len(_TESTS)} self-tests passed")
    return True
