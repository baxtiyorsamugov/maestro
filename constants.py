"""
Словарь расписания.

Общий для клавиатур и построителей текста. Держать его в одном из этих модулей
значило бы получить зависимость в обе стороны, поэтому он вынесен отдельно.

Дни недели нумеруются как в ISO: 1 — понедельник, 7 — воскресенье.
Это тот же порядок, что возвращает date.isoweekday(), и совпадает с тем,
как дни хранятся в таблице schedules.
"""

DAY_NAMES = {
    1: {"ru": "Понедельник", "uz": "Dushanba"},
    2: {"ru": "Вторник", "uz": "Seshanba"},
    3: {"ru": "Среда", "uz": "Chorshanba"},
    4: {"ru": "Четверг", "uz": "Payshanba"},
    5: {"ru": "Пятница", "uz": "Juma"},
    6: {"ru": "Суббота", "uz": "Shanba"},
    7: {"ru": "Воскресенье", "uz": "Yakshanba"},
}

DAY_SHORT_NAMES = {
    1: {"ru": "Пн", "uz": "Du"},
    2: {"ru": "Вт", "uz": "Se"},
    3: {"ru": "Ср", "uz": "Ch"},
    4: {"ru": "Чт", "uz": "Pa"},
    5: {"ru": "Пт", "uz": "Ju"},
    6: {"ru": "Сб", "uz": "Sh"},
    7: {"ru": "Вс", "uz": "Ya"},
}

DEFAULT_LANGUAGE = "ru"


def day_name(day_of_week: int, lang: str = DEFAULT_LANGUAGE) -> str:
    """Полное название дня недели."""
    names = DAY_NAMES.get(day_of_week, {})
    return names.get(lang) or names.get(DEFAULT_LANGUAGE, str(day_of_week))


def day_short(day_of_week: int, lang: str = DEFAULT_LANGUAGE) -> str:
    """Сокращённое название дня недели — для сетки календаря и кнопок."""
    names = DAY_SHORT_NAMES.get(day_of_week, {})
    return names.get(lang) or names.get(DEFAULT_LANGUAGE, str(day_of_week))


def week_header(lang: str = DEFAULT_LANGUAGE) -> list[str]:
    """Шапка календаря: семь сокращений начиная с понедельника."""
    return [day_short(day, lang) for day in range(1, 8)]


TIME_OPTIONS = [f"{hour:02d}:{minute:02d}" for hour in range(7, 24) for minute in (0, 30)]
