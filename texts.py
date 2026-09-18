"""
Локализация интерфейса.

Словари объявлены на уровне модуля: раньше они пересоздавались на каждый вызов
get_text, а он вызывается десятки раз на одно сообщение.

Новый текст добавляется сразу на оба языка. Полноту проверяет
scripts/check_locales.py, он же запускается в CI.
"""

LANGUAGES = ("ru", "uz")
DEFAULT_LANGUAGE = "ru"

TEXTS = {
    "welcome_new": {
        "ru": "Здравствуйте! Лучшие Маэстро Ташкента к вашим услугам. Давайте начнем с выбора языка.",
        "uz": "Assalomu alaykum! Toshkentning eng zo'r Maestrolari xizmatingizda. Boshlash uchun tilni tanlang.",
    },
    "welcome_back": {
        "ru": "С возвращением, {}! Рады видеть вас снова.",
        "uz": "Xush kelibsiz, {}! Sizni yana ko'rib turganimizdan xursandmiz.",
    },
    "ask_search_method": {
        "ru": "Как вы хотите найти своего Маэстро?",
        "uz": "Maestroyingizni qanday topishni xohlaysiz?",
    },
    "language_menu_title": {
        "ru": "Выберите язык интерфейса.",
        "uz": "Interfeys tilini tanlang.",
    },
    "language_changed": {
        "ru": "Язык интерфейса обновлен.",
        "uz": "Interfeys tili yangilandi.",
    },
    "profile_empty": {
        "ru": "У вас пока нет записей.",
        "uz": "Sizda hozircha yozuvlar yo'q.",
    },
    "profile_bookings_title": {
        "ru": "Ваши записи:",
        "uz": "Sizning yozuvlaringiz:",
    },
    "profile_lang_ru": {
        "ru": "Русский",
        "uz": "Ruscha",
    },
    "profile_lang_uz": {
        "ru": "Узбекский",
        "uz": "O'zbekcha",
    },
    "master_label": {
        "ru": "Мастер",
        "uz": "Maestro",
    },
    "status_label": {
        "ru": "Статус",
        "uz": "Holat",
    },
    "status_pending": {
        "ru": "⏳ Ожидание",
        "uz": "⏳ Kutilmoqda",
    },
    "status_approved": {
        "ru": "✅ Подтверждено",
        "uz": "✅ Tasdiqlangan",
    },
    "status_declined": {
        "ru": "❌ Отклонено",
        "uz": "❌ Bekor qilingan",
    },
    "status_completed": {
        "ru": "🏁 Завершено",
        "uz": "🏁 Yakunlangan",
    },
    "status_cancelled": {
        "ru": "🚫 Отменено клиентом",
        "uz": "🚫 Mijoz bekor qildi",
    },
    "cancel_booking": {
        "ru": "❌ Отменить",
        "uz": "❌ Bekor qilish",
    },
    "favorites_empty": {
        "ru": "У вас пока нет избранных мастеров.",
        "uz": "Sizda hozircha sevimli maestrolar yo'q.",
    },
    "favorites_title": {
        "ru": "Ваши избранные мастера:\nНажмите на имя, чтобы открыть карточку мастера.",
        "uz": "Sevimli maestrolaringiz:\nProfilni ochish uchun ism ustiga bosing.",
    },
    "search_by_id": {
        "ru": "🆔 Ввести ID Маэстро",
        "uz": "🆔 Maestro ID sini kiritish",
    },
    "language_name_ru": {
        "ru": "🇷🇺 Русский",
        "uz": "🇷🇺 Ruscha",
    },
    "language_name_uz": {
        "ru": "🇺🇿 Узбекский",
        "uz": "🇺🇿 O'zbekcha",
    },
}

BUTTONS = {
    "search_menu": {
        "ru": "✂️ Записаться / Поиск",
        "uz": "✂️ Yozilish / Izlash",
    },
    "my_masters": {
        "ru": "⭐ Мои мастера",
        "uz": "⭐ Mening maestrolarim",
    },
    "my_profile": {
        "ru": "👤 Мой профиль",
        "uz": "👤 Mening profilim",
    },
    "change_language": {
        "ru": "🌐 Язык",
        "uz": "🌐 Til",
    },
}


def get_text(key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """Строка интерфейса. При отсутствии перевода откатывается на русский."""
    translations = TEXTS.get(key)
    if not translations:
        return "Text not found"
    return translations.get(lang) or translations.get(DEFAULT_LANGUAGE, "Text not found")


def get_buttons(lang: str = DEFAULT_LANGUAGE) -> dict[str, str]:
    """Подписи кнопок главного меню на выбранном языке."""
    return {
        key: translations.get(lang) or translations.get(DEFAULT_LANGUAGE, "")
        for key, translations in BUTTONS.items()
    }
