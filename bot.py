# Файл: bot.py
import asyncio
import calendar
import logging
import re
import sys
from datetime import date, datetime, timedelta
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage  # Хранилище состояний в памяти
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload  # Важный импорт

import database as db
import middlewares
import scheduler
import texts
import timeutils
import utils  # Наш файл календаря
from config import get_optional_env, get_required_env
from services.access import (
    get_stylist_profile_by_telegram,
    get_subscription_days_left,
    is_registration_complete,
    is_stylist_subscription_active,
    load_booking_for_client,
    load_booking_for_stylist,
)
from services.booking import (
    get_available_dates_for_month,
    get_available_slots_for_date,
    load_special_dates,
)
from services.rating import recalculate_stylist_rating
from states import (
    PortfolioForm,
    RegistrationForm,
    ScheduleForm,
    SearchForm,
    ServiceForm,
    SpecialDateForm,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)


def build_storage():
    """
    RedisStorage, если задан REDIS_URL, иначе MemoryStorage.

    С MemoryStorage незавершённый сценарий записи теряется при каждом рестарте
    бота — для прода нужен Redis (docs/AUDIT.md, A-6).
    """
    redis_url = get_optional_env("REDIS_URL")
    if not redis_url:
        logging.warning(
            "storage.memory_fallback REDIS_URL не задан: состояние сценариев "
            "будет теряться при рестарте бота"
        )
        return MemoryStorage()

    from aiogram.fsm.storage.redis import RedisStorage

    logging.info("storage.redis url=%s", redis_url.split("@")[-1])
    return RedisStorage.from_url(redis_url)


storage = build_storage()
bot = Bot(token=get_required_env("BOT_TOKEN"))
dp = Dispatcher(storage=storage)

# Антифлуд. Регистрируется на оба типа апдейтов: быстрые повторные нажатия
# порождают параллельные запросы к базе и дублирующие уведомления.
throttling = middlewares.ThrottlingMiddleware()
dp.message.middleware(throttling)
dp.callback_query.middleware(throttling)

# --- Состояние сценария записи ---
# Раньше здесь были глобальные словари booking_cache/search_cache. Они терялись
# при каждом рестарте и не работали бы в нескольких процессах. Теперь данные
# шага записи живут в FSM (docs/AUDIT.md, A-6).

BOOKING_KEYS = ("stylist_id", "service_id", "date")


async def get_booking_draft(state: FSMContext) -> dict:
    """Черновик записи из FSM: stylist_id, service_id, date."""
    data = await state.get_data()
    return {key: data[key] for key in BOOKING_KEYS if data.get(key) is not None}


async def update_booking_draft(state: FSMContext, **values) -> dict:
    await state.update_data(**values)
    return await get_booking_draft(state)


async def clear_booking_draft(state: FSMContext) -> None:
    data = await state.get_data()
    for key in BOOKING_KEYS:
        data.pop(key, None)
    await state.set_data(data)


async def clear_search_context(state: FSMContext, user_id: int):
    current_state = await state.get_state()
    if current_state == SearchForm.waiting_for_name.state:
        await state.clear()
    await state.update_data(search_type=None)


def is_client_main_menu_button(text_value: str | None) -> bool:
    if not text_value:
        return False
    buttons_ru = texts.get_buttons("ru")
    buttons_uz = texts.get_buttons("uz")
    return text_value in {
        buttons_ru["search_menu"], buttons_uz["search_menu"],
        buttons_ru["my_masters"], buttons_uz["my_masters"],
        buttons_ru["my_profile"], buttons_uz["my_profile"],
        buttons_ru["change_language"], buttons_uz["change_language"],
    }












DAY_LABELS = {
    1: "Понедельник",
    2: "Вторник",
    3: "Среда",
    4: "Четверг",
    5: "Пятница",
    6: "Суббота",
    7: "Воскресенье",
}

DAY_SHORT_LABELS = {
    1: "\u041f\u043d",
    2: "\u0412\u0442",
    3: "\u0421\u0440",
    4: "\u0427\u0442",
    5: "\u041f\u0442",
    6: "\u0421\u0431",
    7: "\u0412\u0441",
}

TIME_OPTIONS = [f"{hour:02d}:{minute:02d}" for hour in range(7, 24) for minute in (0, 30)]


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


def format_schedule_range(schedule):
    return f"{schedule.start_time}-{schedule.end_time}" if schedule else "выходной"


def format_special_schedule_range(schedule: db.SpecialSchedule | None) -> str:
    if not schedule:
        return "без изменений"
    if schedule.is_day_off:
        return "выходной"
    if schedule.start_time and schedule.end_time:
        return f"{schedule.start_time}-{schedule.end_time}"
    return "без изменений"


def build_schedule_overview_text(stylist_name: str, schedule_map: dict[int, db.Schedule], special_dates: list[db.SpecialSchedule] | None = None) -> str:
    lines = [
        f"<b>График мастера {stylist_name}</b>",
        "Базовый шаблон по дням недели. Ниже можно изменить часы или отметить выходной.",
        "",
    ]
    for day in range(1, 8):
        schedule = schedule_map.get(day)
        lines.append(f"• {DAY_LABELS[day]}: <b>{format_schedule_range(schedule)}</b>")
    lines.append("")
    if special_dates:
        lines.append("<b>Ближайшие особые даты:</b>")
        for item in special_dates[:5]:
            lines.append(f"• {item.work_date.strftime('%Y-%m-%d')}: <b>{format_special_schedule_range(item)}</b>")
        lines.append("")
    lines.append("Клиент увидит в календаре только реально доступные слоты. Для разовых изменений используйте кнопку «Особые даты».")
    return "\n".join(lines)


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


def build_special_dates_text(stylist_name: str, year: int, month: int, special_dates: list[db.SpecialSchedule]) -> str:
    lines = [
        f"<b>Особые даты {stylist_name}</b>",
        f"Месяц: <b>{year}-{month:02d}</b>",
        "Выберите конкретную дату, чтобы сделать её выходным или задать отдельные часы.",
        "Если для даты нет исключения, будет работать обычный недельный график.",
        "",
    ]
    upcoming = [item for item in special_dates if item.work_date >= date.today()]
    if upcoming:
        lines.append("<b>Ближайшие исключения:</b>")
        for item in upcoming[:6]:
            lines.append(f"• {item.work_date.strftime('%Y-%m-%d')}: <b>{format_special_schedule_range(item)}</b>")
    else:
        lines.append("Пока нет особых дат. Ниже можно добавить первое исключение.")
    return "\n".join(lines)


def get_special_dates_calendar_kb(year: int, month: int, stylist_id: int):
    cal = calendar.Calendar()
    kb = []
    kb.append([InlineKeyboardButton(text=f"{calendar.month_name[month]} {year}", callback_data="ignore")])
    kb.append([InlineKeyboardButton(text=day, callback_data="ignore") for day in ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]])
    today = date.today()
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


def build_special_date_detail_text(target_date: str, weekly_schedule: db.Schedule | None, special_schedule: db.SpecialSchedule | None) -> str:
    weekly_text = format_schedule_range(weekly_schedule)
    special_text = format_special_schedule_range(special_schedule)
    return (
        f"<b>{target_date}</b>\n"
        f"\u041f\u043e \u0448\u0430\u0431\u043b\u043e\u043d\u0443 \u043d\u0435\u0434\u0435\u043b\u0438: <b>{weekly_text}</b>\n"
        f"\u0418\u0441\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435 \u043d\u0430 \u044d\u0442\u0443 \u0434\u0430\u0442\u0443: <b>{special_text}</b>\n\n"
        "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435, \u0447\u0442\u043e \u0441\u0434\u0435\u043b\u0430\u0442\u044c \u0441 \u044d\u0442\u043e\u0439 \u0434\u0430\u0442\u043e\u0439."
    )


def parse_special_callback_parts(data: str, prefix: str):
    payload = data[len(prefix):]
    target_date, remainder = payload.split("_", 1)
    return target_date, remainder












def get_subscription_menu_text(user: db.User | None) -> str:
    if not user or user.role != "stylist":
        return (
            "<b>\u0422\u0430\u0440\u0438\u0444 \u043c\u0430\u0441\u0442\u0435\u0440\u0430</b>\n"
            "\u042d\u0442\u043e\u0442 \u0440\u0430\u0437\u0434\u0435\u043b \u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d \u0442\u043e\u043b\u044c\u043a\u043e \u043c\u0430\u0441\u0442\u0435\u0440\u0430\u043c."
        )

    expiry_text = user.subscription_until.strftime("%Y-%m-%d") if user.subscription_until else "\u0411\u0435\u0437 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f"
    days_left = get_subscription_days_left(user)

    if user.subscription_until is None:
        status_line = "\u0421\u0442\u0430\u0442\u0443\u0441: \u2705 \u0410\u043a\u0442\u0438\u0432\u0435\u043d"
        detail_line = "\u0421\u0440\u043e\u043a \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f \u043d\u0435 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d."
    elif days_left is not None and days_left < 0:
        status_line = "\u0421\u0442\u0430\u0442\u0443\u0441: \u26d4 \u0422\u0430\u0440\u0438\u0444 \u0438\u0441\u0442\u0451\u043a"
        detail_line = "\u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u043f\u0430\u043d\u0435\u043b\u044c\u044e \u0438 \u043d\u043e\u0432\u044b\u0435 \u0437\u0430\u043f\u0438\u0441\u0438 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b."
    elif days_left == 0:
        status_line = "\u0421\u0442\u0430\u0442\u0443\u0441: \u26a0\ufe0f \u0418\u0441\u0442\u0435\u043a\u0430\u0435\u0442 \u0441\u0435\u0433\u043e\u0434\u043d\u044f"
        detail_line = "\u041f\u0440\u043e\u0434\u043b\u0438\u0442\u0435 \u0442\u0430\u0440\u0438\u0444 \u0441\u0435\u0433\u043e\u0434\u043d\u044f, \u0447\u0442\u043e\u0431\u044b \u043d\u0435 \u043f\u043e\u0442\u0435\u0440\u044f\u0442\u044c \u0434\u043e\u0441\u0442\u0443\u043f \u043a \u043f\u0430\u043d\u0435\u043b\u0438 \u0438 \u043d\u043e\u0432\u044b\u043c \u0437\u0430\u043f\u0438\u0441\u044f\u043c."
    else:
        day_word = "\u0434\u043d\u0435\u0439"
        if days_left == 1:
            day_word = "\u0434\u0435\u043d\u044c"
        elif 2 <= days_left <= 4:
            day_word = "\u0434\u043d\u044f"
        status_line = "\u0421\u0442\u0430\u0442\u0443\u0441: \u2705 \u0410\u043a\u0442\u0438\u0432\u0435\u043d"
        detail_line = f"\u0414\u043e \u043e\u043a\u043e\u043d\u0447\u0430\u043d\u0438\u044f \u043e\u0441\u0442\u0430\u043b\u043e\u0441\u044c: <b>{days_left} {day_word}</b>."

    return (
        "<b>\u0421\u0440\u043e\u043a \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f \u0442\u0430\u0440\u0438\u0444\u0430</b>\n"
        f"\u0414\u0430\u0442\u0430 \u043e\u043a\u043e\u043d\u0447\u0430\u043d\u0438\u044f: <b>{expiry_text}</b>\n"
        f"{status_line}\n"
        f"{detail_line}\n\n"
        "\u0415\u0441\u043b\u0438 \u043d\u0443\u0436\u043d\u043e \u043f\u0440\u043e\u0434\u043b\u0435\u043d\u0438\u0435, \u0441\u0432\u044f\u0436\u0438\u0442\u0435\u0441\u044c \u0441 \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430\u043c\u0438 \u0441\u0435\u0440\u0432\u0438\u0441\u0430."
    )

async def ensure_active_stylist_message(message: Message):
    async with db.async_session() as session:
        user, stylist = await get_stylist_profile_by_telegram(session, message.from_user.id)
    if not (user and stylist):
        await message.answer("\u041f\u0440\u043e\u0444\u0438\u043b\u044c \u043c\u0430\u0441\u0442\u0435\u0440\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.")
        return None, None
    if not is_stylist_subscription_active(user):
        await message.answer(get_subscription_menu_text(user), parse_mode="HTML", reply_markup=await get_main_keyboard(message.from_user.id))
        return None, None
    return user, stylist

async def ensure_active_stylist_callback(cb: CallbackQuery):
    async with db.async_session() as session:
        user, stylist = await get_stylist_profile_by_telegram(session, cb.from_user.id)
    if not (user and stylist):
        await cb.answer("\u041f\u0440\u043e\u0444\u0438\u043b\u044c \u043c\u0430\u0441\u0442\u0435\u0440\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.", show_alert=True)
        return None, None
    if not is_stylist_subscription_active(user):
        await cb.answer("\u0421\u0440\u043e\u043a \u0442\u0430\u0440\u0438\u0444\u0430 \u0438\u0441\u0442\u0451\u043a. \u041f\u0440\u043e\u0434\u043b\u0438\u0442\u0435 \u0442\u0430\u0440\u0438\u0444 \u0443 \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u043e\u0432 \u0441\u0435\u0440\u0432\u0438\u0441\u0430.", show_alert=True)
        return None, None
    return user, stylist

# Статусы записи определены в database.py — оттуда их берёт и scheduler.
from database import (  # noqa: E402
    ACTIVE_BOOKING_STATUSES,
    BOOKING_APPROVED,
    BOOKING_CANCELLED,
    BOOKING_COMPLETED,
    BOOKING_DECLINED,
    BOOKING_PENDING,
)

ACCESS_DENIED_TEXT = {
    "ru": "Это действие доступно только участнику записи.",
    "uz": "Bu amal faqat yozuv ishtirokchisiga ochiq.",
}







