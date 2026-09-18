"""
Тексты сообщений.

Здесь всё, что возвращает строку для пользователя. Клавиатуры — в keyboards.py.

Пользовательские значения обязательно экранируются: имя вида "<b" ломает
отправку сообщения целиком, потому что почти всё отправляется с parse_mode=HTML
(docs/AUDIT.md, B-3).
"""
from html import escape

import database as db
import timeutils
from constants import DAY_LABELS
from services.access import get_subscription_days_left


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

def build_special_dates_text(stylist_name: str, year: int, month: int, special_dates: list[db.SpecialSchedule]) -> str:
    lines = [
        f"<b>Особые даты {stylist_name}</b>",
        f"Месяц: <b>{year}-{month:02d}</b>",
        "Выберите конкретную дату, чтобы сделать её выходным или задать отдельные часы.",
        "Если для даты нет исключения, будет работать обычный недельный график.",
        "",
    ]
    upcoming = [item for item in special_dates if item.work_date >= timeutils.today()]
    if upcoming:
        lines.append("<b>Ближайшие исключения:</b>")
        for item in upcoming[:6]:
            lines.append(f"• {item.work_date.strftime('%Y-%m-%d')}: <b>{format_special_schedule_range(item)}</b>")
    else:
        lines.append("Пока нет особых дат. Ниже можно добавить первое исключение.")
    return "\n".join(lines)

def build_special_date_detail_text(target_date: str, weekly_schedule: db.Schedule | None, special_schedule: db.SpecialSchedule | None) -> str:
    weekly_text = format_schedule_range(weekly_schedule)
    special_text = format_special_schedule_range(special_schedule)
    return (
        f"<b>{target_date}</b>\n"
        f"\u041f\u043e \u0448\u0430\u0431\u043b\u043e\u043d\u0443 \u043d\u0435\u0434\u0435\u043b\u0438: <b>{weekly_text}</b>\n"
        f"\u0418\u0441\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435 \u043d\u0430 \u044d\u0442\u0443 \u0434\u0430\u0442\u0443: <b>{special_text}</b>\n\n"
        "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435, \u0447\u0442\u043e \u0441\u0434\u0435\u043b\u0430\u0442\u044c \u0441 \u044d\u0442\u043e\u0439 \u0434\u0430\u0442\u043e\u0439."
    )

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
