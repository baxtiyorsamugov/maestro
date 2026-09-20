"""
Инлайн-календарь.

Одна и та же сетка нужна и клиенту (выбор даты записи), и мастеру (запись
офлайн-клиента). Отличаются они только префиксом callback_data и кнопкой
возврата, поэтому функция одна, а не две почти одинаковых.
"""
import calendar
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import texts
import timeutils
from constants import DEFAULT_LANGUAGE, week_header


def _month_title(year: int, month: int, lang: str) -> str:
    months = timeutils.MONTHS_UZ if lang == "uz" else timeutils.MONTHS_RU
    return f"{months[month - 1]} {year}"


def generate_calendar(
    year: int,
    month: int,
    maestro_id: int,
    available_dates=None,
    prefix: str = "",
    back_callback: str | None = None,
    lang: str = DEFAULT_LANGUAGE,
):
    """
    Сетка месяца: активны только даты из available_dates.

    prefix уводит нажатия в другой набор хендлеров, не задевая клиентские:
    «offbk_date_2026-09-20» не подходит под фильтр startswith("date_").
    """
    cal = calendar.Calendar()
    kb = []
    available_dates = set(available_dates or [])

    kb.append([InlineKeyboardButton(
        text=_month_title(year, month, lang), callback_data="ignore"
    )])
    kb.append([
        InlineKeyboardButton(text=day, callback_data="ignore") for day in week_header(lang)
    ])

    today = timeutils.today()

    for week in cal.monthdayscalendar(year, month):
        row = []
        for day in week:
            is_past_day = (
                day == 0
                or (year == today.year and month == today.month and day < today.day)
                or (year == today.year and month < today.month)
                or (year < today.year)
            )

            if is_past_day:
                row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
                continue

            current_date = date(year, month, day)
            date_str = current_date.strftime("%Y-%m-%d")

            if available_dates and current_date not in available_dates:
                row.append(InlineKeyboardButton(
                    text=f"·{day}", callback_data=f"{prefix}dayoff_{date_str}"
                ))
            else:
                row.append(InlineKeyboardButton(
                    text=str(day), callback_data=f"{prefix}date_{date_str}"
                ))
        kb.append(row)

    prev_month, prev_year = (month - 1, year) if month > 1 else (12, year - 1)
    next_month, next_year = (month + 1, year) if month < 12 else (1, year + 1)

    kb.append([
        InlineKeyboardButton(
            text="⬅️", callback_data=f"{prefix}cal_{prev_year}-{prev_month}_{maestro_id}"
        ),
        InlineKeyboardButton(text=" ", callback_data="ignore"),
        InlineKeyboardButton(
            text="➡️", callback_data=f"{prefix}cal_{next_year}-{next_month}_{maestro_id}"
        ),
    ])

    if back_callback:
        kb.append([InlineKeyboardButton(
            text=texts.get_text("kb_back", lang), callback_data=back_callback
        )])
    elif maestro_id:
        kb.append([InlineKeyboardButton(
            text="⬅️ Ortga / Назад", callback_data=f"maestro_{maestro_id}"
        )])

    return InlineKeyboardMarkup(inline_keyboard=kb)
