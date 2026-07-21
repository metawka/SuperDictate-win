"""Deterministic transcript post-processing.

Straight port of the three passes in ``main.swift``, in the same order the
macOS app applies them:

1. ``SpeechModelTextRepair``: Parakeet TDT v3 emits ``<unk>`` where a
   Russian "ё" belongs; repair it for ru/auto, drop it elsewhere.
2. ``TranscriptCorrector``: the user's replacement dictionary. Runs
   before filler removal so explicit corrections always win.
3. ``FillerWordRemover``: conservative interjection stripping.

Swift's ``NSRegularExpression`` and Python's ``re`` agree on the syntax
used here except for ``\\p{L}``/``\\p{N}``, which Python lacks; the Unicode
character classes below are the equivalent, since Python's ``\\w`` is
already Unicode-aware and ``[^\\W\\d_]`` is exactly "a Unicode letter".
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from .settings import Correction, TextStyle

# `\p{L}\p{N}` in Swift. Python's `\w` == letters + digits + underscore,
# so letters-or-digits is `\w` minus underscore.
_LETTER_OR_DIGIT = r"[^\W_]"

_UNK_TOKEN = "<unk>"


# -- 1. model text repair ------------------------------------------------


def repair_model_text(text: str, language: str = "auto") -> str:
    if _UNK_TOKEN not in text.lower():
        return text

    replace_with_yo = language in ("auto", "ru")
    result: list[str] = []
    index = 0
    lowered = text.lower()
    while index < len(text):
        if lowered.startswith(_UNK_TOKEN, index):
            if replace_with_yo:
                result.append("Ё" if _should_capitalize_yo(result) else "ё")
            index += len(_UNK_TOKEN)
        else:
            result.append(text[index])
            index += 1

    out = "".join(result)
    if not replace_with_yo:
        out = re.sub(r"\s+([.,!?;:])", r"\1", out)
        out = re.sub(r"[ \t]+", " ", out).strip()
    return out


def _should_capitalize_yo(prefix: Iterable[str]) -> bool:
    for char in reversed(list(prefix)):
        if char.isspace():
            continue
        return char in ".!?"
    return True


# -- 2. user corrections -------------------------------------------------


def normalized_corrections(corrections: Sequence[Correction]) -> list[Correction]:
    seen: set[str] = set()
    cleaned: list[Correction] = []
    for correction in corrections:
        source = " ".join(correction.source.split())
        replacement = correction.replacement.strip()
        if not source or not replacement:
            continue
        key = source.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(Correction(source, replacement))
    return cleaned


def _correction_pattern(source: str) -> str | None:
    parts = [re.escape(part) for part in source.split()]
    if not parts:
        return None
    # `_` is excluded from the boundary the same way Swift's
    # `(?<![\p{L}\p{N}_])` does, so `foo_bar` is not a match for `bar`.
    return r"(?<![^\W_]|_)" + r"\s+".join(parts) + r"(?![^\W_]|_)"


def apply_corrections(
    text: str, corrections: Sequence[Correction]
) -> tuple[str, int]:
    active = sorted(
        normalized_corrections(corrections),
        key=lambda c: (-len(c.source), c.source.casefold()),
    )
    if not text or not active:
        return text, 0

    matches: list[tuple[int, int, str]] = []
    for correction in active:
        pattern = _correction_pattern(correction.source)
        if pattern is None:
            continue
        try:
            regex = re.compile(pattern, re.IGNORECASE | re.UNICODE)
        except re.error:
            continue
        for match in regex.finditer(text):
            start, end = match.span()
            # Longest-source-first ordering plus this overlap guard is
            # what makes the result independent of dictionary order.
            if any(start < other_end and other_start < end
                   for other_start, other_end, _ in matches):
                continue
            matches.append((start, end, correction.replacement))

    if not matches:
        return text, 0

    rewritten = text
    for start, end, replacement in sorted(matches, key=lambda m: -m[0]):
        rewritten = rewritten[:start] + replacement + rewritten[end:]
    return rewritten, len(matches)


# -- 3. filler words -----------------------------------------------------

# Non-word interjections only. "like" / "you know" are excluded because
# they have valid non-filler meanings. Trailing-letter repeats are allowed
# because real fillers stretch out ("ummm"); "er"/"erm" deliberately have
# no quantifier so the real word "err" survives.
_FILLER_PATTERNS = ["um+", "uh+", "ah+", "er", "erm", "hm+"]
_FILLER_REGEX = re.compile(
    r"(?<![^\W_]|['\-])(?:" + "|".join(_FILLER_PATTERNS) + r")(?![^\W_]|['\-])",
    re.IGNORECASE | re.UNICODE,
)

_SENTENCE_TERMINATORS = ".!?"
_BOUNDARY_WRAPPERS = "\"'“”‘’([{"
_ORPHAN_SEPARATORS = ",.;:!?"


def remove_filler_words(text: str) -> tuple[str, int]:
    if not text:
        return text, 0
    matches = list(_FILLER_REGEX.finditer(text))
    if not matches:
        return text, 0

    targets = _capitalization_targets(matches, text)

    result = text
    for match in reversed(matches):
        start, end = match.span()
        result = result[:start] + result[end:]

    # Clean up the artifacts removal leaves behind, in the same order as
    # the Swift implementation, the order matters, e.g. pass 3 can glue a
    # comma onto terminal punctuation that pass 4 then has to unglue.
    result = re.sub(r"\s*,(?:\s*,)+", ",", result)
    result = re.sub(r"([.!?])\s+[,.;:!?]+\s*", r"\1 ", result)
    result = re.sub(r"\s+([.,!?;:])", r"\1", result)
    result = re.sub(r",+([.!?;:])", r"\1", result)
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"^[\s,.;:!?]+", "", result)
    result = result.strip()
    result = _restore_capitalization(result, targets)
    return result, len(matches)


def _capitalization_targets(matches, text: str) -> set[object]:
    """Which sentence starts lost their capital to a removed filler.

    ``"start"`` for the very beginning of the text, or the 1-based ordinal
    of the sentence terminator the filler followed.
    """
    targets: set[object] = set()
    for match in matches:
        if not match.group(0)[:1].isupper():
            continue
        target = _capitalization_target(match.start(), text)
        if target is not None:
            targets.add(target)
    return targets


def _capitalization_target(start: int, text: str) -> object | None:
    index = start
    while index > 0:
        previous = index - 1
        char = text[previous]
        if char.isspace() or char in _BOUNDARY_WRAPPERS:
            index = previous
            continue
        if char not in _SENTENCE_TERMINATORS:
            return None
        ordinal = sum(1 for c in text[: previous + 1] if c in _SENTENCE_TERMINATORS)
        return ("after", ordinal)
    return "start"


def _restore_capitalization(text: str, targets: set[object]) -> str:
    if not targets or not text:
        return text

    sentence_targets = {ordinal for kind, ordinal in
                        (t for t in targets if isinstance(t, tuple))}
    result: list[str] = []
    terminator_ordinal = 0
    capitalize_next = "start" in targets

    for char in text:
        if capitalize_next:
            if char.islower():
                result.append(char.upper())
                capitalize_next = False
                continue
            if char.isalnum():
                capitalize_next = False

        result.append(char)

        if char in _SENTENCE_TERMINATORS:
            terminator_ordinal += 1
            if terminator_ordinal in sentence_targets:
                capitalize_next = True
        elif capitalize_next and not char.isspace() \
                and char not in _BOUNDARY_WRAPPERS \
                and char not in _ORPHAN_SEPARATORS:
            capitalize_next = False

    return "".join(result)


# -- 4. text style -------------------------------------------------------


def apply_text_style(text: str, style: TextStyle) -> str:
    """Trim the model's sentence punctuation to the chosen register.

    Only a trailing full stop goes: "?" and "!" carry meaning that the
    user dictated on purpose, and an ellipsis is not a full stop either.
    """
    if style is TextStyle.FORMAL or not text:
        return text

    stripped = text.rstrip()
    if stripped.endswith(".") and not stripped.endswith(".."):
        stripped = stripped[:-1].rstrip()
    if not stripped:
        return stripped

    if style is TextStyle.INFORMAL:
        first = stripped[0]
        # Only undo the model's own sentence capital. An all-caps word is
        # almost always an acronym the user actually said that way.
        if first.isupper() and not stripped[:2].isupper():
            stripped = first.lower() + stripped[1:]
    return stripped


# -- pipeline ------------------------------------------------------------


def process_transcript(
    raw: str,
    *,
    language: str = "auto",
    corrections: Sequence[Correction] = (),
    strip_fillers: bool = False,
    style: TextStyle = TextStyle.FORMAL,
) -> tuple[str, int, int]:
    """Returns (text, corrections applied, fillers removed)."""
    text = repair_model_text(raw.strip(), language=language)
    text, applied = apply_corrections(text, corrections)
    removed = 0
    if strip_fillers:
        text, removed = remove_filler_words(text)
    # Style last: it works on the finished sentence, so filler removal
    # cannot re-expose a full stop that this pass already took off.
    text = apply_text_style(text.strip(), style)
    return text.strip(), applied, removed
