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
    "schedule_closed": {
        "ru": "Управление расписанием закрыто.",
        "uz": "Jadvalni boshqarish yopildi.",
    },
    "action_cancelled": {
        "ru": "Действие отменено.",
        "uz": "Amal bekor qilindi.",
    },
    "schedule_day_off_set": {
        "ru": "{day} теперь выходной",
        "uz": "{day} endi dam olish kuni",
    },
    "schedule_pick_start": {
        "ru": "{day}: выберите время начала работы.",
        "uz": "{day}: ish boshlanish vaqtini tanlang.",
    },
    "schedule_pick_end": {
        "ru": "{day}: выберите время окончания работы.",
        "uz": "{day}: ish tugash vaqtini tanlang.",
    },
    "schedule_pick_start_buttons": {
        "ru": "{day}: выберите время начала работы кнопками ниже.",
        "uz": "{day}: ish boshlanish vaqtini quyidagi tugmalar bilan tanlang.",
    },
    "schedule_pick_end_buttons": {
        "ru": "{day}: выберите время окончания работы кнопками ниже.",
        "uz": "{day}: ish tugash vaqtini quyidagi tugmalar bilan tanlang.",
    },
    "schedule_saved": {
        "ru": "График на {day} сохранён: {start}-{end}",
        "uz": "{day} uchun jadval saqlandi: {start}-{end}",
    },
    "schedule_session_expired": {
        "ru": "Сессия выбора времени истекла. Начните заново.",
        "uz": "Vaqt tanlash sessiyasi tugadi. Qaytadan boshlang.",
    },
    "special_day_off_set": {
        "ru": "День отмечен как выходной.",
        "uz": "Kun dam olish kuni sifatida belgilandi.",
    },
    "special_removed": {
        "ru": "Исключение удалено. Для этой даты снова работает недельный шаблон.",
        "uz": "Istisno o'chirildi. Bu sanaga yana haftalik jadval amal qiladi.",
    },
    "special_hours_saved": {
        "ru": "На {date} сохранены часы: {start}-{end}",
        "uz": "{date} uchun ish vaqti saqlandi: {start}-{end}",
    },
    "back_to_calendar": {
        "ru": "⬅️ К календарю",
        "uz": "⬅️ Kalendarga",
    },
    "schedule_day_off_short": {
        "ru": "Выходной",
        "uz": "Dam olish",
    },
    "schedule_no_exception": {
        "ru": "Нет исключения",
        "uz": "Istisno yo'q",
    },
    "schedule_title": {
        "ru": "График мастера {name}",
        "uz": "{name} maestroning jadvali",
    },
    "schedule_subtitle": {
        "ru": "Базовый шаблон по дням недели. Ниже можно изменить часы или отметить выходной.",
        "uz": "Hafta kunlari bo'yicha asosiy jadval. Quyida vaqtni o'zgartirish yoki dam olish kunini belgilash mumkin.",
    },
    "schedule_upcoming_special": {
        "ru": "Ближайшие особые даты:",
        "uz": "Yaqin maxsus sanalar:",
    },
    "schedule_hint": {
        "ru": "Клиент увидит в календаре только реально доступные слоты. Для разовых изменений используйте кнопку «Особые даты».",
        "uz": "Mijoz kalendarda faqat haqiqatda bo'sh vaqtlarni ko'radi. Bir martalik o'zgarishlar uchun «Maxsus sanalar» tugmasidan foydalaning.",
    },
    "special_title": {
        "ru": "Особые даты {name}",
        "uz": "{name} maxsus sanalari",
    },
    "special_month": {
        "ru": "Месяц: <b>{month}</b>",
        "uz": "Oy: <b>{month}</b>",
    },
    "special_subtitle": {
        "ru": "Выберите конкретную дату, чтобы сделать её выходным или задать отдельные часы.",
        "uz": "Dam olish kuni qilish yoki alohida vaqt belgilash uchun aniq sanani tanlang.",
    },
    "special_fallback_hint": {
        "ru": "Если для даты нет исключения, будет работать обычный недельный график.",
        "uz": "Agar sanaga istisno bo'lmasa, odatdagi haftalik jadval amal qiladi.",
    },
    "special_upcoming": {
        "ru": "Ближайшие исключения:",
        "uz": "Yaqin istisnolar:",
    },
    "special_empty": {
        "ru": "Пока нет особых дат. Ниже можно добавить первое исключение.",
        "uz": "Hozircha maxsus sanalar yo'q. Quyida birinchi istisnoni qo'shishingiz mumkin.",
    },
    "special_by_weekly": {
        "ru": "По шаблону недели",
        "uz": "Haftalik jadval bo'yicha",
    },
    "special_exception_for_date": {
        "ru": "Исключение на эту дату",
        "uz": "Ushbu sanaga istisno",
    },
    "special_choose_action": {
        "ru": "Выберите, что сделать с этой датой.",
        "uz": "Ushbu sana bilan nima qilishni tanlang.",
    },
    "booking_card_title": {
        "ru": "Новая заявка",
        "uz": "Yangi so'rov",
    },
    "booking_client": {
        "ru": "Клиент",
        "uz": "Mijoz",
    },
    "booking_contact": {
        "ru": "Контакт",
        "uz": "Aloqa",
    },
    "booking_write_telegram": {
        "ru": "Написать в Telegram",
        "uz": "Telegramda yozish",
    },
    "booking_service": {
        "ru": "Услуга",
        "uz": "Xizmat",
    },
    "booking_datetime": {
        "ru": "Дата и время",
        "uz": "Sana va vaqt",
    },
    "booking_service_unknown": {
        "ru": "Услуга не указана",
        "uz": "Xizmat ko'rsatilmagan",
    },
    "booking_phone_unknown": {
        "ru": "не указан",
        "uz": "ko'rsatilmagan",
    },
    "day_plural_one": {
        "ru": "день",
        "uz": "kun",
    },
    "day_plural_few": {
        "ru": "дня",
        "uz": "kun",
    },
    "day_plural_many": {
        "ru": "дней",
        "uz": "kun",
    },
    "tariff_title": {
        "ru": "Тариф мастера",
        "uz": "Maestro tarifi",
    },
    "tariff_stylists_only": {
        "ru": "Этот раздел доступен только мастерам.",
        "uz": "Bu bo'lim faqat maestrolar uchun.",
    },
    "tariff_unlimited": {
        "ru": "Без ограничения",
        "uz": "Cheklovsiz",
    },
    "tariff_period_title": {
        "ru": "Срок действия тарифа",
        "uz": "Tarif amal qilish muddati",
    },
    "tariff_expires_on": {
        "ru": "Дата окончания",
        "uz": "Tugash sanasi",
    },
    "tariff_status_active": {
        "ru": "Статус: ✅ Активен",
        "uz": "Holat: ✅ Faol",
    },
    "tariff_status_expired": {
        "ru": "Статус: ⛔ Тариф истёк",
        "uz": "Holat: ⛔ Tarif tugagan",
    },
    "tariff_status_today": {
        "ru": "Статус: ⚠️ Истекает сегодня",
        "uz": "Holat: ⚠️ Bugun tugaydi",
    },
    "tariff_detail_unlimited": {
        "ru": "Срок действия не ограничен.",
        "uz": "Amal qilish muddati cheklanmagan.",
    },
    "tariff_detail_expired": {
        "ru": "Управление панелью и новые записи временно недоступны.",
        "uz": "Panelni boshqarish va yangi yozuvlar vaqtincha mavjud emas.",
    },
    "tariff_detail_today": {
        "ru": "Продлите тариф сегодня, чтобы не потерять доступ к панели и новым записям.",
        "uz": "Panel va yangi yozuvlarga kirishni yo'qotmaslik uchun tarifni bugun uzaytiring.",
    },
    "tariff_detail_days_left": {
        "ru": "До окончания осталось: <b>{days} {word}</b>.",
        "uz": "Tugashiga qoldi: <b>{days} {word}</b>.",
    },
    "tariff_contact_admin": {
        "ru": "Если нужно продление, свяжитесь с администраторами сервиса.",
        "uz": "Uzaytirish kerak bo'lsa, xizmat administratorlari bilan bog'laning.",
    },
    "choose_language": {
        "ru": "Добро пожаловать в Maestro. Для начала выберите язык.",
        "uz": "Maestro'ga xush kelibsiz. Davom etish uchun tilni tanlang.",
    },
    "ask_name": {
        "ru": "Как вас зовут?\nОтправьте имя и фамилию одним сообщением.",
        "uz": "Ismingiz nima?\nIsm va familiyangizni bitta xabarda yuboring.",
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
        "uz": "Ro'yxatdan o'tish tugadi. Endi yozilish, sevimli maestrolar va profil ochiq.",
    },
    "registration_required": {
        "ru": "Сначала завершите регистрацию через /start, чтобы записываться и пользоваться меню.",
        "uz": "Avval /start orqali ro'yxatdan o'tishni yakunlang, shundan keyin yozilish va menyu ochiladi.",
    },
    "kb_cancel": {
        "ru": "✖ Отмена",
        "uz": "✖ Bekor qilish",
    },
    "kb_close": {
        "ru": "✖ Закрыть",
        "uz": "✖ Yopish",
    },
    "kb_back_to_start_time": {
        "ru": "← Назад ко времени начала",
        "uz": "← Boshlanish vaqtiga qaytish",
    },
    "kb_special_dates": {
        "ru": "📅 Особые даты",
        "uz": "📅 Maxsus sanalar",
    },
    "kb_back_to_weekly": {
        "ru": "⬅️ К недельному графику",
        "uz": "⬅️ Haftalik jadvalga",
    },
    "kb_set_hours": {
        "ru": "🕒 Задать часы",
        "uz": "🕒 Vaqtni belgilash",
    },
    "kb_make_day_off": {
        "ru": "🌴 Сделать выходным",
        "uz": "🌴 Dam olish kuni qilish",
    },
    "kb_remove_exception": {
        "ru": "♻️ Убрать исключение",
        "uz": "♻️ Istisnoni olib tashlash",
    },
    "booking_approved": {
        "ru": "Запись подтверждена",
        "uz": "Yozuv tasdiqlandi",
    },
    "booking_declined": {
        "ru": "Запись отклонена",
        "uz": "Yozuv rad etildi",
    },
    "booking_completed": {
        "ru": "Визит завершён",
        "uz": "Tashrif yakunlandi",
    },
    "booking_already_handled": {
        "ru": "Эта заявка уже обработана.",
        "uz": "Bu so'rov allaqachon ko'rib chiqilgan.",
    },
    "booking_already_completed": {
        "ru": "Визит уже отмечен как завершённый.",
        "uz": "Tashrif allaqachon yakunlangan deb belgilangan.",
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