async def deny_access(cb: CallbackQuery) -> None:
    lang = await get_user_lang(cb.from_user.id)
    logging.warning(
        "access.denied user_id=%s callback=%s", cb.from_user.id, cb.data
    )
    await cb.answer(ACCESS_DENIED_TEXT[lang], show_alert=True)


def build_booking_card(booking: db.Booking, footer: str | None = None) -> str:
    """
    Карточка заявки для мастера. Данные берём из базы, а не из текста сообщения:
    текст сообщения — ненадёжный источник, он ломается при любой смене шаблона.
    """
    service_name = (
        booking.service.catalog_service.name
        if booking.service and booking.service.catalog_service
        else "Услуга не указана"
    )
    card = (
        "<b>Новая заявка</b>\n\n"
        f"Клиент: {escape(booking.user.first_name or 'Клиент')}\n"
        f"Контакт: {escape(booking.user.phone_number or 'не указан')}\n"
        f'<a href="tg://user?id={booking.user.telegram_id}">Написать в Telegram</a>\n'
        f"Услуга: {escape(service_name)}\n"
        f"Дата и время: {escape(timeutils.format_slot(booking.starts_at))}"
    )
    if footer:
        card += f"\n\n<b>{footer}</b>"
    return card


















def get_registration_text(key: str, lang: str) -> str:
    messages = {
        "choose_language": {
            "ru": "Добро пожаловать в BarberBot. Для начала выберите язык.",
            "uz": "BarberBot ga xush kelibsiz. Davom etish uchun tilni tanlang.",
        },
        "ask_name": {
            "ru": "Как вас зовут?\nОтправьте имя и фамилию одним сообщением.",
            "uz": "Ismingiz va familiyangizni bitta xabarda yuboring.",
        },
        "ask_contact": {
            "ru": "Остался последний шаг: отправьте номер телефона кнопкой ниже или введите вручную.",
            "uz": "Oxirgi qadam: telefon raqamingizni pastdagi tugma orqali yuboring yoki qo'lda kiriting.",
        },
        "ask_phone_manual": {
            "ru": "Введите номер телефона в формате +998901234567 или 901234567.",
            "uz": "Telefon raqamingizni +998901234567 yoki 901234567 formatida kiriting.",
        },
        "invalid_name": {
            "ru": "Введите имя чуть подробнее, минимум 2 символа.",
            "uz": "Iltimos, ismni to'liqroq kiriting, kamida 2 ta belgi.",
        },
        "invalid_phone": {
            "ru": "Не удалось распознать номер. Пример: +998901234567",
            "uz": "Raqamni aniqlab bo'lmadi. Misol: +998901234567",
        },
        "contact_self_only": {
            "ru": "Пожалуйста, отправьте свой контакт или введите свой номер вручную.",
            "uz": "Iltimos, o'zingizning kontaktingizni yuboring yoki raqamni qo'lda kiriting.",
        },
        "registration_done": {
            "ru": "Регистрация завершена. Теперь доступны запись, избранные мастера и профиль.",
            "uz": "Ro'yxatdan o'tish tugadi. Endi bron qilish, sevimli ustalar va profil ochiq.",
        },
        "registration_required": {
            "ru": "Сначала завершите регистрацию через /start, чтобы записываться и пользоваться меню.",
            "uz": "Avval /start orqali ro'yxatdan o'tishni yakunlang, shundan keyin bron va menyu ochiladi.",
        },
    }
    return messages[key].get(lang, messages[key]["ru"])


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


def normalize_phone_number(raw_phone: str | None) -> str | None:
    if not raw_phone:
        return None
    cleaned = re.sub(r"[^\d+]", "", raw_phone.strip())
    if cleaned.startswith("+"):
        digits = "+" + re.sub(r"\D", "", cleaned)
    else:
        digits = re.sub(r"\D", "", cleaned)
        if digits.startswith("998"):
            digits = "+" + digits
        elif len(digits) == 9:
            digits = "+998" + digits
        elif len(digits) == 12:
            digits = "+" + digits
        else:
            return None
    if re.fullmatch(r"\+\d{9,15}", digits):
        return digits
    return None


async def get_user_by_telegram_id(telegram_id: int) -> db.User | None:
    async with db.async_session() as session:
        return await session.scalar(select(db.User).where(db.User.telegram_id == telegram_id))


async def get_user_lang(telegram_id: int, default: str = "ru") -> str:
    user = await get_user_by_telegram_id(telegram_id)
    return user.language_code if user and user.language_code else default


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


async def finish_registration(
    message: Message, user: db.User, pending_stylist_id: int | None = None
):
    """
    Завершение регистрации. Если пользователь пришёл по ссылке на мастера,
    сразу показываем его карточку — иначе переход из рассылки теряется
    и человек оказывается в общем меню, не понимая, зачем нажимал.
    """
    keyboard = await get_main_keyboard(message.from_user.id)
    lang = user.language_code or "ru"
    await message.answer(
        get_registration_text("registration_done", lang),
        reply_markup=keyboard,
    )

    if pending_stylist_id:
        logging.info(
            "deeplink.resumed user_id=%s stylist_id=%s",
            message.from_user.id, pending_stylist_id,
        )
        await send_stylist_card(message, pending_stylist_id, lang)


async def prompt_registration_step(message: Message, user: db.User | None, state: FSMContext):
    lang = (user.language_code if user and user.language_code else "ru")

    if user and (user.role == "stylist" or is_registration_complete(user)):
        keyboard = await get_main_keyboard(message.from_user.id)
        welcome_name = user.first_name or message.from_user.first_name or "друг"
        welcome_text = texts.get_text('welcome_back', lang).format(welcome_name)
        await state.clear()
        await message.answer(welcome_text, reply_markup=keyboard)
        return

    if not user or not user.language_code:
        await state.clear()
        await message.answer(
            get_registration_text("choose_language", "ru"),
            reply_markup=get_language_keyboard(),
        )
        return

    if not user.first_name:
        await state.set_state(RegistrationForm.full_name)
        await message.answer(
            get_registration_text("ask_name", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await state.set_state(RegistrationForm.phone_number)
    await message.answer(
        get_registration_text("ask_contact", lang),
        reply_markup=get_contact_request_keyboard(lang),
    )


async def ensure_registered_message(message: Message) -> db.User | None:
    user = await get_user_by_telegram_id(message.from_user.id)
    if user and (user.role == "stylist" or is_registration_complete(user)):
        return user

    lang = user.language_code if user and user.language_code else "ru"
    await message.answer(
        get_registration_text("registration_required", lang),
        reply_markup=ReplyKeyboardRemove(),
    )
    return None


async def ensure_registered_callback(cb: CallbackQuery) -> db.User | None:
    user = await get_user_by_telegram_id(cb.from_user.id)
    if user and (user.role == "stylist" or is_registration_complete(user)):
        return user

    lang = user.language_code if user and user.language_code else "ru"
    await cb.answer(get_registration_text("registration_required", lang), show_alert=True)
    return None

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


# --- Start / Registration ---
def parse_start_payload(raw: str | None) -> int | None:
    """
    Параметр диплинка https://t.me/<bot>?start=<payload>.

    Поддерживаются "12" и "stylist_12": второй вид оставляет место
    для других типов ссылок в будущем. Мусор игнорируется молча —
    пользователь просто попадёт в обычное меню.
    """
    if not raw:
        return None
    value = raw.strip()
    if value.startswith("stylist_"):
        value = value[len("stylist_"):]
    if not value.isdigit():
        return None
    stylist_id = int(value)
    return stylist_id if stylist_id > 0 else None


@dp.message(Command("start"))
async def start(message: Message, state: FSMContext, command: CommandObject | None = None):
    await state.clear()
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))

    stylist_id = parse_start_payload(command.args if command else None)

    # Незарегистрированного сначала проводим через регистрацию, но мастера
    # запоминаем: иначе переход по ссылке из рассылки теряется.
    if stylist_id and not (user and (user.role == "stylist" or is_registration_complete(user))):
        await state.update_data(pending_stylist_id=stylist_id)
        await prompt_registration_step(message, user, state)
        return

    if stylist_id:
        lang = user.language_code if user and user.language_code else "ru"
        logging.info("deeplink.stylist user_id=%s stylist_id=%s", message.from_user.id, stylist_id)
        await message.answer(
            {"ru": "Открываю карточку мастера...", "uz": "Maestro kartasi ochilmoqda..."}[lang],
            reply_markup=await get_main_keyboard(message.from_user.id),
        )
        if await send_stylist_card(message, stylist_id, lang):
            return

    await prompt_registration_step(message, user, state)


@dp.callback_query(F.data.startswith("lang_"))
async def lang_choice(cb: CallbackQuery, state: FSMContext):
    lang = cb.data.split("_")[1]

    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == cb.from_user.id))
        if not user:
            user = db.User(telegram_id=cb.from_user.id, language_code=lang)
            session.add(user)
        else:
            user.language_code = lang
        await session.commit()

    if user and (user.role == 'stylist' or is_registration_complete(user)):
        await state.clear()
        keyboard = await get_main_keyboard(cb.from_user.id)
        welcome_name = user.first_name or cb.from_user.first_name or ""
        await cb.message.edit_text(texts.get_text('welcome_back', lang).format(welcome_name))
        await cb.message.answer(texts.get_text('language_changed', lang), reply_markup=keyboard)
        await cb.answer()
        return

    await state.set_state(RegistrationForm.full_name)
    await cb.message.edit_text(get_registration_text("ask_name", lang))
    await cb.answer()


@dp.message(F.text.in_([texts.get_buttons('ru')['change_language'], texts.get_buttons('uz')['change_language']]))
async def open_language_menu(message: Message, state: FSMContext):
    # ПЕРВЫМ ДЕЛОМ ЧИСТИМ ВСЁ
    await state.clear()
    
    user = await ensure_registered_message(message)
    if not user:
        return

    lang = user.language_code or 'ru'
    await message.answer(
        texts.get_text('language_menu_title', lang),
        reply_markup=get_language_switch_kb(lang),
    )


@dp.callback_query(F.data.startswith("change_lang_"))
async def change_language(cb: CallbackQuery):
    user = await ensure_registered_callback(cb)
    if not user:
        return

    lang = cb.data.split("_")[-1]
    async with db.async_session() as session:
        db_user = await session.scalar(select(db.User).where(db.User.telegram_id == cb.from_user.id))
        if db_user:
            db_user.language_code = lang
            await session.commit()

    keyboard = await get_main_keyboard(cb.from_user.id)
    await cb.message.edit_text(texts.get_text('language_changed', lang), reply_markup=None)
    await cb.message.answer(texts.get_text('welcome_back', lang).format(user.first_name or cb.from_user.first_name or ""), reply_markup=keyboard)
    await cb.answer()


@dp.message(RegistrationForm.full_name)
async def process_registration_name(message: Message, state: FSMContext):
    full_name = (message.text or "").strip()

    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))
        lang = user.language_code if user and user.language_code else "ru"

        if len(full_name) < 2:
            await message.answer(get_registration_text("invalid_name", lang))
            return

        if not user:
            user = db.User(telegram_id=message.from_user.id, language_code=lang)
            session.add(user)

        user.first_name = full_name
        await session.commit()

    await state.set_state(RegistrationForm.phone_number)
    await message.answer(
        get_registration_text("ask_contact", lang),
        reply_markup=get_contact_request_keyboard(lang),
    )


@dp.message(RegistrationForm.phone_number, F.contact)
async def process_registration_contact(message: Message, state: FSMContext):
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))
        lang = user.language_code if user and user.language_code else "ru"

        if not message.contact or message.contact.user_id != message.from_user.id:
            await message.answer(get_registration_text("contact_self_only", lang))
            return

        if not user:
            user = db.User(telegram_id=message.from_user.id, language_code=lang)
            session.add(user)

        user.phone_number = normalize_phone_number(message.contact.phone_number) or message.contact.phone_number
        await session.commit()

    pending_stylist_id = (await state.get_data()).get("pending_stylist_id")
    await state.clear()
    await finish_registration(message, user, pending_stylist_id)


@dp.message(RegistrationForm.phone_number, F.text)
async def process_registration_phone_text(message: Message, state: FSMContext):
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))
        lang = user.language_code if user and user.language_code else "ru"

        manual_button = {
            "ru": "✍️ Ввести вручную",
            "uz": "✍️ Qo'lda kiritish",
        }[lang]
        share_button = {
            "ru": "📱 Поделиться контактом",
            "uz": "📱 Kontaktni ulashish",
        }[lang]

        if message.text == share_button:
            await message.answer(
                get_registration_text("ask_contact", lang),
                reply_markup=get_contact_request_keyboard(lang),
            )
            return

        if message.text == manual_button:
            await message.answer(
                get_registration_text("ask_phone_manual", lang),
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        normalized_phone = normalize_phone_number(message.text)
        if not normalized_phone:
            await message.answer(get_registration_text("invalid_phone", lang))
            return

        if not user:
            user = db.User(telegram_id=message.from_user.id, language_code=lang)
            session.add(user)

        user.phone_number = normalized_phone
        await session.commit()

    pending_stylist_id = (await state.get_data()).get("pending_stylist_id")
    await state.clear()
    await finish_registration(message, user, pending_stylist_id)


# --- ПОИСК И ФИЛЬТРЫ (ВЕРСИЯ 3.0 - ФИНАЛЬНАЯ) ---

# --- Вспомогательная функция для показа списка мастеров ---
async def show_stylist_buttons(message: Message, stylists: list, title: str, shop_id_for_back_button: int | None = None):
    if not stylists:
        await message.answer("Мастера по вашему запросу не найдены.")
        return

    btns = []
    for stylist in stylists:
        rating_suffix = f" (⭐ {stylist.avg_rating:.1f})" if stylist.avg_rating else ""
        btns.append([
            InlineKeyboardButton(
                text=f"💇‍♂️ {stylist.name}{rating_suffix}",
                callback_data=f"maestro_{stylist.id}",
            )
        ])

    if shop_id_for_back_button:
        btns.append([InlineKeyboardButton(text="\n️ Назад", callback_data=f"shop_{shop_id_for_back_button}")])

    await message.answer(title, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))


