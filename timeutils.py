"""
Единая точка работы со временем.

РЕШЕНИЕ: в базе хранится **наивное локальное время Asia/Tashkent**, не UTC.

Почему не UTC, хотя это «правильный» ответ по умолчанию:

- бизнес целиком в одном городе, Узбекистан — одна зона UTC+5 без перехода
  на летнее время, то есть выгода UTC равна нулю до выхода в другую страну;
- запросы в коде почти все вида «записи на дату X», где X — локальная дата.
  При хранении в UTC каждая из ~20 таких выборок обязана конвертировать границы
  суток, и пропуск одной даёт тихий сдвиг на 5 часов;
- то же самое на выводе: пропущенная конвертация покажет клиенту 09:00 вместо
  14:00. Это худший вид бага — он не падает, а врёт.

Переход на UTC становится оправдан при выходе за пределы одной зоны. Точка
конвертации тогда ровно одна — этот модуль.

Все datetime в проекте — наивные. Не смешивайте их с aware-объектами:
`datetime.now(timezone.utc)` в сравнении с полем из базы даст TypeError.
Вместо `datetime.now()` используйте `timeutils.now()`.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")

# Формат хранения и обмена со слотами календаря.
SLOT_FORMAT = "%Y-%m-%d %H:%M"
DATE_FORMAT = "%Y-%m-%d"

MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
MONTHS_UZ = (
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
)


def now() -> datetime:
    """Текущее локальное время как наивный datetime."""
    return datetime.now(TZ).replace(tzinfo=None)


def today() -> date:
    return now().date()


def parse_slot(value: str) -> datetime:
    """Строка "YYYY-MM-DD HH:MM" -> datetime. Бросает ValueError на мусоре."""
    return datetime.strptime(value, SLOT_FORMAT)


def combine(day: date, time_value: str) -> datetime:
    """Дата плюс время вида "14:30"."""
    hour, minute = (int(part) for part in time_value.split(":"))
    return datetime.combine(day, time(hour, minute))


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Полуинтервал [начало суток, начало следующих) — для выборок за день."""
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


def range_bounds(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    """Полуинтервал от начала start_day до начала дня после end_day."""
    return datetime.combine(start_day, time.min), datetime.combine(end_day, time.min) + timedelta(days=1)


def format_slot(value: datetime | None) -> str:
    """Машинный формат — для логов и мест, где важна однозначность."""
    return value.strftime(SLOT_FORMAT) if value else "-"


def format_human(value: datetime | None, lang: str = "ru") -> str:
    """
    Человеческий формат для сообщений: «23 сентября, 15:00».
    Сегодня и завтра называются словом — так клиенту не надо сверяться с календарём.
    """
    if not value:
        return "-"

    current = today()
    delta_days = (value.date() - current).days
    time_part = value.strftime("%H:%M")

    if delta_days == 0:
        prefix = {"ru": "сегодня", "uz": "bugun"}.get(lang, "сегодня")
        return f"{prefix}, {time_part}"
    if delta_days == 1:
        prefix = {"ru": "завтра", "uz": "ertaga"}.get(lang, "завтра")
        return f"{prefix}, {time_part}"

    months = MONTHS_UZ if lang == "uz" else MONTHS_RU
    return f"{value.day} {months[value.month - 1]}, {time_part}"
