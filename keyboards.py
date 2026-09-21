"""
Клавиатуры бота.

Здесь всё, что возвращает разметку. Тексты сообщений — в presenters.py:
разделение по тому, что функция отдаёт, а не по экрану, к которому относится.
"""
import calendar
from datetime import date

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from sqlalchemy import select

import database as db
import texts
import timeutils
from constants import DEFAULT_LANGUAGE, TIME_OPTIONS, day_short, week_header

# Зависимость идёт в одну сторону: клавиатура может показать готовую подпись,
# но presenters ничего не знает про разметку.
from presenters import format_buffer, format_schedule_range
from services.access import is_stylist_subscription_active
from services.booking import BUFFER_CHOICES


def get_schedule_time_kb(
    day_of_week: int, action: str, start_time: str | None = None, lang: str = DEFAULT_LANGUAGE
):
    buttons = []
    row = []
    for time_value in TIME_OPTIONS:
        if action == "end" and start_time and time_value <= start_time:
            continue
        row.append(InlineKeyboardButton(text=time_value, callback_data=f"schedule_{action}_{day_of_week}_{time_value}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if action == "end":
        buttons.append([InlineKeyboardButton(
            text=texts.get_text("kb_back_to_start_time", lang),
            callback_data=f"schedule_back_start_{day_of_week}",
        )])
    buttons.append([InlineKeyboardButton(
        text=texts.get_text("kb_cancel", lang), callback_data="cancel_fsm"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_special_schedule_time_kb(
    target_date: str, action: str, start_time: str | None = None, lang: str = DEFAULT_LANGUAGE
):
    buttons = []
    row = []
    for time_value in TIME_OPTIONS:
        if action == "end" and start_time and time_value <= start_time:
            continue
        row.append(InlineKeyboardButton(text=time_value, callback_data=f"special_{action}_{target_date}_{time_value}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if action == "end":
        buttons.append([InlineKeyboardButton(
            text=texts.get_text("kb_back_to_start_time", lang),
            callback_data=f"special_back_start_{target_date}",
        )])
    buttons.append([InlineKeyboardButton(
        text=texts.get_text("kb_cancel", lang), callback_data="cancel_fsm"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_schedule_management_kb(
    schedule_map: dict[int, db.Schedule], lang: str = DEFAULT_LANGUAGE, buffer_min: int = 0
):
    buttons = []
    for day in range(1, 8):
        schedule = schedule_map.get(day)
        buttons.append([
            InlineKeyboardButton(
                text=f"{day_short(day, lang)} • {format_schedule_range(schedule, lang)}",
                callback_data=f"set_day_{day}",
            ),
            InlineKeyboardButton(
                text=texts.get_text("schedule_day_off_short", lang),
                callback_data=f"set_day_off_{day}",
            ),
        ])
    buttons.append([InlineKeyboardButton(
        text=texts.get_text("kb_breaks", lang), callback_data="brk_menu"
    )])
    buttons.append([InlineKeyboardButton(
        text=texts.get_text("kb_buffer", lang).format(value=format_buffer(buffer_min, lang)),
        callback_data="buffer_menu",
    )])
    buttons.append([InlineKeyboardButton(
        text=texts.get_text("kb_special_dates", lang), callback_data="schedule_special_dates"
    )])
    buttons.append([InlineKeyboardButton(
        text=texts.get_text("kb_close", lang), callback_data="schedule_close"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_buffer_kb(current: int, lang: str = DEFAULT_LANGUAGE):
    """Выбор буфера. Текущее значение помечено — иначе непонятно, что стоит сейчас."""
    row = []
    buttons = []
    for minutes in BUFFER_CHOICES:
        label = format_buffer(minutes, lang)
        if minutes == current:
            label = f"✅ {label}"
        row.append(InlineKeyboardButton(text=label, callback_data=f"buffer_set_{minutes}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(
        text=texts.get_text("kb_back_to_weekly", lang), callback_data="schedule_weekly"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_break_days_kb(schedule_map: dict[int, db.Schedule], lang: str = DEFAULT_LANGUAGE):
    """
    День недели для настройки перерыва.

    Выходные дни тоже показываются, но помечены: мастер не должен гадать,
    почему в списке шесть дней вместо семи.
    """
    buttons = []
    for day in range(1, 8):
        schedule = schedule_map.get(day)
        if not schedule:
            state = texts.get_text("schedule_day_off_short", lang)
        elif schedule.break_start and schedule.break_end:
            state = f"{schedule.break_start}-{schedule.break_end}"
        else:
            state = texts.get_text("break_none", lang)
        buttons.append([InlineKeyboardButton(
            text=f"{day_short(day, lang)} • {state}", callback_data=f"brk_day_{day}"
        )])
    buttons.append([InlineKeyboardButton(
        text=texts.get_text("kb_back_to_weekly", lang), callback_data="schedule_weekly"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_break_time_kb(
    day_of_week: int,
    action: str,
    lower_bound: str,
    upper_bound: str,
    lang: str = DEFAULT_LANGUAGE,
):
    """
    Часы для границы перерыва внутри рабочего дня.

    Показывать время за пределами смены незачем: перерыв в 22:00 у мастера,
    который работает до 18:00, не значит ничего, а выбрать его можно.
    """
    buttons = []
    row = []
    for time_value in TIME_OPTIONS:
        if time_value < lower_bound or time_value > upper_bound:
            continue
        row.append(InlineKeyboardButton(
            text=time_value, callback_data=f"brk_{action}_{day_of_week}_{time_value}"
        ))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if action == "start":
        buttons.append([InlineKeyboardButton(
            text=texts.get_text("kb_break_clear", lang), callback_data=f"brk_clear_{day_of_week}"
        )])
    buttons.append([InlineKeyboardButton(
        text=texts.get_text("kb_breaks", lang), callback_data="brk_menu"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_special_dates_calendar_kb(
    year: int, month: int, stylist_id: int, lang: str = DEFAULT_LANGUAGE
):
    cal = calendar.Calendar()
    kb = []
    kb.append([InlineKeyboardButton(text=f"{calendar.month_name[month]} {year}", callback_data="ignore")])
    kb.append([
        InlineKeyboardButton(text=day, callback_data="ignore") for day in week_header(lang)
    ])
    today = timeutils.today()
    for week in cal.monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
                continue
            current_date = date(year, month, day)
            if current_date < today:
                row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
                continue
            row.append(InlineKeyboardButton(text=str(day), callback_data=f"specdate_{current_date.strftime('%Y-%m-%d')}_{stylist_id}"))
        kb.append(row)
    prev_month, prev_year = (month - 1, year) if month > 1 else (12, year - 1)
    next_month, next_year = (month + 1, year) if month < 12 else (1, year + 1)
    kb.append([
        InlineKeyboardButton(text="⬅️", callback_data=f"spec_cal_{prev_year}-{prev_month}_{stylist_id}"),
        InlineKeyboardButton(text=" ", callback_data="ignore"),
        InlineKeyboardButton(text="➡️", callback_data=f"spec_cal_{next_year}-{next_month}_{stylist_id}"),
    ])
    kb.append([InlineKeyboardButton(
        text=texts.get_text("kb_back_to_weekly", lang), callback_data="schedule_weekly"
    )])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_special_date_actions_kb(
    target_date: str, stylist_id: int, has_override: bool, lang: str = DEFAULT_LANGUAGE
):
    year_month = target_date[:7]
    buttons = [
        [InlineKeyboardButton(
            text=texts.get_text("kb_set_hours", lang),
            callback_data=f"special_set_hours_{target_date}_{stylist_id}",
        )],
        [InlineKeyboardButton(
            text=texts.get_text("kb_make_day_off", lang),
            callback_data=f"special_day_off_{target_date}_{stylist_id}",
        )],
    ]
    if has_override:
        buttons.append([InlineKeyboardButton(
            text=texts.get_text("kb_remove_exception", lang),
            callback_data=f"special_delete_{target_date}_{stylist_id}",
        )])
    buttons.append([InlineKeyboardButton(
        text=texts.get_text("back_to_calendar", lang),
        callback_data=f"spec_cal_{year_month}_{stylist_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
        ]
    ])

def get_contact_request_keyboard(lang: str) -> ReplyKeyboardMarkup:
    share_text = texts.get_text("kb_share_contact", lang)
    manual_text = texts.get_text("kb_enter_phone_manually", lang)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=share_text, request_contact=True)],
            [KeyboardButton(text=manual_text)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

def get_language_switch_kb(current_lang: str, prefix: str = "change_lang") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=(" " if current_lang == "uz" else "") + texts.get_text("language_name_uz", current_lang),
                callback_data=f"{prefix}_uz",
            ),
            InlineKeyboardButton(
                text=(" " if current_lang == "ru" else "") + texts.get_text("language_name_ru", current_lang),
                callback_data=f"{prefix}_ru",
            ),
        ]
    ])

# --- Клавиатуры ---
async def get_main_keyboard(user_id: int):
    """
    Возвращает главное меню в зависимости от роли пользователя:
    - клиенту -> меню поиска и записи
    - мастеру -> панель управления
    """
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == user_id))

    lang = user.language_code if user and user.language_code else "ru"
    buttons = texts.get_buttons(lang)

    if user and user.role == "stylist":
        panel = texts.get_stylist_buttons(lang)
        if is_stylist_subscription_active(user):
            kb = [
                [KeyboardButton(text=panel["my_bookings"]), KeyboardButton(text=panel["my_stats"])],
                [KeyboardButton(text=panel["manage_schedule"]), KeyboardButton(text=panel["my_services"])],
                [KeyboardButton(text=panel["my_profile_card"]), KeyboardButton(text=panel["my_portfolio"])],
                [KeyboardButton(text=panel["subscription"])],
            ]
            return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, row_width=2)

        # Тариф истёк: оставляем только продление и переключение языка.
        limited_kb = [
            [KeyboardButton(text=panel["subscription"])],
            [KeyboardButton(text=buttons["change_language"])],
        ]
        return ReplyKeyboardMarkup(keyboard=limited_kb, resize_keyboard=True)

    kb = [
        [KeyboardButton(text=buttons["search_menu"])],
        [KeyboardButton(text=buttons["my_masters"]), KeyboardButton(text=buttons["my_data"])],
        [KeyboardButton(text=buttons["my_profile"]), KeyboardButton(text=buttons["change_language"])]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
