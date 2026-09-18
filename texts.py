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
    "panel_welcome": {
        "ru": "Добро пожаловать в панель управления! Успехов в работе!",
        "uz": "Boshqaruv paneliga xush kelibsiz! Ishlaringizga rivoj!",
    },
    "panel_exited": {
        "ru": "Вы вернулись в главное меню.",
        "uz": "Siz asosiy menyuga qaytdingiz.",
    },
    "portfolio_prompt": {
        "ru": "Сейчас в вашем портфолио: <b>{count}</b> фото.\nОтправьте новое фото сообщением в чат. Когда закончите, нажмите кнопку ниже.",
        "uz": "Hozir portfoliongizda: <b>{count}</b> ta rasm.\nYangi rasmni xabar sifatida yuboring. Tugatgach, quyidagi tugmani bosing.",
    },
    "portfolio_photo_added": {
        "ru": "Фото добавлено в портфолио.",
        "uz": "Rasm portfolioga qo'shildi.",
    },
    "portfolio_done": {
        "ru": "Вы вышли из режима добавления фото.",
        "uz": "Rasm qo'shish rejimidan chiqdingiz.",
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


# Кнопки панели мастера. Выделены отдельно от BUTTONS: у клиента и у мастера
# разные меню, и смешивать их в одном словаре — значит однажды показать
# клиенту кнопку «Мои услуги».
STYLIST_BUTTONS = {
    "my_bookings": {
        "ru": "📓 Мои записи",
        "uz": "📓 Mening yozuvlarim",
    },
    "my_stats": {
        "ru": "📊 Моя статистика",
        "uz": "📊 Mening statistikam",
    },
    "manage_schedule": {
        "ru": "🕒 Управление расписанием",
        "uz": "🕒 Jadvalni boshqarish",
    },
    "my_services": {
        "ru": "✂️ Мои услуги",
        "uz": "✂️ Mening xizmatlarim",
    },
    "my_portfolio": {
        "ru": "🖼 Мое портфолио",
        "uz": "🖼 Mening portfoliom",
    },
    "subscription": {
        "ru": "💳 Срок тарифа",
        "uz": "💳 Tarif muddati",
    },
    "exit_panel": {
        "ru": "↩️ Выйти из админ-панели",
        "uz": "↩️ Boshqaruv panelidan chiqish",
    },
    "done": {
        "ru": "Готово",
        "uz": "Tayyor",
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


def get_stylist_buttons(lang: str = DEFAULT_LANGUAGE) -> dict[str, str]:
    """Подписи кнопок панели мастера на выбранном языке."""
    return {
        key: translations.get(lang) or translations.get(DEFAULT_LANGUAGE, "")
        for key, translations in STYLIST_BUTTONS.items()
    }


def all_variants(key: str) -> list[str]:
    """
    Подпись кнопки на всех языках.

    Фильтры хендлеров сравнивают текст сообщения с подписью буквально.
    Если фильтр знает только русский вариант, то после переключения языка
    кнопка перестаёт работать — причём молча, без единой ошибки в логах.
    Поэтому фильтр всегда строится через этот хелпер.
    """
    source = STYLIST_BUTTONS.get(key) or BUTTONS.get(key) or {}
    return [value for value in source.values() if value]
