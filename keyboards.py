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
from constants import DAY_SHORT_LABELS, TIME_OPTIONS

# Зависимость идёт в одну сторону: клавиатура может показать готовую подпись,
# но presenters ничего не знает про разметку.
from presenters import format_schedule_range
from services.access import is_stylist_subscription_active


def get_schedule_time_kb(day_of_week: int, action: str, start_time: str | None = None):
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
        buttons.append([InlineKeyboardButton(text="← Назад ко времени начала", callback_data=f"schedule_back_start_{day_of_week}")])
    buttons.append([InlineKeyboardButton(text="✖ Отмена", callback_data="cancel_fsm")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_special_schedule_time_kb(target_date: str, action: str, start_time: str | None = None):
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
        buttons.append([InlineKeyboardButton(text="← Назад ко времени начала", callback_data=f"special_back_start_{target_date}")])
    buttons.append([InlineKeyboardButton(text="✖ Отмена", callback_data="cancel_fsm")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_schedule_management_kb(schedule_map: dict[int, db.Schedule]):
    buttons = []
    for day in range(1, 8):
        schedule = schedule_map.get(day)
        buttons.append([
            InlineKeyboardButton(text=f"{DAY_SHORT_LABELS[day]} • {format_schedule_range(schedule)}", callback_data=f"set_day_{day}"),
            InlineKeyboardButton(text="Выходной", callback_data=f"set_day_off_{day}"),
        ])
    buttons.append([InlineKeyboardButton(text="📅 Особые даты", callback_data="schedule_special_dates")])
    buttons.append([InlineKeyboardButton(text="✖ Закрыть", callback_data="schedule_close")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_special_dates_calendar_kb(year: int, month: int, stylist_id: int):
    cal = calendar.Calendar()
    kb = []
    kb.append([InlineKeyboardButton(text=f"{calendar.month_name[month]} {year}", callback_data="ignore")])
    kb.append([InlineKeyboardButton(text=day, callback_data="ignore") for day in ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]])
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
    kb.append([InlineKeyboardButton(text="⬅️ К недельному графику", callback_data="schedule_weekly")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_special_date_actions_kb(target_date: str, stylist_id: int, has_override: bool):
    year_month = target_date[:7]
    buttons = [
        [InlineKeyboardButton(text="🕒 Задать часы", callback_data=f"special_set_hours_{target_date}_{stylist_id}")],
        [InlineKeyboardButton(text="🌴 Сделать выходным", callback_data=f"special_day_off_{target_date}_{stylist_id}")],
    ]
    if has_override:
        buttons.append([InlineKeyboardButton(text="♻️ Убрать исключение", callback_data=f"special_delete_{target_date}_{stylist_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ К календарю", callback_data=f"spec_cal_{year_month}_{stylist_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
        ]
    ])

def get_contact_request_keyboard(lang: str) -> ReplyKeyboardMarkup:
    share_text = {
        "ru": "📱 Поделиться контактом",
        "uz": "📱 Kontaktni ulashish",
    }[lang]
    manual_text = {
        "ru": "✍️ Ввести вручную",
        "uz": "✍️ Qo'lda kiritish",
    }[lang]
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
        if is_stylist_subscription_active(user):
            kb = [
                [KeyboardButton(text="📓 Мои записи"), KeyboardButton(text="📊 Моя статистика")],
                [KeyboardButton(text="🕒 Управление расписанием"), KeyboardButton(text="✂️ Мои услуги")],
                [KeyboardButton(text="🖼 Мое портфолио"), KeyboardButton(text="💳 Срок тарифа")],
            ]
            return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, row_width=2)

        limited_kb = [
            [KeyboardButton(text="💳 Срок тарифа")],
            [KeyboardButton(text=buttons["change_language"])],
        ]
        return ReplyKeyboardMarkup(keyboard=limited_kb, resize_keyboard=True)

    kb = [
        [KeyboardButton(text=buttons["search_menu"])],
        [KeyboardButton(text=buttons["my_masters"])],
        [KeyboardButton(text=buttons["my_profile"]), KeyboardButton(text=buttons["change_language"])]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
