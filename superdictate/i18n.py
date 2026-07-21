"""Russian / English interface strings.

macOS calls ``localizedText(russian, english, language:)`` at every use
site. The same idea, one table: ``tr("key")`` reads the currently selected
language, and the RU/EN toggle in settings takes effect immediately
because nothing caches the resolved string.
"""

from __future__ import annotations

_LANGUAGE = "ru"

_STRINGS: dict[str, tuple[str, str]] = {
    # -- status ------------------------------------------------------
    "app_name": ("D1CT", "D1CT"),
    "status_starting": ("Запуск…", "Starting…"),
    "status_downloading": ("Загрузка модели", "Downloading model"),
    "status_loading": ("Загрузка модели в память", "Loading model"),
    "status_ready": ("Работает", "Ready"),
    "status_recording": ("Запись", "Recording"),
    "status_transcribing": ("Расшифровка", "Transcribing"),
    "status_failed": ("Ошибка", "Failed"),
    "status_no_microphone": ("Нет доступа к микрофону", "No microphone access"),
    "status_hook_failed": ("Хоткеи не перехватываются", "Hotkeys not captured"),

    # -- tray --------------------------------------------------------
    "tray_open_panel": ("Панель управления", "Control panel"),
    "tray_settings": ("Настройки…", "Settings…"),
    "tray_history": ("История", "History"),
    "tray_start": ("Начать диктовку", "Start dictation"),
    "tray_stop": ("Остановить", "Stop"),
    "tray_quit": ("Выйти", "Quit"),

    # -- control panel ----------------------------------------------
    "panel_service": ("Служба", "Service"),
    "panel_model": ("Модель", "Model"),
    "panel_hotkey": ("Диктовка", "Dictation"),
    "panel_hotkey_history": ("История", "History"),
    "panel_restart": ("Перезапустить", "Restart"),
    "panel_check_updates": ("Проверить обновления", "Check for updates"),
    "panel_compute": ("Вычисления", "Compute"),
    "panel_today": ("Сегодня", "Today"),
    "panel_total": ("Всего", "Total"),
    "panel_dictations": ("диктовок", "dictations"),
    "panel_words": ("слов", "words"),
    "panel_microphone": ("Микрофон", "Microphone"),
    "panel_shortcuts": ("Сочетания клавиш", "Shortcuts"),
    "panel_statistics": ("Статистика", "Statistics"),

    # -- statistics --------------------------------------------------
    "stats_today_dictations": ("Сегодня", "Today"),
    "stats_today_words": ("Слова", "Words"),
    "stats_total_dictations": ("Всего", "All time"),
    "stats_total_time": ("Наговорено", "Dictated"),
    "stats_unit_today": ("диктовок", "dictations"),
    "stats_unit_words_today": ("слов", "words"),
    "stats_unit_hours": ("ч:мин аудио", "h:min of audio"),
    "stats_unit_minutes": ("мин:сек аудио", "min:sec of audio"),
    "stats_unit_seconds": ("секунд аудио", "seconds of audio"),
    "stats_last_14_days": ("Последние 14 дней", "Last 14 days"),
    "stats_activity": ("Активность", "Activity"),

    # -- settings ----------------------------------------------------
    "settings_title": ("Настройки D1CT", "D1CT Settings"),
    "settings_tab_hotkeys": ("Сочетания", "Shortcuts"),
    "settings_tab_dictation": ("Диктовка", "Dictation"),
    "settings_tab_appearance": ("Вид", "Appearance"),
    "settings_tab_corrections": ("Замены", "Replacements"),
    "settings_tab_advanced": ("Дополнительно", "Advanced"),
    "settings_section_behaviour": ("Поведение", "Behaviour"),
    "settings_section_recognition": ("Распознавание", "Recognition"),
    "settings_section_capture": ("Запись", "Capture"),
    "settings_primary_hotkey": ("Основное сочетание", "Primary shortcut"),
    "settings_history_hotkey": ("Быстрая история", "Quick history"),
    "settings_record": ("Записать…", "Record…"),
    "settings_trigger_mode": ("Режим", "Mode"),
    "settings_trigger_hold": ("Удерживать", "Press and hold"),
    "settings_trigger_toggle": ("Нажать и нажать снова", "Press to toggle"),
    "settings_completion": ("Повторное нажатие", "Second press"),
    "settings_completion_insert": ("Вставить текст", "Insert text"),
    "settings_completion_enter": ("Вставить текст и Enter", "Insert text and press Enter"),
    "settings_text_style": ("Стиль текста", "Text style"),
    "settings_text_style_formal": ("Формальный", "Formal"),
    "settings_text_style_standard": ("Стандартный", "Standard"),
    "settings_text_style_informal": ("Неформальный", "Informal"),
    "settings_text_style_hint": (
        "Формальный: как распознала модель. Стандартный: без точки в конце. "
        "Неформальный: без точки и с маленькой буквы.",
        "Formal: exactly as recognised. Standard: no full stop at the end. "
        "Informal: no full stop and no leading capital.",
    ),
    "settings_enter_delay": ("Задержка перед Enter, мс", "Delay before Enter, ms"),
    "settings_paste_suffix": ("После вставки", "After insertion"),
    "settings_suffix_space": ("Добавить пробел", "Append space"),
    "settings_suffix_none": ("Ничего", "No suffix"),
    "settings_suffix_newline": ("Перевод строки", "Append newline"),
    "settings_language": ("Язык диктовки", "Dictation language"),
    "settings_interface_language": ("Язык интерфейса", "Interface language"),
    "settings_input_device": ("Устройство ввода", "Input device"),
    "settings_device_default": ("Системное по умолчанию", "System default"),
    "settings_remove_fillers": ("Убирать слова-паразиты (um, uh, …)",
                                "Remove filler words (um, uh, …)"),
    "settings_mute": ("Отключать звук системы во время записи",
                      "Mute system output while recording"),
    "settings_stop_on_silence": (
        "Завершать запись автоматически после паузы",
        "Finish the recording automatically after a pause",
    ),
    "settings_silence_seconds": ("Длина паузы, с", "Pause length, s"),
    "settings_stop_on_silence_hint": (
        "Отсчёт начинается только после первых произнесённых слов.",
        "The countdown only starts once you have actually said something.",
    ),
    "settings_sounds": ("Звуковые сигналы", "Feedback sounds"),
    "settings_autostart": ("Запускать при входе в Windows", "Start at Windows login"),
    "settings_check_updates": ("Проверять обновления", "Check for updates"),
    "settings_waveform": ("Показывать капсулу с волной", "Show waveform capsule"),
    "settings_hud_size": ("Размер капсулы", "Capsule size"),
    "settings_hud_size_compact": ("Компактный", "Compact"),
    "settings_hud_size_standard": ("Стандартный", "Standard"),
    "settings_hud_size_large": ("Крупный", "Large"),
    "settings_hud_recording_color": ("Цвет записи", "Recording color"),
    "settings_hud_transcribing_color": ("Цвет расшифровки", "Transcribing color"),
    "settings_hud_background": ("Фон капсулы", "Capsule background"),
    "settings_hud_background_system": ("Системный", "System"),
    "settings_hud_background_dark": ("Тёмный", "Dark"),
    "settings_hud_background_light": ("Светлый", "Light"),
    "color_red": ("Красный", "Red"),
    "color_orange": ("Оранжевый", "Orange"),
    "color_pink": ("Розовый", "Pink"),
    "color_purple": ("Фиолетовый", "Purple"),
    "color_blue": ("Синий", "Blue"),
    "color_cyan": ("Голубой", "Cyan"),
    "color_green": ("Зелёный", "Green"),
    "color_white": ("Белый", "White"),
    "settings_history_limit": ("Быстрая история", "Quick history"),
    "settings_history_off": ("Выключена", "Off"),
    "settings_history_last": ("Последние {n}", "Last {n}"),
    "settings_model_quality": ("Веса модели", "Model weights"),
    "settings_model_int8": ("Сжатые int8 · 640 МБ", "Quantized int8 · 640 MB"),
    "settings_model_full": ("Полные fp32 · 2,4 ГБ", "Full fp32 · 2.4 GB"),
    "settings_compute": ("Устройство вычислений", "Compute device"),
    "settings_compute_auto": ("Авто", "Auto"),
    "settings_compute_cuda": ("GPU (CUDA)", "GPU (CUDA)"),
    "settings_compute_cpu": ("CPU", "CPU"),
    "settings_save_restart": ("Сохранить и перезапустить", "Save and restart"),
    "settings_cancel": ("Отмена", "Cancel"),
    "settings_draft_note": (
        "Изменения применятся после «Сохранить и перезапустить».",
        "Changes apply when you click Save and restart.",
    ),

    # -- shortcut recorder ------------------------------------------
    "recorder_title": ("Новое сочетание", "Record shortcut"),
    "recorder_instruction": (
        "Нажмите одну клавишу или сочетание. Escape закроет окно без изменений.",
        "Press one key or a shortcut. Escape closes without changes.",
    ),
    "recorder_nothing": ("Ничего не выбрано", "Nothing selected"),
    "recorder_save": ("Сохранить", "Save"),

    # -- corrections -------------------------------------------------
    "corrections_source": ("Слышится как", "Heard as"),
    "corrections_replacement": ("Заменить на", "Replace with"),
    "corrections_add": ("Добавить", "Add"),
    "corrections_remove": ("Удалить", "Remove"),
    "corrections_note": (
        "Замены применяются к тексту до вставки; регистр игнорируется, "
        "совпадение по целым словам.",
        "Replacements are applied before insertion; matching is "
        "case-insensitive and whole-word.",
    ),

    # -- history window ----------------------------------------------
    "history_title": ("История диктовок", "Dictation history"),
    "history_empty": ("Пока пусто", "Nothing yet"),
    "history_insert": ("Вставить", "Insert"),
    "history_copy": ("Копировать", "Copy"),
    "history_delete": ("Удалить", "Delete"),
    "history_clear": ("Очистить всё", "Clear all"),
    "history_hint": (
        "Enter, вставить в активное окно. Esc, закрыть.",
        "Enter inserts into the active window, Esc closes.",
    ),

    # -- updates -----------------------------------------------------
    "update_available": ("Доступна версия {version}", "Version {version} available"),
    "update_none": ("Установлена последняя версия", "You are up to date"),
    "update_checking": ("Проверка…", "Checking…"),
    "update_failed": ("Не удалось проверить обновления", "Update check failed"),
    "update_open": ("Открыть страницу релиза", "Open release page"),
    "update_no_windows_build": (
        "Для Windows сборка ещё не опубликована",
        "No Windows build published yet",
    ),

    # -- errors ------------------------------------------------------
    # Two separate causes: a real permission block, and everything else
    # (device busy, unplugged, driver refusing the format). Reporting the
    # second as the first sent users hunting through privacy settings for
    # a problem that was not there.
    "error_microphone_denied": (
        "Windows не дал доступ к микрофону. Откройте Параметры → "
        "Конфиденциальность → Микрофон и разрешите доступ приложениям.",
        "Windows denied microphone access. Open Settings → Privacy → "
        "Microphone and allow desktop apps.",
    ),
    "error_microphone": (
        "Не удалось открыть микрофон: {reason}",
        "Could not open the microphone: {reason}",
    ),
    "error_microphone_busy": (
        "Микрофон занят другим приложением",
        "The microphone is in use by another application",
    ),
    "error_hook": (
        "Не удалось установить перехват клавиатуры. Запустите приложение "
        "от того же уровня прав, что и целевое окно.",
        "Could not install the keyboard hook. Run the app at the same "
        "privilege level as the window you type into.",
    ),
    "error_too_short": ("Слишком короткая запись", "Recording too short"),
    "error_no_speech": ("Речь не распознана", "No speech recognized"),
}


def set_language(language: str) -> None:
    global _LANGUAGE
    _LANGUAGE = "en" if language == "en" else "ru"


def language() -> str:
    return _LANGUAGE


_MONTHS: tuple[tuple[str, str], ...] = (
    ("янв", "Jan"), ("фев", "Feb"), ("мар", "Mar"), ("апр", "Apr"),
    ("май", "May"), ("июн", "Jun"), ("июл", "Jul"), ("авг", "Aug"),
    ("сен", "Sep"), ("окт", "Oct"), ("ноя", "Nov"), ("дек", "Dec"),
)


def month_abbr(month: int) -> str:
    """Abbreviated month name. ``strftime('%b')`` follows the C locale,
    which is English no matter what the interface language is."""
    return _MONTHS[month - 1][0 if _LANGUAGE == "ru" else 1]


def tr(key: str, **kwargs) -> str:
    pair = _STRINGS.get(key)
    if pair is None:
        return key
    text = pair[0] if _LANGUAGE == "ru" else pair[1]
    return text.format(**kwargs) if kwargs else text