@dp.callback_query(F.data == "search_district")
async def search_by_district_menu(cb: CallbackQuery):
    if not await ensure_registered_callback(cb):
        return

    async with db.async_session() as session:
        districts = (await session.execute(
            select(db.Barbershop.district).distinct().order_by(db.Barbershop.district)
        )).scalars().all()

    if not districts:
        await cb.answer("Пока нет доступны\n районов для поиска.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        *[[InlineKeyboardButton(text=d, callback_data=f"dist_{d}")] for d in districts],
        [InlineKeyboardButton(text="\n️ Назад", callback_data="back_home")],
    ])
    await cb.message.edit_text(
        "Выберите район. Потом можно открыть список под\nодящи\n барбершопов.",
        reply_markup=kb,
    )
    await cb.answer()


async def run_search_input_flow(message: Message, search_type: str) -> bool:
    lang = await get_user_lang(message.from_user.id)

    async with db.async_session() as session:
        if search_type == "name":
            stylists = (await session.execute(
                select(db.Stylist)
                .where(db.Stylist.name.ilike(f"%{message.text}%"))
                .options(joinedload(db.Stylist.user_account))
            )).scalars().all()
            title = {"ru": "Результаты поиска по имени:", "uz": "Ism bo'yicha qidiruv natijalari:"}[lang]
        elif search_type == "id":
            if not (message.text or "").isdigit():
                await message.answer({
                    "ru": "ID должен состоять только из цифр. Попробуйте ещё раз.",
                    "uz": "ID faqat raqamlardan iborat bo'lishi kerak. Qayta urinib ko'ring.",
                }[lang])
                return False
            
            requested_id = int(message.text)
            
            # ИСПРАВЛЕНИЕ: Ищем ТОЛЬКО по основному ID стилиста (тот, что в твоей таблице)
            stylist = await session.scalar(
                select(db.Stylist)
                .where(db.Stylist.id == requested_id)
                .options(joinedload(db.Stylist.user_account))
            )
            
            if stylist and not is_stylist_subscription_active(stylist.user_account):
                expiry_text = stylist.user_account.subscription_until.strftime("%Y-%m-%d") if stylist.user_account and stylist.user_account.subscription_until else None
                await message.answer({
                    "ru": f"Мастер найден, но сейчас недоступен для записи. Срок тарифа истёк: {expiry_text or 'не указан'}.",
                    "uz": f"Maestro topildi, lekin hozir yozilish uchun mavjud emas. Tarif muddati tugagan: {expiry_text or 'koʻrsatilmagan'}.",
                }[lang])
                return False
            
            stylists = [stylist] if stylist else []
            title = {"ru": "Результат поиска по ID:", "uz": "ID bo'yicha qidiruv natijasi:"}[lang]
        else:
            await message.answer({"ru": "Не удалось выполнить поиск. Попробуйте ещё раз.", "uz": "Qidiruvda xatolik yuz berdi."}[lang])
            return False

    stylists = [stylist for stylist in stylists if stylist and is_stylist_subscription_active(stylist.user_account)]

    if not stylists:
        retry_prompt = {
            "id": {
                "ru": "Мастер не найден. Отправьте другой ID или вернитесь в меню поиска.",
                "uz": "Maestro topilmadi. Boshqa ID yuboring yoki qidiruv menyusiga qayting.",
            },
            "name": {
                "ru": "По вашему запросу никого не нашли. Попробуйте другое имя.",
                "uz": "So'rovingiz bo'yicha hech kim topilmadi. Boshqa ism bilan urinib ko'ring.",
            },
        }
        await message.answer(retry_prompt.get(search_type, retry_prompt["name"])[lang])
        return False

    await show_stylist_buttons(message, stylists, title)
    return True

@dp.callback_query(F.data.startswith("search_"))
async def search_start(cb: CallbackQuery, state: FSMContext):
    if not await ensure_registered_callback(cb):
        return

    search_type = cb.data.split("_")[1]
    await state.update_data(search_type=search_type)
    await state.set_state(SearchForm.waiting_for_name)

    lang = await get_user_lang(cb.from_user.id)
    prompt = (
        {"ru": "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0438\u043c\u044f \u0438\u043b\u0438 \u0447\u0430\u0441\u0442\u044c \u0438\u043c\u0435\u043d\u0438 \u043c\u0430\u0441\u0442\u0435\u0440\u0430:", "uz": "Maestroning ismini yoki bir qismini kiriting:"}[lang]
        if search_type == "name"
        else {"ru": "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 ID \u043c\u0430\u0441\u0442\u0435\u0440\u0430 (\u0442\u043e\u043b\u044c\u043a\u043e \u0446\u0438\u0444\u0440\u044b):", "uz": "Maestro ID sini kiriting (faqat raqam):"}[lang]
    )
    await cb.message.edit_text(prompt)
    await cb.answer()


@dp.message(SearchForm.waiting_for_name)
async def process_search_input(message: Message, state: FSMContext):
    # Проверка: если нажата кнопка главного меню - просто сбрасываем состояние и выходим
    if is_client_main_menu_button(message.text):
        await state.clear()
        await state.update_data(search_type=None)
        return # Бот увидит нажатие кнопки меню следующим хендлером

    data = await state.get_data()
    search_type = data.get("search_type")

    if not search_type:
        await state.clear()
        return

    success = await run_search_input_flow(message, search_type)
    if success:
        await state.clear()
        await state.update_data(search_type=None)



@dp.message(F.text.in_([texts.get_buttons("ru")["search_menu"], texts.get_buttons("uz")["search_menu"]]))
async def booking_start_menu(message: Message, state: FSMContext):
    # 1. Полная очистка перед стартом
    await state.clear()
    
    # 2. Проверка регистрации (чтобы мы знали язык и телефон клиента)
    user = await ensure_registered_message(message)
    if not user:
        return

    # 3. СРАЗУ ставим бота в режим ожидания ID
    await state.set_state(SearchForm.waiting_for_name)
    await state.update_data(search_type="id")  # ждём именно ID мастера
    
    lang = user.language_code or "ru"

    # 4. Красивый и понятный текст в стиле Maestro
    text = {
        "ru": (
            "✨ <b>Добро пожаловать в мир Maestro!</b>\n\n"
            "Чтобы мгновенно найти своего мастера и забронировать время, "
            "просто <b>введите его ID номер</b> ниже:\n\n"
            "🆔 <i>Номер указан на табличке с QR-кодом или визитке мастера.</i>"
        ),
        "uz": (
            "✨ <b>Maestro olamiga xush kelibsiz!</b>\n\n"
            "O'z maestroingizni bir zumda topish va vaqtni band qilish uchun "
            "uning <b>ID raqamini</b> pastga yuboring:\n\n"
            "🆔 <i>ID raqami Maestro peshlavhasidagi QR-kod ostida yoki instagram biosida ko'rsatilgan.</i>"
        )
    }[lang]

    # Отправляем сообщение. Мы не убираем Reply-кнопки, чтобы клиент мог передумать 
    # и нажать "Мой профиль", но фокус теперь на вводе цифр.
    await message.answer(text, parse_mode="HTML")

@dp.callback_query(F.data == "back_home")
async def back_home(cb: CallbackQuery):
    await cb.message.delete()
    await booking_start_menu(cb.message)
    await cb.answer()


