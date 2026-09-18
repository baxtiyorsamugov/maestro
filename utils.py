import calendar
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import timeutils


def generate_calendar(year: int, month: int, maestro_id: int, available_dates=None):
    cal = calendar.Calendar()
    days = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
    month_name = calendar.month_name[month]
    kb = []
    available_dates = set(available_dates or [])

    kb.append([InlineKeyboardButton(text=f"{month_name} {year}", callback_data="ignore")])
    kb.append([InlineKeyboardButton(text=day, callback_data="ignore") for day in days])

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
                row.append(InlineKeyboardButton(text=f"·{day}", callback_data=f"dayoff_{date_str}"))
            else:
                row.append(InlineKeyboardButton(text=str(day), callback_data=f"date_{date_str}"))
        kb.append(row)

    prev_month, prev_year = (month - 1, year) if month > 1 else (12, year - 1)
    next_month, next_year = (month + 1, year) if month < 12 else (1, year + 1)

    kb.append([
        InlineKeyboardButton(text="⬅️", callback_data=f"cal_{prev_year}-{prev_month}_{maestro_id}"),
        InlineKeyboardButton(text=" ", callback_data="ignore"),
        InlineKeyboardButton(text="➡️", callback_data=f"cal_{next_year}-{next_month}_{maestro_id}"),
    ])

    if maestro_id:
        kb.append([InlineKeyboardButton(text="⬅️ Ortga / Назад", callback_data=f"maestro_{maestro_id}")])

    return InlineKeyboardMarkup(inline_keyboard=kb)