@dp.callback_query(F.data.startswith("dist_"))
async def show_shops(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    dist = cb.data.split("_", 1)[1]
    async with db.async_session() as session:
        shops = (await session.execute(
            select(db.Barbershop).where(db.Barbershop.district == dist).order_by(db.Barbershop.name)
        )).scalars().all()
        shop_ids = [shop.id for shop in shops]
        stylist_counts = {}
        if shop_ids:
            stylists = (await session.execute(
                select(db.Stylist)
                .where(db.Stylist.barbershop_id.in_(shop_ids))
                .options(joinedload(db.Stylist.user_account))
            )).scalars().all()
            for stylist in stylists:
                if is_stylist_subscription_active(stylist.user_account):
                    stylist_counts[stylist.barbershop_id] = stylist_counts.get(stylist.barbershop_id, 0) + 1

    if not shops:
        await cb.answer({"ru": "В этом районе пока нет барбершопов.", "uz": "Bu tumanda hozircha barbershoplarimiz yo'q."}[lang], show_alert=True)
        return

    visible_shops = [shop for shop in shops if stylist_counts.get(shop.id, 0) > 0]
    if not visible_shops:
        await cb.answer({"ru": "В этом районе пока нет активных мастеров.", "uz": "Bu tumanda hozircha faol maestrolar yo'q."}[lang], show_alert=True)
        return

    btns = [[InlineKeyboardButton(text=f"{shop.name} - {stylist_counts.get(shop.id, 0)}", callback_data=f"shop_{shop.id}")] for shop in visible_shops]
    btns.append([InlineKeyboardButton(text={"ru": "Назад", "uz": "Ortga"}[lang], callback_data="search_district")])

    await cb.message.edit_text(
        {
            "ru": f"Выберите барбершоп в районе <b>{dist}</b>.\nКарту можно открыть в карточке мастера.",
            "uz": f"<b>{dist}</b> tumanidagi barbershopni tanlang.\nXaritani usta kartasidan ochishingiz mumkin.",
        }[lang],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
        parse_mode="HTML",
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("shop_"))
async def show_stylists(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    shop_id = int(cb.data.split("_")[1])
    async with db.async_session() as session:
        stylists = (await session.execute(
            select(db.Stylist)
            .where(db.Stylist.barbershop_id == shop_id)
            .options(joinedload(db.Stylist.user_account))
        )).scalars().all()
        stylists = [stylist for stylist in stylists if is_stylist_subscription_active(stylist.user_account)]
        shop = await session.get(db.Barbershop, shop_id)

    if not stylists:
        await cb.answer({"ru": "В этом салоне пока нет активных мастеров.", "uz": "Bu salonda hozircha faol maestrolar yo'q."}[lang], show_alert=True)
        return

    btns = [[InlineKeyboardButton(text=f"{({'ru': 'Мастер', 'uz': 'Maestro'})[lang]} {s.name}", callback_data=f"maestro_{s.id}")] for s in stylists]
    btns.append([InlineKeyboardButton(text={"ru": "Назад", "uz": "Ortga"}[lang], callback_data=f"dist_{shop.district}")])

    await cb.message.edit_text(
        {
            "ru": f"Выберите мастера в салоне <b>{escape(shop.name)}</b>.",
            "uz": f"<b>{escape(shop.name)}</b> salonidagi maestroni tanlang.",
        }[lang],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
        parse_mode="HTML",
    )
    await cb.answer()

async def load_stylist_card(stylist_id: int, lang: str):
    """
    Данные карточки мастера: сама карточка, клавиатура и фото портфолио.
    Возвращает (None, причина) если мастера нет или он закрыт для записи.
    """
    async with db.async_session() as session:
        stylist = await session.scalar(
            select(db.Stylist)
            .where(db.Stylist.id == stylist_id)
            .options(joinedload(db.Stylist.barbershop), joinedload(db.Stylist.user_account))
        )
        if not stylist:
            return None, {'ru': 'Мастер не найден.', 'uz': 'Maestro topilmadi.'}[lang]
        if not is_stylist_subscription_active(stylist.user_account):
            return None, {
                'ru': 'Этот мастер временно недоступен для записи.',
                'uz': 'Bu maestro hozircha yozuv uchun yopiq.',
            }[lang]

        photos = (await session.execute(
            select(db.Portfolio)
            .where(db.Portfolio.stylist_id == stylist.id)
            .order_by(db.Portfolio.id.desc())
            .limit(3)
        )).scalars().all()

        rating_text = (
            ("★ " * int(round(stylist.avg_rating)))
            if stylist.avg_rating > 0
            else {'ru': 'Нет оценок', 'uz': "Baholar yo'q"}[lang]
        )
        if stylist.reviews_count:
            rating_text += f" ({stylist.reviews_count})"

        caption = (
            f"<b>{({'ru': 'Мастер', 'uz': 'Maestro'})[lang]}: {escape(stylist.name)}</b>\n"
            f"{({'ru': 'Рейтинг', 'uz': 'Reyting'})[lang]}: {rating_text}\n\n"
            f"<b>{({'ru': 'Салон', 'uz': 'Salon'})[lang]}:</b> {escape(stylist.barbershop.name)}\n"
            f"<b>{({'ru': 'Район', 'uz': 'Tuman'})[lang]}:</b> {escape(stylist.barbershop.district)}\n"
            f"<b>{({'ru': 'Адрес', 'uz': 'Manzil'})[lang]}:</b> {escape(stylist.barbershop.address)}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text={'ru': 'Записаться к мастеру', 'uz': 'Maestroga yozilish'}[lang], callback_data=f"book_{stylist.id}")],
            [InlineKeyboardButton(text={'ru': 'Показать на карте', 'uz': "Xaritada ko'rsatish"}[lang], callback_data=f"map_{stylist.barbershop.id}")],
            [InlineKeyboardButton(text={'ru': 'Назад к списку мастеров', 'uz': "Maestrolar ro'yxatiga qaytish"}[lang], callback_data=f"shop_{stylist.barbershop.id}")],
        ])

    return {"caption": caption, "keyboard": kb, "photos": photos}, None


async def send_stylist_card(message: Message, stylist_id: int, lang: str) -> bool:
    """Отправляет карточку мастера новым сообщением. False — если показать нечего."""
    card, error = await load_stylist_card(stylist_id, lang)
    if not card:
        await message.answer(error)
        return False

    if card["photos"]:
        await message.answer_media_group(
            media=[InputMediaPhoto(media=p.telegram_photo_file_id) for p in card["photos"]]
        )
    await message.answer(card["caption"], reply_markup=card["keyboard"], parse_mode="HTML")
    return True


@dp.callback_query(F.data.startswith("stylist_"))
async def show_maestro_card(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    stylist_id = int(cb.data.split("_")[1])

    card, error = await load_stylist_card(stylist_id, lang)
    if not card:
        await cb.answer(error, show_alert=True)
        return

    if card["photos"]:
        await cb.message.answer_media_group(
            media=[InputMediaPhoto(media=p.telegram_photo_file_id) for p in card["photos"]]
        )
    await cb.message.answer(card["caption"], reply_markup=card["keyboard"], parse_mode="HTML")

    await cb.message.delete()
    await cb.answer()

@dp.callback_query(F.data.startswith("back_to_stylist_"))
async def back_to_stylist_card(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    stylist_id = int(cb.data.split("_")[-1])
    await cb.message.edit_text({'ru': '\u041f\u0440\u043e\u0444\u0438\u043b\u044c \u043c\u0430\u0441\u0442\u0435\u0440\u0430 \u0437\u0430\u0433\u0440\u0443\u0436\u0430\u0435\u0442\u0441\u044f...', 'uz': 'Maestro profili yuklanmoqda...'}[lang])

    async with db.async_session() as session:
        query = select(db.Stylist).where(db.Stylist.id == stylist_id).options(joinedload(db.Stylist.barbershop), joinedload(db.Stylist.user_account))
        stylist = await session.scalar(query)
        if not stylist:
            await cb.answer({'ru': '\u041c\u0430\u0441\u0442\u0435\u0440 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.', 'uz': 'Maestro topilmadi.'}[lang], show_alert=True)
            return
        if not is_stylist_subscription_active(stylist.user_account):
            await cb.answer({'ru': '\u042d\u0442\u043e\u0442 \u043c\u0430\u0441\u0442\u0435\u0440 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d \u0434\u043b\u044f \u0437\u0430\u043f\u0438\u0441\u0438.', 'uz': 'Bu maestro hozircha yozuv uchun yopiq.'}[lang], show_alert=True)
            return
        photos = (await session.execute(
            select(db.Portfolio).where(db.Portfolio.stylist_id == stylist.id).order_by(db.Portfolio.id.desc()).limit(3)
        )).scalars().all()

    rating_text = ("★ " * int(round(stylist.avg_rating))) if stylist.avg_rating > 0 else ({'ru': 'Нет оценок', 'uz': "Baholar yo'q"}[lang])
    labels = {
        "master": {"ru": "Мастер", "uz": "Maestro"}[lang],
        "rating": {"ru": "Рейтинг", "uz": "Reyting"}[lang],
        "salon": {"ru": "Салон", "uz": "Salon"}[lang],
        "district": {"ru": "Район", "uz": "Tuman"}[lang],
        "address": {"ru": "Адрес", "uz": "Manzil"}[lang],
    }
    caption = (
        f"<b>{labels['master']}: {escape(stylist.name)}</b>\n"
        f"{labels['rating']}: {rating_text}\n\n"
        f"<b>{labels['salon']}:</b> {stylist.barbershop.name}\n"
        f"<b>{labels['district']}:</b> {stylist.barbershop.district}\n"
        f"<b>{labels['address']}:</b> {stylist.barbershop.address}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text={'ru': '\u0417\u0430\u043f\u0438\u0441\u0430\u0442\u044c\u0441\u044f \u043a \u043c\u0430\u0441\u0442\u0435\u0440\u0443', 'uz': 'Maestroga yozilish'}[lang], callback_data=f"book_{stylist.id}")],
        [InlineKeyboardButton(text={'ru': '\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u043d\u0430 \u043a\u0430\u0440\u0442\u0435', 'uz': "Xaritada ko'rsatish"}[lang], callback_data=f"map_{stylist.barbershop.id}")],
        [InlineKeyboardButton(text={'ru': '\u041d\u0430\u0437\u0430\u0434 \u043a \u0441\u043f\u0438\u0441\u043a\u0443 \u043c\u0430\u0441\u0442\u0435\u0440\u043e\u0432', 'uz': "Maestrolar ro'yxatiga qaytish"}[lang], callback_data=f"shop_{stylist.barbershop.id}")],
    ])

    if photos:
        media_group = [InputMediaPhoto(media=p.telegram_photo_file_id) for p in photos]
        await cb.message.answer_media_group(media=media_group)
        await cb.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    else:
        await cb.message.answer(caption, reply_markup=kb, parse_mode="HTML")

    await cb.message.delete()
    await cb.answer()

@dp.callback_query(F.data.startswith("map_"))
async def show_map(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    shop_id = int(cb.data.split("_")[1])
    async with db.async_session() as session:
        shop = await session.get(db.Barbershop, shop_id)
    if shop and shop.latitude and shop.longitude:
        await cb.message.answer_location(latitude=shop.latitude, longitude=shop.longitude)
        await cb.answer({'ru': 'Карта отправлена', 'uz': 'Xarita yuborildi'}[lang])
    else:
        await cb.answer({'ru': 'Для этого салона координаты не указаны.', 'uz': 'Bu salon uchun koordinatalar kiritilmagan.'}[lang], show_alert=True)


@dp.callback_query(F.data.startswith(("book_", "maestro_", "stylist_")))
async def show_services(cb: CallbackQuery, state: FSMContext):
    if not await ensure_registered_callback(cb):
        return

    lang = await get_user_lang(cb.from_user.id)
    maestro_id = int(cb.data.split("_")[-1])
    await update_booking_draft(state, stylist_id=maestro_id)

    async with db.async_session() as session:
        services_query = select(db.Service).where(db.Service.stylist_id == maestro_id).options(joinedload(db.Service.catalog_service))
        services = (await session.execute(services_query)).scalars().all()
        stylist_query = select(db.Stylist).where(db.Stylist.id == maestro_id).options(joinedload(db.Stylist.barbershop), joinedload(db.Stylist.user_account))
        stylist = await session.scalar(stylist_query)
        if not stylist:
            await cb.answer({"ru": "Мастер не найден.", "uz": "Maestro topilmadi."}[lang], show_alert=True)
            return
        if not is_stylist_subscription_active(stylist.user_account):
            await cb.answer({"ru": "У этого мастера истёк срок тарифа. Выберите другого мастера.", "uz": "Bu maestroning tarifi tugagan. Boshqa maestroni tanlang."}[lang], show_alert=True)
            return
        user = await session.scalar(select(db.User).where(db.User.telegram_id == cb.from_user.id))
        is_favorite = await session.scalar(
            select(db.Favorite).where(db.Favorite.user_id == user.id, db.Favorite.stylist_id == maestro_id)
        )

    btns = []
    for srv in services:
        price = f"{srv.price:,.0f}".replace(",", " ")
        duration_label = {"ru": "мин", "uz": "daq"}[lang]
        btns.append([
            InlineKeyboardButton(
                text=f"{srv.catalog_service.name} - {price} so'm - {srv.duration_min} {duration_label}",
                callback_data=f"srv_{srv.id}",
            )
        ])

    if not services:
        btns.append([
            InlineKeyboardButton(
                text={"ru": "Назад к мастеру", "uz": "Maestroga qaytish"}[lang],
                callback_data=f"back_to_stylist_{stylist.id}",
            )
        ])
        await cb.message.edit_text(
            {
                "ru": f"У <b>{escape(stylist.name)}</b> пока нет добавленных услуг.\nВыберите другого мастера или загляните позже.",
                "uz": f"<b>{escape(stylist.name)}</b> uchun hozircha xizmatlar mavjud emas.\nBoshqa maestroni tanlang yoki keyinroq qayting.",
            }[lang],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
            parse_mode="HTML",
        )
        await cb.answer()
        return

    if not is_favorite:
        btns.append([
            InlineKeyboardButton(
                text={"ru": "Добавить в избранное", "uz": "Sevimlilarga qo'shish"}[lang],
                callback_data=f"fav_add_{stylist.id}",
            )
        ])
    btns.append([
        InlineKeyboardButton(text={"ru": "Назад к мастеру", "uz": "Maestroga qaytish"}[lang], callback_data=f"back_to_stylist_{stylist.id}")
    ])
    await cb.message.edit_text(
        {
            "ru": f"<b>{escape(stylist.name)}</b>\nВыберите услугу для записи.",
            "uz": f"<b>{escape(stylist.name)}</b>\nYozilish uchun xizmatni tanlang.",
        }[lang],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
        parse_mode="HTML",
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("srv_"))
async def choose_service_and_show_calendar(cb: CallbackQuery, state: FSMContext):
    if not await ensure_registered_callback(cb):
        return

    lang = await get_user_lang(cb.from_user.id)
    service_id = int(cb.data.split("_")[1])
    draft = await get_booking_draft(state)
    stylist_id = draft.get("stylist_id")
    if not stylist_id:
        await cb.answer({"ru": "Время выбора истекло. Начните запись заново.", "uz": "Tanlov sessiyasi tugadi. Qaytadan boshlang."}[lang], show_alert=True)
        return

    await update_booking_draft(state, service_id=service_id)
    current_dt = datetime.now()

    async with db.async_session() as session:
        stylist = await session.scalar(
            select(db.Stylist)
            .where(db.Stylist.id == stylist_id)
            .options(joinedload(db.Stylist.user_account))
        )
        if not stylist or not is_stylist_subscription_active(stylist.user_account):
            await cb.answer({"ru": "Запись к этому мастеру временно закрыта.", "uz": "Bu maestroga yozilish vaqtincha yopiq."}[lang], show_alert=True)
            return
        available_dates = await get_available_dates_for_month(session, stylist_id, service_id, current_dt.year, current_dt.month)

    if not available_dates:
        await cb.answer({"ru": "Для этой услуги пока нет свободных дат.", "uz": "Bu xizmat uchun hozircha bo'sh sanalar yo'q."}[lang], show_alert=True)
        return

    kb = utils.generate_calendar(current_dt.year, current_dt.month, maestro_id=stylist_id, available_dates=available_dates)
    await cb.message.edit_text(
        {"ru": "Выберите дату. Активны только дни со свободным временем.", "uz": "Sanani tanlang. Faqat bo'sh vaqti bor kunlar faol."}[lang],
        reply_markup=kb,
    )
    await cb.answer()


@dp.callback_query(F.data == "ignore")
async def ignore_calendar_button(cb: CallbackQuery):
    await cb.answer()


@dp.callback_query(F.data.startswith("dayoff_"))
async def show_dayoff_notice(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    selected_date = cb.data.split("_", 1)[1]
    await cb.answer({
        "ru": f"\u041d\u0430 {selected_date} \u0443 \u043c\u0430\u0441\u0442\u0435\u0440\u0430 \u043d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e\u0433\u043e \u0432\u0440\u0435\u043c\u0435\u043d\u0438. \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0440\u0443\u0433\u043e\u0439 \u0434\u0435\u043d\u044c.",
        "uz": f"{selected_date} sanasida maestro bo'sh emas yoki ishlamaydi. Boshqa kunni tanlang.",
    }[lang], show_alert=True)


@dp.callback_query(F.data.startswith("cal_"))
async def switch_calendar_month(cb: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(cb.from_user.id)
    payload = cb.data[len("cal_"):]
    try:
        ym_part, stylist_id_str = payload.rsplit("_", 1)
        year_str, month_str = ym_part.split("-", 1)
        year = int(year_str)
        month = int(month_str)
        stylist_id = int(stylist_id_str)
    except ValueError:
        await cb.answer({"ru": "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043a\u0440\u044b\u0442\u044c \u043a\u0430\u043b\u0435\u043d\u0434\u0430\u0440\u044c.", "uz": "Kalendarni ochib bo'lmadi."}[lang], show_alert=True)
        return

    draft = await get_booking_draft(state)
    service_id = draft.get("service_id")
    if not service_id:
        await cb.answer({"ru": "Время выбора истекло. Начните запись заново.", "uz": "Tanlov sessiyasi tugadi. Qaytadan boshlang."}[lang], show_alert=True)
        return

    async with db.async_session() as session:
        available_dates = await get_available_dates_for_month(session, stylist_id, service_id, year, month)

    kb = utils.generate_calendar(year, month, maestro_id=stylist_id, available_dates=available_dates)
    await cb.message.edit_text(
        {"ru": "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0430\u0442\u0443. \u0421\u0435\u0440\u044b\u0435 \u0434\u043d\u0438 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b \u0434\u043b\u044f \u0437\u0430\u043f\u0438\u0441\u0438.", "uz": "Sanani tanlang. Xira kunlar yozuv uchun yopiq."}[lang],
        reply_markup=kb,
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("date_"))
async def pick_time(cb: CallbackQuery, state: FSMContext):
    if not await ensure_registered_callback(cb):
        return

    lang = await get_user_lang(cb.from_user.id)
    selected_date_str = cb.data.split("_")[1]
    selected_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
    draft = await get_booking_draft(state)
    if not {"stylist_id", "service_id"} <= draft.keys():
        await cb.answer({"ru": "Время выбора истекло. Начните запись заново.", "uz": "Sessiya tugadi, qaytadan boshlang."}[lang], show_alert=True)
        return

    stylist_id = draft["stylist_id"]
    service_id = draft["service_id"]
    await update_booking_draft(state, date=selected_date_str)
    async with db.async_session() as session:
        schedule, available_slots = await get_available_slots_for_date(session, stylist_id, service_id, selected_date)

    if not schedule:
        await cb.answer({"ru": "\u041c\u0430\u0441\u0442\u0435\u0440 \u0432 \u044d\u0442\u043e\u0442 \u0434\u0435\u043d\u044c \u043d\u0435 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442.", "uz": "Maestro bu kuni ishlamaydi."}[lang], show_alert=True)
        return

    if not available_slots:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text={"ru": "\u041d\u0430\u0437\u0430\u0434 \u043a \u043a\u0430\u043b\u0435\u043d\u0434\u0430\u0440\u044e", "uz": "Kalendarga qaytish"}[lang], callback_data=f"back_to_calendar_{stylist_id}")
        ]])
        await cb.message.edit_text(
            {
                "ru": f"\u041d\u0430 {selected_date_str} \u0441\u0432\u043e\u0431\u043e\u0434\u043d\u044b\u0445 \u0441\u043b\u043e\u0442\u043e\u0432 \u043d\u0435\u0442.\n\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0440\u0443\u0433\u0443\u044e \u0434\u0430\u0442\u0443.",
                "uz": f"{selected_date_str} sanasida bo'sh slotlar yo'q.\nBoshqa sanani tanlang.",
            }[lang],
            reply_markup=back_kb,
        )
        await cb.answer()
        return

    btns, row = [], []
    for slot in available_slots:
        row.append(InlineKeyboardButton(text=slot, callback_data=f"time_{slot}"))
        if len(row) == 3:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    btns.append([
        InlineKeyboardButton(text={"ru": "\u041d\u0430\u0437\u0430\u0434 \u043a \u043a\u0430\u043b\u0435\u043d\u0434\u0430\u0440\u044e", "uz": "Kalendarga qaytish"}[lang], callback_data=f"back_to_calendar_{stylist_id}")
    ])
    await cb.message.edit_text(
        {"ru": f"\u0414\u0430\u0442\u0430: {selected_date_str}\n\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0432\u0440\u0435\u043c\u044f:", "uz": f"Sana: {selected_date_str}\nVaqtni tanlang:"}[lang],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("back_to_calendar_"))
async def back_to_calendar(cb: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(cb.from_user.id)
    stylist_id = int(cb.data.split("_")[-1])
    draft = await get_booking_draft(state)
    service_id = draft.get("service_id")
    if not service_id:
        await cb.answer({"ru": "\u0421\u0435\u0441\u0441\u0438\u044f \u0432\u044b\u0431\u043e\u0440\u0430 \u0438\u0441\u0442\u0435\u043a\u043b\u0430. \u041d\u0430\u0447\u043d\u0438\u0442\u0435 \u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043d\u043e\u0432\u043e.", "uz": "Tanlov sessiyasi tugadi. Qaytadan boshlang."}[lang], show_alert=True)
        return

    current_dt = datetime.strptime(draft.get("date") or datetime.now().strftime("%Y-%m-%d"), "%Y-%m-%d")
    async with db.async_session() as session:
        available_dates = await get_available_dates_for_month(session, stylist_id, service_id, current_dt.year, current_dt.month)

    kb = utils.generate_calendar(current_dt.year, current_dt.month, maestro_id=stylist_id, available_dates=available_dates)
    await cb.message.edit_text(
        {"ru": "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0430\u0442\u0443. \u0410\u043a\u0442\u0438\u0432\u043d\u044b \u0442\u043e\u043b\u044c\u043a\u043e \u0434\u043d\u0438, \u0433\u0434\u0435 \u0435\u0441\u0442\u044c \u0441\u0432\u043e\u0431\u043e\u0434\u043d\u043e\u0435 \u0432\u0440\u0435\u043c\u044f.", "uz": "Sanani tanlang. Faqat bo'sh vaqti bor ish kunlari faol."}[lang],
        reply_markup=kb,
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("time_"))
async def finalize_booking(cb: CallbackQuery, state: FSMContext):
    if not await ensure_registered_callback(cb):
        return

    lang = await get_user_lang(cb.from_user.id)
    selected_time = cb.data.split("_")[1]
    user_id = cb.from_user.id
    data = await get_booking_draft(state)
    if not {"stylist_id", "service_id", "date"} <= data.keys():
        await cb.answer({"ru": "Время выбора истекло. Начните запись заново.", "uz": "Sessiya xatosi. Qaytadan boshlang."}[lang], show_alert=True)
        return

    full_datetime = f"{data['date']} {selected_time}"
    selected_date = datetime.strptime(data['date'], "%Y-%m-%d").date()
    async with db.async_session() as session:
        user_db = await session.scalar(select(db.User).where(db.User.telegram_id == user_id))
        if not user_db or not is_registration_complete(user_db):
            await cb.answer({"ru": "Сначала завершите регистрацию через /start.", "uz": "Avval /start orqali ro'yxatdan o'tishni tugating."}[lang], show_alert=True)
            return
        stylist_profile = await session.scalar(
            select(db.Stylist)
            .where(db.Stylist.id == data['stylist_id'])
            .options(joinedload(db.Stylist.user_account))
        )
        if not stylist_profile or not is_stylist_subscription_active(stylist_profile.user_account):
            await cb.answer({"ru": "Запись к этому мастеру временно закрыта. Выберите другого мастера.", "uz": "Bu maestroga yozilish vaqtincha yopiq. Boshqa maestroni tanlang."}[lang], show_alert=True)
            return
        _, available_slots = await get_available_slots_for_date(session, data['stylist_id'], data['service_id'], selected_date)
        if selected_time not in available_slots:
            await cb.answer({"ru": "Это время уже заняли. Выберите другое.", "uz": "Bu slot endi mavjud emas. Boshqa vaqtni tanlang."}[lang], show_alert=True)
            return
        service = await session.scalar(select(db.Service).where(db.Service.id == data['service_id']).options(joinedload(db.Service.catalog_service)))
        starts_at = timeutils.parse_slot(full_datetime)
        new_booking = db.Booking(
            user_id=user_db.id,
            stylist_id=data['stylist_id'],
            service_id=data['service_id'],
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=service.duration_min),
            status=BOOKING_PENDING,
        )
        session.add(new_booking)
        try:
            await session.commit()
        except IntegrityError:
            # Частичный уникальный индекс uq_active_booking_slot: слот заняли
            # между проверкой свободных слотов и вставкой.
            await session.rollback()
            logging.info(
                "booking.slot_race stylist_id=%s datetime=%s user_id=%s",
                data["stylist_id"], full_datetime, user_id,
            )
            await cb.answer(
                {
                    "ru": "Это время только что заняли. Выберите другое.",
                    "uz": "Bu vaqtni hozirgina band qilishdi. Boshqa vaqtni tanlang.",
                }[lang],
                show_alert=True,
            )
            return
        booking_db_id = new_booking.id
        stylist_user_query = select(db.User.telegram_id).join(db.Stylist, db.Stylist.user_id == db.User.id).where(db.Stylist.id == data['stylist_id'])
        stylist_telegram_id = await session.scalar(stylist_user_query)
        client_name = user_db.first_name or cb.from_user.first_name or "Клиент"
        client_telegram_id = user_db.telegram_id
        client_phone = user_db.phone_number or "не указан"
        service_name = service.catalog_service.name if service and service.catalog_service else "Услуга не указана"

    await clear_booking_draft(state)
    await cb.message.edit_text(
        {
            "ru": f"Заявка отправлена.\n{full_datetime}\n\nМастер посмотрит заявку и ответит в ближайшее время.",
            "uz": f"So'rovingiz yuborildi.\n{full_datetime}\n\nMaestro so'rovni ko'rib chiqadi va tez orada javob beradi.",
        }[lang]
    )

    if stylist_telegram_id:
        admin_text = (
            "<b>Новая заявка</b>\n\n"
            f"Клиент: {escape(client_name)}\n"
            f"Контакт: {escape(client_phone)}\n"
            f'<a href="tg://user?id={client_telegram_id}">Написать в Telegram</a>\n'
            f"Услуга: {escape(service_name)}\n"
            f"Дата и время: {escape(full_datetime)}"
        )
        admin_kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="Подтвердить", callback_data=f"approve_{booking_db_id}"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"decline_{booking_db_id}"),
            ]]
        )
        try:
            await bot.send_message(chat_id=stylist_telegram_id, text=admin_text, reply_markup=admin_kb, parse_mode="HTML")
        except Exception as e:
            logging.warning("notify.new_booking_failed booking_id=%s error=%s", booking_db_id, e)

    await cb.answer()

@dp.callback_query(F.data.startswith("approve_"))
async def approve_booking(cb: CallbackQuery):
    booking_id = int(cb.data.split("_")[-1])

    async with db.async_session() as session:
        booking = await load_booking_for_stylist(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        if booking.status != BOOKING_PENDING:
            await cb.answer("Эта заявка уже обработана.", show_alert=True)
            return

        booking.status = BOOKING_APPROVED
        await session.commit()
        client_lang = booking.user.language_code or "ru"
        client_telegram_id = booking.user.telegram_id
        booking_datetime = timeutils.format_human(booking.starts_at, client_lang)
        card = build_booking_card(booking, footer="Запись подтверждена")

    try:
        await bot.send_message(
            chat_id=client_telegram_id,
            text={
                "ru": (
                    "✨ <b>Прекрасный выбор!</b>\n\n"
                    "Ваша запись подтверждена. Мастер уже готовится к вашему визиту.\n\n"
                    f"📅 Ждём вас: <b>{escape(booking_datetime)}</b>\n\n"
                    "До встречи в Maestro! ✂️"
                ),
                "uz": (
                    "✨ <b>Ajoyib tanlov!</b>\n\n"
                    "Sizning yozuvingiz tasdiqlandi. Maestro tashrifingizga tayyorgarlik ko'rmoqda.\n\n"
                    f"📅 Sizni kutamiz: <b>{escape(booking_datetime)}</b>\n\n"
                    "Maestro'da ko'rishguncha! ✂️"
                ),
            }[client_lang],
            parse_mode="HTML",
        )
    except Exception as e:
        logging.warning("notify.approve_failed booking_id=%s error=%s", booking_id, e)

    await cb.message.edit_text(card, reply_markup=None, parse_mode="HTML")
    await cb.answer("Готово")


@dp.callback_query(F.data.startswith("decline_"))
async def decline_booking(cb: CallbackQuery):
    booking_id = int(cb.data.split("_")[-1])

    async with db.async_session() as session:
        booking = await load_booking_for_stylist(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        if booking.status != BOOKING_PENDING:
            await cb.answer("Эта заявка уже обработана.", show_alert=True)
            return

        booking.status = BOOKING_DECLINED
        await session.commit()
        client_lang = booking.user.language_code or "ru"
        client_telegram_id = booking.user.telegram_id
        booking_datetime = timeutils.format_human(booking.starts_at, client_lang)
        card = build_booking_card(booking, footer="Запись отклонена")

    try:
        await bot.send_message(
            chat_id=client_telegram_id,
            text={
                "ru": (
                    "<b>Запись отклонена.</b>\n\n"
                    f"Время {escape(booking_datetime)} уже недоступно. Пожалуйста, выберите другое."
                ),
                "uz": (
                    "<b>Yozuv rad etildi.</b>\n\n"
                    f"{escape(booking_datetime)} vaqti endi mavjud emas. Iltimos, boshqa vaqtni tanlang."
                ),
            }[client_lang],
            parse_mode="HTML",
        )
    except Exception as e:
        logging.warning("notify.decline_failed booking_id=%s error=%s", booking_id, e)

    await cb.message.edit_text(card, reply_markup=None, parse_mode="HTML")
    await cb.answer("Готово")


@dp.callback_query(F.data.startswith("complete_"))
async def complete_booking(cb: CallbackQuery):
    booking_id = int(cb.data.split("_")[1])

    async with db.async_session() as session:
        booking = await load_booking_for_stylist(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        if booking.status == BOOKING_COMPLETED:
            await cb.answer("Визит уже отмечен как завершённый.", show_alert=True)
            return

        booking.status = BOOKING_COMPLETED
        await session.commit()
        client_lang = booking.user.language_code or "ru"
        client_telegram_id = booking.user.telegram_id
        card = build_booking_card(booking, footer="Визит завершён")

    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="★", callback_data=f"rate_{booking_id}_1"),
            InlineKeyboardButton(text="★★", callback_data=f"rate_{booking_id}_2"),
            InlineKeyboardButton(text="★★★", callback_data=f"rate_{booking_id}_3"),
            InlineKeyboardButton(text="★★★★", callback_data=f"rate_{booking_id}_4"),
            InlineKeyboardButton(text="★★★★★", callback_data=f"rate_{booking_id}_5"),
        ]])
        await bot.send_message(
            chat_id=client_telegram_id,
            text={
                "ru": "Как вам сервис? Пожалуйста, оцените визит.",
                "uz": "Xizmat sizga yoqdimi? Iltimos, baho bering.",
            }[client_lang],
            reply_markup=kb,
        )
    except Exception as e:
        logging.warning("notify.rating_request_failed booking_id=%s error=%s", booking_id, e)

    await cb.message.edit_text(card, reply_markup=None, parse_mode="HTML")
    await cb.answer("Готово")


@dp.message(F.text.in_([texts.get_buttons("ru")["my_profile"], texts.get_buttons("uz")["my_profile"]]))
async def show_profile(message: Message, state: FSMContext):
    # ПЕРВЫМ ДЕЛОМ ЧИСТИМ ВСЁ
    await state.clear()
    
    user = await ensure_registered_message(message)
    if not user:
        return

    user_id = message.from_user.id
    lang = user.language_code or "ru"

    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == user_id))
        query = (
            select(db.Booking)
                .where(db.Booking.user_id == user.id)
                .options(
                    joinedload(db.Booking.stylist).joinedload(db.Stylist.barbershop),
                    joinedload(db.Booking.service).joinedload(db.Service.catalog_service)
                )
                .order_by(db.Booking.starts_at.desc())
        )
        bookings = (await session.execute(query)).scalars().all()

    lang_label = texts.get_text("profile_lang_ru", lang) if user.language_code == "ru" else texts.get_text("profile_lang_uz", lang)
    profile_header = (
        f"👤 <b>{escape(user.first_name or '')}</b>\n"
        f"📞 <code>{user.phone_number}</code>\n"
        f"🌐 {lang_label}\n\n"
    )

    if not bookings:
        await message.answer(profile_header + f"📭 {texts.get_text('profile_empty', lang)}", parse_mode="HTML")
        return

    response_text = profile_header + f"{texts.get_text('profile_bookings_title', lang)}\n{'=' * 20}\n"
    kb_builder = []

    for booking in bookings:
        status_icon = texts.get_text("status_pending", lang)
        if booking.status == BOOKING_APPROVED:
            status_icon = texts.get_text("status_approved", lang)
        elif booking.status == BOOKING_DECLINED:
            status_icon = texts.get_text("status_declined", lang)
        elif booking.status == BOOKING_COMPLETED:
            status_icon = texts.get_text("status_completed", lang)
        elif booking.status == BOOKING_CANCELLED:
            status_icon = texts.get_text("status_cancelled", lang)

        response_text += (
            f"\n<b>{timeutils.format_human(booking.starts_at, lang)}</b>\n"
            f"Барбершоп: {escape(booking.stylist.barbershop.name)}\n"
            f"{texts.get_text('master_label', lang)}: {escape(booking.stylist.name)}\n"
            f"\u0423\u0441\u043b\u0443\u0433\u0430: {escape(booking.service.catalog_service.name)} ({booking.service.price:,.0f} so'm)\n"
            f"{texts.get_text('status_label', lang)}: <b>{status_icon}</b>\n"
            f"{'-' * 20}\n"
        )
        if booking.status in ACTIVE_BOOKING_STATUSES:
            kb_builder.append([InlineKeyboardButton(text=f"{texts.get_text('cancel_booking', lang)}: {timeutils.format_human(booking.starts_at, lang)}", callback_data=f"booking_cancel_{booking.id}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=kb_builder)
    await message.answer(response_text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data.startswith("booking_cancel_"))
async def cancel_booking(cb: CallbackQuery):
    booking_id = int(cb.data.split("_")[-1])
    lang = await get_user_lang(cb.from_user.id)

    async with db.async_session() as session:
        # Отменить запись может только сам клиент — владельца сверяем в запросе.
        booking = await load_booking_for_client(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        if booking.status in (BOOKING_DECLINED, BOOKING_COMPLETED):
            await cb.answer(
                {"ru": "Эту запись уже нельзя отменить.", "uz": "Bu yozuvni endi bekor qilib bo'lmaydi."}[lang],
                show_alert=True,
            )
            return

        stylist_telegram_id = (
            booking.stylist.user_account.telegram_id
            if booking.stylist and booking.stylist.user_account
            else None
        )
        client_name = booking.user.first_name or "Клиент"
        booking_datetime = timeutils.format_slot(booking.starts_at)

        # Статус вместо удаления: история визитов нужна для статистики и follow-up.
        booking.status = BOOKING_CANCELLED
        await session.commit()

    if stylist_telegram_id:
        notification_text = (
            "<b>Запись отменена</b>\n\n"
            f"Клиент: {escape(client_name)}\n"
            f"Дата и время: {escape(booking_datetime)}\n\n"
            "Это окно снова свободно для записи."
        )
        try:
            await bot.send_message(chat_id=stylist_telegram_id, text=notification_text, parse_mode="HTML")
        except Exception as e:
            logging.warning("notify.cancel_failed booking_id=%s error=%s", booking_id, e)

    await cb.answer({"ru": "Запись отменена.", "uz": "Yozuv bekor qilindi."}[lang], show_alert=True)
    await cb.message.delete()
    await cb.message.answer(
        {"ru": "Ваша запись успешно отменена.", "uz": "Yozuvingiz muvaffaqiyatli bekor qilindi."}[lang]
    )


# --- ИЗБРАННЫЕ МАСТЕРА ---

# Хэндлер для кнопки "⭐ Мои мастера"
@dp.message(F.text.in_([texts.get_buttons("ru")["my_masters"], texts.get_buttons("uz")["my_masters"]]))
async def show_favorites(message: Message, state: FSMContext):
    # ПЕРВЫМ ДЕЛОМ ЧИСТИМ ВСЁ
    await state.clear()
    
    user = await ensure_registered_message(message)
    if not user:
        return

    lang = user.language_code or "ru"
    async with db.async_session() as session:
        user = await session.scalar(
            select(db.User)
                .where(db.User.telegram_id == message.from_user.id)
                .options(joinedload(db.User.favorite_stylists))
        )

    if not user or not user.favorite_stylists:
        await message.answer(texts.get_text("favorites_empty", lang))
        return

    btns = [[InlineKeyboardButton(text=f"💇‍♂️ {stylist.name}", callback_data=f"stylist_{stylist.id}"), 
             InlineKeyboardButton(text="❌", callback_data=f"fav_rem_{stylist.id}")] for stylist in user.favorite_stylists]
    
    await message.answer(
        f"<b>{texts.get_text('favorites_title', lang)}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
        parse_mode="HTML"
    )
    
# Хэндлер для добавления в избранное
@dp.callback_query(F.data.startswith("fav_add_"))
async def add_favorite(cb: CallbackQuery):
    stylist_id = int(cb.data.split("_")[2])
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == cb.from_user.id))

        # Проверяем, нет ли уже в избранном
        existing = await session.scalar(
            select(db.Favorite).where(db.Favorite.user_id == user.id, db.Favorite.stylist_id == stylist_id))
        if not existing:
            session.add(db.Favorite(user_id=user.id, stylist_id=stylist_id))
            await session.commit()
            await cb.answer("\n Мастер добавлен в избранное!", show_alert=True)
        else:
            await cb.answer("Этот мастер уже в избранном.", show_alert=True)


# Хэндлер для удаления из избранного
@dp.callback_query(F.data.startswith("fav_rem_"))
async def remove_favorite(cb: CallbackQuery):
    stylist_id = int(cb.data.split("_")[2])
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == cb.from_user.id))
        fav_to_delete = await session.scalar(
            select(db.Favorite).where(db.Favorite.user_id == user.id, db.Favorite.stylist_id == stylist_id))
        if fav_to_delete:
            await session.delete(fav_to_delete)
            await session.commit()
            await cb.answer("Мастер удален из избранного.", show_alert=True)
            # Обновляем сообщение со списком
            await show_favorites(cb.message)
            await cb.message.delete()



# --- УПРАВЛЕНИЕ ПОРТФОЛИО ---

@dp.message(F.text == "🖼 Мое портфолио")
async def manage_portfolio(message: Message, state: FSMContext):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    async with db.async_session() as session:
        photos = (await session.execute(
            select(db.Portfolio)
            .where(db.Portfolio.stylist_id == stylist.id)
            .order_by(db.Portfolio.id.desc())
            .limit(3)
        )).scalars().all()

    if photos:
        media_group = [InputMediaPhoto(media=photo.telegram_photo_file_id) for photo in photos]
        await message.answer_media_group(media=media_group)

    await state.set_state(PortfolioForm.waiting_for_photo)
    await message.answer(
        f"Сейчас в вашем портфолио: <b>{len(photos)}</b> фото.\n"
        "Отправьте новое фото сообщением в чат. Когда закончите, нажмите кнопку ниже.",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Готово")]], resize_keyboard=True),
        parse_mode="HTML",
    )

@dp.message(PortfolioForm.waiting_for_photo, F.photo)
async def process_portfolio_photo(message: Message, state: FSMContext):
    # Берем самое качественное фото из предложенны

    file_id = message.photo[-1].file_id

    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))
        stylist = await session.scalar(select(db.Stylist).where(db.Stylist.user_id == user.id))

        # Со
# раняем file_id в базу
        new_photo = db.Portfolio(stylist_id=stylist.id, telegram_photo_file_id=file_id)
        session.add(new_photo)
        await session.commit()

    await message.answer("Фото добавлено в портфолио.")


# Вы
# од из режима добавления фото
@dp.message(PortfolioForm.waiting_for_photo, F.text == "Готово")
async def done_adding_photos(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из режима добавления фото.", reply_markup=await get_main_keyboard(message.from_user.id))

# В
# од в админ-панель
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))

    keyboard = await get_main_keyboard(message.from_user.id)
    if user and user.role == "stylist" and not is_stylist_subscription_active(user):
        await message.answer(get_subscription_menu_text(user), parse_mode="HTML", reply_markup=keyboard)
        return

    await message.answer(
        " Boshqaruv paneliga xush kelibsiz! Ishlaringizga rivoj!\n\n"
        "Добро пожаловать в панель управления! Успехов в работе!",
        reply_markup=keyboard,
    )

@dp.message(F.text == "↩️ Выйти из админ-панели")
async def exit_admin_panel(message: Message):
    await message.answer("Вы вернулись в главное меню.", reply_markup=await get_main_keyboard(message.from_user.id))


@dp.message(F.text == "💳 Срок тарифа")
async def show_tariff_status(message: Message):
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))
    await message.answer(get_subscription_menu_text(user), parse_mode="HTML", reply_markup=await get_main_keyboard(message.from_user.id))

@dp.message(F.text == "📓 Мои записи")
async def show_bookings_menu(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☀️ На сегодня", callback_data="view_bookings_today")],
        [InlineKeyboardButton(text="📅 На неделю", callback_data="view_bookings_week")],
        [InlineKeyboardButton(text="📚 Все записи", callback_data="view_bookings_all")]
    ])
    
    await message.answer("Выберите период для просмотра записей:", reply_markup=kb)
    
@dp.callback_query(F.data.startswith("view_bookings_"))
async def process_view_bookings(cb: CallbackQuery):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        return

    period = cb.data.split("_")[-1]
    today_dt = datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")
    
    async with db.async_session() as session:
        # Базовый запрос: только активные и завершенные будущие записи
        query = select(db.Booking).where(
            db.Booking.stylist_id == stylist.id,
            db.Booking.status.in_(ACTIVE_BOOKING_STATUSES)  # не показываем отклонённые и старые
        ).options(
            joinedload(db.Booking.user), 
            joinedload(db.Booking.service).joinedload(db.Service.catalog_service)
        )

        if period == "today":
            day_start, day_end = timeutils.day_bounds(today_dt.date())
            query = query.where(db.Booking.starts_at >= day_start, db.Booking.starts_at < day_end)
            title = f"☀️ Записи на сегодня ({today_str})"
        
        elif period == "week":
            week_start, week_end = timeutils.range_bounds(
                today_dt.date(), today_dt.date() + timedelta(days=6)
            )
            end_week = week_end.strftime("%Y-%m-%d")
            query = query.where(db.Booking.starts_at >= week_start, db.Booking.starts_at < week_end)
            title = f"📅 Записи на неделю (до {end_week})"
        
        else: # "all" — теперь это "Все будущие записи"
            query = query.where(db.Booking.starts_at >= timeutils.now())
            title = "📚 Все предстоящие записи"

        query = query.order_by(db.Booking.starts_at)
        result = await session.execute(query)
        bookings = result.scalars().all()

    if not bookings:
        await cb.message.edit_text(f"<b>{title}</b>\n\n📭 Актуальных записей нет.", parse_mode="HTML")
        await cb.answer()
        return

    await cb.message.edit_text(f"<b>{title}</b>\nНайдено: {len(bookings)}", parse_mode="HTML")
    
    for b in bookings:
        try:
            client_name = b.user.first_name if b.user else "Клиент"
            service_name = b.service.catalog_service.name if (b.service and b.service.catalog_service) else "Услуга"
            display_date = timeutils.format_human(b.starts_at)
            
            status_emoji = "⏳" if b.status == BOOKING_PENDING else "✅"
            
            text = (
                f"{status_emoji} <b>{display_date}</b>\n"
                f"👤 {client_name}\n"
                f"✂️ {service_name}\n"
                f"📞 <code>{b.user.phone_number if b.user else 'не указан'}</code>"
            )
            
            kb = None
            if b.status == BOOKING_APPROVED:
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🏁 Завершить визит", callback_data=f"complete_{b.id}")
                ]])
            
            await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Error rendering booking {b.id}: {e}")
            continue
    
    await cb.answer()

@dp.callback_query(F.data == "schedule_close")
async def schedule_close(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Управление расписанием закрыто.")
    await cb.answer()


@dp.callback_query(F.data == "cancel_fsm")
async def cancel_fsm_handler(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Действие отменено.", reply_markup=None)
    await cb.answer()


async def render_schedule_overview(target, stylist: db.Stylist):
    async with db.async_session() as session:
        schedules = (await session.execute(
            select(db.Schedule)
            .where(db.Schedule.stylist_id == stylist.id)
            .order_by(db.Schedule.day_of_week)
        )).scalars().all()
        special_dates = (await session.execute(
            select(db.SpecialSchedule)
            .where(db.SpecialSchedule.stylist_id == stylist.id, db.SpecialSchedule.work_date >= date.today())
            .order_by(db.SpecialSchedule.work_date)
        )).scalars().all()
        schedule_map = {item.day_of_week: item for item in schedules}
    await target.edit_text(
        build_schedule_overview_text(stylist.name, schedule_map, special_dates),
        reply_markup=get_schedule_management_kb(schedule_map),
        parse_mode="HTML",
    )


async def render_special_dates_calendar(target, stylist: db.Stylist, year: int, month: int):
    async with db.async_session() as session:
        special_dates = await load_special_dates(session, stylist.id)
    await target.edit_text(
        build_special_dates_text(stylist.name, year, month, special_dates),
        reply_markup=get_special_dates_calendar_kb(year, month, stylist.id),
        parse_mode="HTML",
    )


@dp.message(F.text == "🕒 Управление расписанием")
async def manage_schedule(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    async with db.async_session() as session:
        schedules = (await session.execute(
            select(db.Schedule)
            .where(db.Schedule.stylist_id == stylist.id)
            .order_by(db.Schedule.day_of_week)
        )).scalars().all()
        special_dates = (await session.execute(
            select(db.SpecialSchedule)
            .where(db.SpecialSchedule.stylist_id == stylist.id, db.SpecialSchedule.work_date >= date.today())
            .order_by(db.SpecialSchedule.work_date)
        )).scalars().all()
        schedule_map = {item.day_of_week: item for item in schedules}

    await message.answer(
        build_schedule_overview_text(stylist.name, schedule_map, special_dates),
        reply_markup=get_schedule_management_kb(schedule_map),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "schedule_weekly")
async def back_to_weekly_schedule(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    await state.clear()
    await render_schedule_overview(cb.message, stylist)
    await cb.answer()


@dp.callback_query(F.data == "schedule_special_dates")
async def open_special_dates(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    await state.clear()
    today = date.today()
    await render_special_dates_calendar(cb.message, stylist, today.year, today.month)
    await cb.answer()


@dp.callback_query(F.data.startswith("spec_cal_"))
async def switch_special_dates_month(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    payload = cb.data[len("spec_cal_"):]
    ym_part, _ = payload.rsplit("_", 1)
    year_str, month_str = ym_part.split("-", 1)
    await render_special_dates_calendar(cb.message, stylist, int(year_str), int(month_str))
    await cb.answer()


@dp.callback_query(F.data.startswith("specdate_"))
async def open_special_date_details(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    payload = cb.data[len("specdate_"):]
    target_date, _ = payload.rsplit("_", 1)
    work_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    async with db.async_session() as session:
        weekly_schedule = await session.scalar(
            select(db.Schedule).where(
                db.Schedule.stylist_id == stylist.id,
                db.Schedule.day_of_week == work_date.isoweekday(),
            )
        )
        special_schedule = await session.scalar(
            select(db.SpecialSchedule).where(
                db.SpecialSchedule.stylist_id == stylist.id,
                db.SpecialSchedule.work_date == work_date,
            )
        )

    await state.clear()
    await cb.message.edit_text(
        build_special_date_detail_text(target_date, weekly_schedule, special_schedule),
        reply_markup=get_special_date_actions_kb(target_date, stylist.id, bool(special_schedule)),
        parse_mode="HTML",
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("special_day_off_"))
async def set_special_day_off(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    payload = cb.data[len("special_day_off_"):]
    target_date, _ = payload.rsplit("_", 1)
    work_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    async with db.async_session() as session:
        special_schedule = await session.scalar(
            select(db.SpecialSchedule).where(
                db.SpecialSchedule.stylist_id == stylist.id,
                db.SpecialSchedule.work_date == work_date,
            )
        )
        if special_schedule:
            special_schedule.is_day_off = True
            special_schedule.start_time = None
            special_schedule.end_time = None
        else:
            session.add(db.SpecialSchedule(stylist_id=stylist.id, work_date=work_date, is_day_off=True))
        await session.commit()
        weekly_schedule = await session.scalar(
            select(db.Schedule).where(
                db.Schedule.stylist_id == stylist.id,
                db.Schedule.day_of_week == work_date.isoweekday(),
            )
        )

    await state.clear()
    await cb.message.edit_text(
        build_special_date_detail_text(target_date, weekly_schedule, db.SpecialSchedule(work_date=work_date, is_day_off=True)),
        reply_markup=get_special_date_actions_kb(target_date, stylist.id, True),
        parse_mode="HTML",
    )
    await cb.answer("День отмечен как выходной.")


@dp.callback_query(F.data.startswith("special_delete_"))
async def delete_special_schedule(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    payload = cb.data[len("special_delete_"):]
    target_date, stylist_id = payload.rsplit("_", 1)
    work_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    async with db.async_session() as session:
        special_schedule = await session.scalar(
            select(db.SpecialSchedule).where(
                db.SpecialSchedule.stylist_id == stylist.id,
                db.SpecialSchedule.work_date == work_date,
            )
        )
        if special_schedule:
            await session.delete(special_schedule)
            await session.commit()

    await state.clear()
    await cb.message.edit_text(
        "Исключение удалено. Для этой даты снова работает недельный шаблон.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⬅️ К календарю", callback_data=f"spec_cal_{target_date[:7]}_{stylist_id}"),
        ]]),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("special_set_hours_"))
async def start_special_hours_setup(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    payload = cb.data[len("special_set_hours_"):]
    target_date, _ = payload.rsplit("_", 1)
    await state.update_data(target_date=target_date)
    await state.set_state(SpecialDateForm.start_time)
    await cb.message.edit_text(
        f"{target_date}: выберите время начала работы.",
        reply_markup=get_special_schedule_time_kb(target_date, "start"),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("special_back_start_"))
async def special_back_to_start(cb: CallbackQuery, state: FSMContext):
    target_date = cb.data[len("special_back_start_"):]
    await state.update_data(target_date=target_date)
    await state.set_state(SpecialDateForm.start_time)
    await cb.message.edit_text(
        f"{target_date}: выберите время начала работы.",
        reply_markup=get_special_schedule_time_kb(target_date, "start"),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("special_start_"))
async def process_special_start_time_choice(cb: CallbackQuery, state: FSMContext):
    target_date, start_t = parse_special_callback_parts(cb.data, "special_start_")
    await state.update_data(target_date=target_date, start_time=start_t)
    await state.set_state(SpecialDateForm.end_time)
    await cb.message.edit_text(
        f"{target_date}: выберите время окончания работы.",
        reply_markup=get_special_schedule_time_kb(target_date, "end", start_t),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("special_end_"))
async def process_special_end_time_choice(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    target_date, end_t = parse_special_callback_parts(cb.data, "special_end_")
    data = await state.get_data()
    start_t = data.get("start_time")

    if not start_t or target_date != data.get("target_date"):
        await state.clear()
        await cb.answer("Сессия выбора времени истекла. Начните заново.", show_alert=True)
        return

    work_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    async with db.async_session() as session:
        special_schedule = await session.scalar(
            select(db.SpecialSchedule).where(
                db.SpecialSchedule.stylist_id == stylist.id,
                db.SpecialSchedule.work_date == work_date,
            )
        )
        if special_schedule:
            special_schedule.is_day_off = False
            special_schedule.start_time = start_t
            special_schedule.end_time = end_t
        else:
            session.add(db.SpecialSchedule(
                stylist_id=stylist.id,
                work_date=work_date,
                start_time=start_t,
                end_time=end_t,
                is_day_off=False,
            ))
        await session.commit()

        weekly_schedule = await session.scalar(
            select(db.Schedule).where(
                db.Schedule.stylist_id == stylist.id,
                db.Schedule.day_of_week == work_date.isoweekday(),
            )
        )
        saved_special = await session.scalar(
            select(db.SpecialSchedule).where(
                db.SpecialSchedule.stylist_id == stylist.id,
                db.SpecialSchedule.work_date == work_date,
            )
        )

    await state.clear()
    await cb.message.edit_text(
        build_special_date_detail_text(target_date, weekly_schedule, saved_special),
        reply_markup=get_special_date_actions_kb(target_date, stylist.id, True),
        parse_mode="HTML",
    )
    await cb.answer(f"На {target_date} сохранены часы: {start_t}-{end_t}")


@dp.callback_query(F.data.startswith("set_day_off_"))
async def set_day_off(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    day_of_week = int(cb.data.split("_")[-1])
    async with db.async_session() as session:
        existing_schedule = await session.scalar(select(db.Schedule).where(db.Schedule.stylist_id == stylist.id, db.Schedule.day_of_week == day_of_week))
        if existing_schedule:
            await session.delete(existing_schedule)
            await session.commit()
    await state.clear()
    await render_schedule_overview(cb.message, stylist)
    await cb.answer(f"{DAY_LABELS[day_of_week]} теперь выходной")


@dp.callback_query(F.data.startswith("set_day_"))
async def process_day_of_week(cb: CallbackQuery, state: FSMContext):
    day_of_week = int(cb.data.split("_")[-1])
    await state.update_data(day_of_week=day_of_week)
    await state.set_state(ScheduleForm.start_time)
    await cb.message.edit_text(
        f"{DAY_LABELS[day_of_week]}: выберите время начала работы.",
        reply_markup=get_schedule_time_kb(day_of_week, "start"),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("schedule_back_start_"))
async def schedule_back_to_start(cb: CallbackQuery, state: FSMContext):
    day_of_week = int(cb.data.split("_")[-1])
    await state.update_data(day_of_week=day_of_week)
    await state.set_state(ScheduleForm.start_time)
    await cb.message.edit_text(
        f"{DAY_LABELS[day_of_week]}: выберите время начала работы.",
        reply_markup=get_schedule_time_kb(day_of_week, "start"),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("schedule_start_"))
async def process_start_time_choice(cb: CallbackQuery, state: FSMContext):
    _, _, day_str, start_t = cb.data.split("_", 3)
    day_of_week = int(day_str)
    await state.update_data(day_of_week=day_of_week, start_time=start_t)
    await state.set_state(ScheduleForm.end_time)
    await cb.message.edit_text(
        f"{DAY_LABELS[day_of_week]}: выберите время окончания работы.",
        reply_markup=get_schedule_time_kb(day_of_week, "end", start_t),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("schedule_end_"))
async def process_end_time_choice(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    _, _, day_str, end_t = cb.data.split("_", 3)
    data = await state.get_data()
    day = int(day_str)
    start_t = data.get("start_time")

    if not start_t or day != data.get("day_of_week"):
        await state.clear()
        await cb.answer("Сессия выбора времени истекла. Начните заново.", show_alert=True)
        return

    async with db.async_session() as session:
        existing_schedule = await session.scalar(select(db.Schedule).where(db.Schedule.stylist_id == stylist.id, db.Schedule.day_of_week == day))
        if existing_schedule:
            existing_schedule.start_time = start_t
            existing_schedule.end_time = end_t
        else:
            session.add(db.Schedule(stylist_id=stylist.id, day_of_week=day, start_time=start_t, end_time=end_t))
        await session.commit()

    await state.clear()
    await render_schedule_overview(cb.message, stylist)
    await cb.answer(f"График на {DAY_LABELS[day]} сохранён: {start_t}-{end_t}")


@dp.message(ScheduleForm.start_time)
async def process_start_time(message: Message, state: FSMContext):
    data = await state.get_data()
    day = data.get("day_of_week")
    if not day:
        await state.clear()
        await message.answer("\u0421\u0435\u0441\u0441\u0438\u044f \u0432\u044b\u0431\u043e\u0440\u0430 \u0432\u0440\u0435\u043c\u0435\u043d\u0438 \u0438\u0441\u0442\u0435\u043a\u043b\u0430. \u041d\u0430\u0447\u043d\u0438\u0442\u0435 \u0437\u0430\u043d\u043e\u0432\u043e.")
        return
    await message.answer(
        f"{DAY_LABELS[day]}: \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0432\u0440\u0435\u043c\u044f \u043d\u0430\u0447\u0430\u043b\u0430 \u0440\u0430\u0431\u043e\u0442\u044b \u043a\u043d\u043e\u043f\u043a\u0430\u043c\u0438 \u043d\u0438\u0436\u0435.",
        reply_markup=get_schedule_time_kb(day, "start"),
    )


@dp.message(ScheduleForm.end_time)
async def process_end_time(message: Message, state: FSMContext):
    data = await state.get_data()
    day = data.get("day_of_week")
    start_t = data.get("start_time")
    if not day or not start_t:
        await state.clear()
        await message.answer("\u0421\u0435\u0441\u0441\u0438\u044f \u0432\u044b\u0431\u043e\u0440\u0430 \u0432\u0440\u0435\u043c\u0435\u043d\u0438 \u0438\u0441\u0442\u0435\u043a\u043b\u0430. \u041d\u0430\u0447\u043d\u0438\u0442\u0435 \u0437\u0430\u043d\u043e\u0432\u043e.")
        return
    await message.answer(
        f"{DAY_LABELS[day]}: \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0432\u0440\u0435\u043c\u044f \u043e\u043a\u043e\u043d\u0447\u0430\u043d\u0438\u044f \u0440\u0430\u0431\u043e\u0442\u044b \u043a\u043d\u043e\u043f\u043a\u0430\u043c\u0438 \u043d\u0438\u0436\u0435.",
        reply_markup=get_schedule_time_kb(day, "end", start_t),
    )


@dp.message(F.text == "✂️ Мои услуги")
async def manage_services(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    async with db.async_session() as session:
        query = select(db.Service).where(db.Service.stylist_id == stylist.id).options(joinedload(db.Service.catalog_service))
        services = (await session.execute(query)).scalars().all()
    if services:
        response_text = "<b>\u0412\u0430\u0448\u0438 \u0443\u0441\u043b\u0443\u0433\u0438:</b>\n\u041a\u043b\u0438\u0435\u043d\u0442\u044b \u0432\u0438\u0434\u044f\u0442 \u0446\u0435\u043d\u0443 \u0438 \u0434\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c.\n\n"
    else:
        response_text = "\u0423 \u0432\u0430\u0441 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442 \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u043d\u044b\u0445 \u0443\u0441\u043b\u0443\u0433. \u0414\u0430\u0432\u0430\u0439\u0442\u0435 \u0441\u043e\u0437\u0434\u0430\u0434\u0438\u043c \u043f\u0435\u0440\u0432\u0443\u044e.\n\n"
    for s in services:
        response_text += f"\u2022 {s.catalog_service.name} - {s.price:,.0f} so'm ({s.duration_min} \u043c\u0438\u043d)\n"
    kb_builder = []
    for s in services:
        kb_builder.append([InlineKeyboardButton(text=f"\u0423\u0434\u0430\u043b\u0438\u0442\u044c: {s.catalog_service.name}", callback_data=f"del_srv_{s.id}")])
    kb_builder.append([InlineKeyboardButton(text="\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u043d\u043e\u0432\u0443\u044e \u0443\u0441\u043b\u0443\u0433\u0443", callback_data="add_service")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=kb_builder)
    await message.answer(response_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("del_srv_"))
async def delete_service(cb: CallbackQuery):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        return

    service_id = int(cb.data.split("_")[2])
    async with db.async_session() as session:
        try:
            service = await session.get(db.Service, service_id)
            if service and service.stylist_id == stylist.id:
                await session.delete(service)
                await session.commit()
                await cb.answer("✅ Услуга успешно удалена", show_alert=True)
                # Обновляем список услуг
                await manage_services(cb.message) 
            else:
                await cb.answer("❌ Ошибка: услуга не найдена", show_alert=True)
        except Exception as e:
            await session.rollback()
            # Если есть связанные записи, выскочит ошибка
            await cb.answer("⚠️ Нельзя удалить услугу, на которую уже есть записи! Сначала удалите записи в профиле.", show_alert=True)
            logging.error(f"Ошибка удаления услуги: {e}")

@dp.callback_query(F.data == "add_service")
async def add_service_start(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    async with db.async_session() as session:
        catalog_services = (await session.execute(select(db.CatalogService))).scalars().all()
    btns = [[InlineKeyboardButton(text=s.name, callback_data=f"cat_srv_{s.id}")] for s in catalog_services]
    btns.append([InlineKeyboardButton(text="Отмена", callback_data="cancel_fsm")])
    await state.set_state(ServiceForm.name)
    await cb.message.edit_text("Выберите тип услуги из каталога:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
    await cb.answer()

@dp.callback_query(ServiceForm.name, F.data.startswith("cat_srv_"))
async def process_service_catalog_choice(cb: CallbackQuery, state: FSMContext):
    catalog_id = int(cb.data.split("_")[2])
    await state.update_data(catalog_id=catalog_id)
    await state.set_state(ServiceForm.price)
    await cb.message.edit_text("\u0422\u0435\u043f\u0435\u0440\u044c \u0443\u043a\u0430\u0436\u0438\u0442\u0435 \u0432\u0430\u0448\u0443 \u0446\u0435\u043d\u0443 \u0434\u043b\u044f \u044d\u0442\u043e\u0439 \u0443\u0441\u043b\u0443\u0433\u0438. \u0422\u043e\u043b\u044c\u043a\u043e \u0446\u0438\u0444\u0440\u044b:")
    await cb.answer()


@dp.message(ServiceForm.price)
async def process_service_price(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430. \u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0446\u0435\u043d\u0443 \u0442\u043e\u043b\u044c\u043a\u043e \u0446\u0438\u0444\u0440\u0430\u043c\u0438.")
        return
    await state.update_data(price=int(message.text))
    await state.set_state(ServiceForm.duration)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="30 \u043c\u0438\u043d\u0443\u0442", callback_data="dur_30"), InlineKeyboardButton(text="45 \u043c\u0438\u043d\u0443\u0442", callback_data="dur_45")],
        [InlineKeyboardButton(text="60 \u043c\u0438\u043d\u0443\u0442", callback_data="dur_60"), InlineKeyboardButton(text="90 \u043c\u0438\u043d\u0443\u0442", callback_data="dur_90")],
    ])
    await message.answer("\u0426\u0435\u043d\u0430 \u043f\u0440\u0438\u043d\u044f\u0442\u0430. \u0422\u0435\u043f\u0435\u0440\u044c \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c \u0443\u0441\u043b\u0443\u0433\u0438:", reply_markup=kb)


@dp.callback_query(ServiceForm.duration, F.data.startswith("dur_"))
async def process_service_duration_choice(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    duration = int(cb.data.split("_")[1])
    data = await state.get_data()
    async with db.async_session() as session:
        catalog_service = await session.get(db.CatalogService, data["catalog_id"])
        new_service = db.Service(catalog_service_id=data["catalog_id"], price=data["price"], duration_min=duration, stylist_id=stylist.id)
        session.add(new_service)
        await session.commit()
    await cb.message.delete()
    keyboard = await get_main_keyboard(cb.from_user.id)
    await cb.message.answer(f"Новая услуга '{catalog_service.name}' успешно добавлена.", reply_markup=keyboard)
    await state.clear()
    await cb.answer()

@dp.message(F.text == "📊 Моя статистика")
async def show_stats_menu(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    async with db.async_session() as session:
        fav_count = await session.scalar(select(func.count(db.Favorite.id)).where(db.Favorite.stylist_id == stylist.id))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u0417\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f", callback_data="stats_today")],
        [InlineKeyboardButton(text="\u0417\u0430 \u0432\u0447\u0435\u0440\u0430", callback_data="stats_yesterday")],
        [InlineKeyboardButton(text="\u0417\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 7 \u0434\u043d\u0435\u0439", callback_data="stats_7_days")],
    ])
    await message.answer(
        f"<b>\u0412\u0430\u0441 \u0434\u043e\u0431\u0430\u0432\u0438\u043b\u0438 \u0432 \u0438\u0437\u0431\u0440\u0430\u043d\u043d\u043e\u0435 {fav_count} \u0440\u0430\u0437(\u0430).</b>\n\n\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u0435\u0440\u0438\u043e\u0434 \u0434\u043b\u044f \u043e\u0442\u0447\u0451\u0442\u0430:",
        reply_markup=kb,
        parse_mode="HTML",
    )

@dp.callback_query(F.data.startswith("stats_"))
async def get_statistics(cb: CallbackQuery):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        return

    period = cb.data.split("_")[1]
    today = timeutils.today()
    if period == "today":
        start_date = today
        end_date = today + timedelta(days=1)
        period_text = "\u0441\u0435\u0433\u043e\u0434\u043d\u044f"
    elif period == "yesterday":
        start_date = today - timedelta(days=1)
        end_date = today
        period_text = "\u0432\u0447\u0435\u0440\u0430"
    elif period == "7":
        start_date = today - timedelta(days=7)
        end_date = today + timedelta(days=1)
        period_text = "\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 7 \u0434\u043d\u0435\u0439"
    else:
        await cb.answer("\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u044b\u0439 \u043f\u0435\u0440\u0438\u043e\u0434.")
        return

    # start_date/end_date заданы в днях, а запросы сравнивают моменты времени.
    period_start, period_end = timeutils.range_bounds(start_date, end_date - timedelta(days=1))

    async with db.async_session() as session:
        pending_count = await session.scalar(
            select(func.count(db.Booking.id)).where(
                db.Booking.stylist_id == stylist.id,
                db.Booking.status == BOOKING_PENDING,
                db.Booking.starts_at >= period_start,
                db.Booking.starts_at < period_end,
            )
        ) or 0
        approved_count = await session.scalar(
            select(func.count(db.Booking.id)).where(
                db.Booking.stylist_id == stylist.id,
                db.Booking.status == BOOKING_APPROVED,
                db.Booking.starts_at >= period_start,
                db.Booking.starts_at < period_end,
            )
        ) or 0
        completed_count = await session.scalar(
            select(func.count(db.Booking.id)).where(
                db.Booking.stylist_id == stylist.id,
                db.Booking.status == BOOKING_COMPLETED,
                db.Booking.starts_at >= period_start,
                db.Booking.starts_at < period_end,
            )
        ) or 0
        revenue = await session.scalar(
            select(func.coalesce(func.sum(db.Service.price), 0))
            .select_from(db.Booking)
            .join(db.Service, db.Service.id == db.Booking.service_id)
            .where(
                db.Booking.stylist_id == stylist.id,
                db.Booking.status.in_((BOOKING_APPROVED, BOOKING_COMPLETED)),
                db.Booking.starts_at >= period_start,
                db.Booking.starts_at < period_end,
            )
        ) or 0

    total_count = pending_count + approved_count + completed_count
    await cb.message.edit_text(
        f"<b>\u041e\u0442\u0447\u0451\u0442 \u0437\u0430 {period_text}:</b>\n\n"
        f"\u0412\u0441\u0435\u0433\u043e \u0437\u0430\u043f\u0438\u0441\u0435\u0439: {total_count}\n"
        f"\u041d\u043e\u0432\u044b\u0435 \u0437\u0430\u044f\u0432\u043a\u0438: {pending_count}\n"
        f"\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043d\u043d\u044b\u0435: {approved_count}\n"
        f"\u0417\u0430\u0432\u0435\u0440\u0448\u0451\u043d\u043d\u044b\u0435: {completed_count}\n"
        f"\u0414\u043e\u0445\u043e\u0434: {revenue:,.0f} so'm",
        parse_mode="HTML",
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("rate_"))
async def handle_rating(cb: CallbackQuery):
    booking_id, rating = map(int, cb.data.split("_")[1:])
    if not 1 <= rating <= 5:
        await cb.answer("Некорректная оценка.", show_alert=True)
        return

    async with db.async_session() as session:
        # Оценить визит может только клиент этой записи.
        booking = await load_booking_for_client(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        if booking.status != BOOKING_COMPLETED:
            await cb.answer("Оценить можно только завершённый визит.", show_alert=True)
            return
        if booking.rating is not None:
            await cb.message.edit_text("Вы уже оставили оценку.")
            await cb.answer()
            return

        booking.rating = rating
        await session.commit()
        await recalculate_stylist_rating(session, booking.stylist_id)

        await cb.message.edit_text(f"Спасибо за вашу оценку: {rating} ★")

    await cb.answer()


# --- Обработка ошибок и нераспознанных сообщений ---

@dp.errors()
async def handle_unexpected_error(event: ErrorEvent) -> bool:
    """
    Последний рубеж: любое необработанное исключение в хендлере.
    Пользователь не должен оставаться перед «зависшим» экраном без ответа.
    """
    logging.exception(
        "handler.unhandled_error update_id=%s error=%s",
        getattr(event.update, "update_id", None),
        event.exception,
    )

    update = event.update
    try:
        if update.callback_query:
            lang = await get_user_lang(update.callback_query.from_user.id)
            await update.callback_query.answer(
                {
                    "ru": "Что-то пошло не так. Мы уже разбираемся, попробуйте через минуту.",
                    "uz": "Nimadir xato ketdi. Biz tekshiryapmiz, bir daqiqadan so'ng urinib ko'ring.",
                }[lang],
                show_alert=True,
            )
        elif update.message:
            lang = await get_user_lang(update.message.from_user.id)
            await update.message.answer(
                {
                    "ru": "Что-то пошло не так. Мы уже разбираемся, попробуйте через минуту.",
                    "uz": "Nimadir xato ketdi. Biz tekshiryapmiz, bir daqiqadan so'ng urinib ko'ring.",
                }[lang],
                reply_markup=await get_main_keyboard(update.message.from_user.id),
            )
    except Exception as e:
        logging.warning("handler.error_reply_failed error=%s", e)

    return True


@dp.message()
async def fallback_message(message: Message, state: FSMContext):
    """
    Всё, что не подошло ни одному хендлеру выше. Без этого бот молчит
    в ответ на произвольный текст, и пользователь не понимает, что делать.
    """
    if await state.get_state() is not None:
        # Мы внутри сценария — подсказываем, что ожидается, и не сбрасываем состояние.
        lang = await get_user_lang(message.from_user.id)
        await message.answer(
            {
                "ru": "Не понял ответ. Воспользуйтесь кнопками выше или отправьте /start, чтобы начать заново.",
                "uz": "Javobni tushunmadim. Yuqoridagi tugmalardan foydalaning yoki qaytadan boshlash uchun /start yuboring.",
            }[lang]
        )
        return

    lang = await get_user_lang(message.from_user.id)
    await message.answer(
        {
            "ru": "Я понимаю только кнопки меню. Выберите действие ниже.",
            "uz": "Men faqat menyu tugmalarini tushunaman. Quyidan amalni tanlang.",
        }[lang],
        reply_markup=await get_main_keyboard(message.from_user.id),
    )


# --- start ---
async def main():
    await db.run_migrations()

    scheduler_tasks = AsyncIOScheduler(timezone="Asia/Tashkent")
    scheduler_tasks.add_job(scheduler.check_reminders, 'cron', hour='*', minute=0, args=(bot,))
    scheduler_tasks.add_job(scheduler.check_follow_ups, 'cron', hour=10, minute=0, args=(bot,))
    scheduler_tasks.add_job(scheduler.check_subscription_expiry, 'cron', hour=10, minute=5, args=(bot,))
    scheduler_tasks.start()
    print("\u041f\u043b\u0430\u043d\u0438\u0440\u043e\u0432\u0449\u0438\u043a \u0437\u0430\u043f\u0443\u0449\u0435\u043d.")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    if sys.platform == 'win32':
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
