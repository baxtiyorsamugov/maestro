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
    "reschedule_booking": {
        "ru": "🔄 Перенести",
        "uz": "🔄 Ko'chirish",
    },
    "change_denied_closed": {
        "ru": "Эта запись уже закрыта: переносить или отменять нечего.",
        "uz": "Bu yozuv allaqachon yopilgan: ko'chirish yoki bekor qilish uchun hech narsa yo'q.",
    },
    "change_denied_too_late": {
        "ru": "Менять запись можно не позже чем за {hours} ч. до визита. Позвоните мастеру напрямую.",
        "uz": "Yozuvni tashrifdan kamida {hours} soat oldin o'zgartirish mumkin. Maestroga to'g'ridan-to'g'ri qo'ng'iroq qiling.",
    },
    "reschedule_pick_date": {
        "ru": "Выберите новую дату. Старое время освободится, как только вы подтвердите новое.",
        "uz": "Yangi sanani tanlang. Eski vaqt siz yangisini tasdiqlaganingizdan so'ng bo'shaydi.",
    },
    "reschedule_done": {
        "ru": "Запись перенесена на {slot}.\n\nМастер подтвердит новое время — придёт уведомление.",
        "uz": "Yozuv {slot} ga ko'chirildi.\n\nMaestro yangi vaqtni tasdiqlaydi — xabar keladi.",
    },
    "reschedule_notice_stylist": {
        "ru": "<b>Клиент перенёс запись</b>\n\nКлиент: {client}\nУслуга: {service}\nБыло: {old_slot}\nСтало: {new_slot}",
        "uz": "<b>Mijoz yozuvni ko'chirdi</b>\n\nMijoz: {client}\nXizmat: {service}\nOldin: {old_slot}\nHozir: {new_slot}",
    },
    "btn_approve_booking": {
        "ru": "Подтвердить",
        "uz": "Tasdiqlash",
    },
    "btn_decline_booking": {
        "ru": "Отклонить",
        "uz": "Rad etish",
    },
    "reschedule_service_gone": {
        "ru": "Услуги из этой записи больше нет. Запишитесь заново.",
        "uz": "Bu yozuvdagi xizmat endi mavjud emas. Qaytadan yoziling.",
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
    "profile_card_title": {
        "ru": "<b>Ваша карточка</b>\n\nЕё видит клиент до того, как нажмёт «Записаться».",
        "uz": "<b>Sizning kartangiz</b>\n\nUni mijoz «Yozilish»ni bosishdan oldin ko'radi.",
    },
    "profile_card_about": {
        "ru": "О себе: {about}",
        "uz": "O'zim haqimda: {about}",
    },
    "profile_card_no_about": {
        "ru": "О себе: не заполнено. Пара строк помогает клиенту выбрать — без них карточки мастеров неотличимы.",
        "uz": "O'zim haqimda: to'ldirilmagan. Bir necha satr mijozga tanlashda yordam beradi — ularsiz maestrolar kartalari bir xil.",
    },
    "profile_card_no_photo": {
        "ru": "Фото: нет.",
        "uz": "Foto: yo'q.",
    },
    "profile_card_has_photo": {
        "ru": "Фото: загружено.",
        "uz": "Foto: yuklangan.",
    },
    "kb_edit_about": {
        "ru": "✏️ О себе",
        "uz": "✏️ O'zim haqimda",
    },
    "kb_edit_photo": {
        "ru": "🖼 Фото",
        "uz": "🖼 Foto",
    },
    "kb_clear_photo": {
        "ru": "🚫 Убрать фото",
        "uz": "🚫 Fotoni olib tashlash",
    },
    "kb_clear_about": {
        "ru": "🚫 Очистить",
        "uz": "🚫 Tozalash",
    },
    "profile_ask_about": {
        "ru": "Напишите пару строк о себе — до {limit} символов.\n\nЧто вы делаете лучше всего, сколько лет в профессии, чем отличаетесь. Это увидят клиенты.",
        "uz": "O'zingiz haqingizda bir necha satr yozing — {limit} belgigacha.\n\nNimani eng yaxshi bajarasiz, kasbda necha yil, nimangiz bilan ajralib turasiz. Buni mijozlar ko'radi.",
    },
    "profile_about_saved": {
        "ru": "Описание сохранено.",
        "uz": "Tavsif saqlandi.",
    },
    "profile_about_empty": {
        "ru": "Пустое описание сохранять нечего. Напишите текст или нажмите «Очистить».",
        "uz": "Bo'sh tavsifni saqlab bo'lmaydi. Matn yozing yoki «Tozalash»ni bosing.",
    },
    "profile_about_cleared": {
        "ru": "Описание убрано.",
        "uz": "Tavsif olib tashlandi.",
    },
    "profile_ask_photo": {
        "ru": "Пришлите фото одним сообщением. Лучше своё рабочее, а не логотип — клиенты выбирают человека.",
        "uz": "Bitta xabar bilan foto yuboring. Logotip emas, o'zingizning ish fotongiz yaxshiroq — mijozlar odamni tanlaydi.",
    },
    "profile_photo_saved": {
        "ru": "Фото сохранено.",
        "uz": "Foto saqlandi.",
    },
    "profile_photo_cleared": {
        "ru": "Фото убрано.",
        "uz": "Foto olib tashlandi.",
    },
    "profile_photo_expected": {
        "ru": "Это не фото. Пришлите изображение или вернитесь назад.",
        "uz": "Bu foto emas. Rasm yuboring yoki ortga qayting.",
    },
    "rating_invalid": {
        "ru": "Некорректная оценка.",
        "uz": "Noto'g'ri baho.",
    },
    "rating_already_left": {
        "ru": "Вы уже оставили оценку.",
        "uz": "Siz allaqachon baho qo'ygansiz.",
    },
    "rating_thanks": {
        "ru": "Спасибо за оценку: {stars}\n\nРасскажете, как всё прошло? Несколько слов помогут тем, кто выбирает мастера впервые.",
        "uz": "Baho uchun rahmat: {stars}\n\nQanday o'tganini aytib berasizmi? Bir necha so'z maestroni birinchi marta tanlayotganlarga yordam beradi.",
    },
    "rating_thanks_short": {
        "ru": "Спасибо за оценку: {stars}",
        "uz": "Baho uchun rahmat: {stars}",
    },
    "kb_write_review": {
        "ru": "✍️ Написать отзыв",
        "uz": "✍️ Sharh yozish",
    },
    "kb_skip_review": {
        "ru": "Пропустить",
        "uz": "O'tkazib yuborish",
    },
    "review_prompt": {
        "ru": "Напишите отзыв одним сообщением — до {limit} символов.\n\nЕго увидят другие клиенты рядом с вашей оценкой.",
        "uz": "Sharhni bitta xabar bilan yozing — {limit} belgigacha.\n\nUni boshqa mijozlar bahoingiz yonida ko'radi.",
    },
    "review_saved": {
        "ru": "Отзыв сохранён. Спасибо — он поможет другим выбрать мастера.",
        "uz": "Sharh saqlandi. Rahmat — u boshqalarga maestro tanlashda yordam beradi.",
    },
    "review_empty": {
        "ru": "Пустой отзыв сохранять нечего. Напишите пару слов или нажмите «Пропустить».",
        "uz": "Bo'sh sharhni saqlab bo'lmaydi. Bir necha so'z yozing yoki «O'tkazib yuborish»ni bosing.",
    },
    "review_skipped": {
        "ru": "Хорошо, обойдёмся оценкой.",
        "uz": "Yaxshi, baho bilan cheklanamiz.",
    },
    "review_denied_not_completed": {
        "ru": "Отзыв можно оставить только о завершённом визите.",
        "uz": "Sharhni faqat yakunlangan tashrif haqida qoldirish mumkin.",
    },
    "review_denied_no_rating": {
        "ru": "Сначала поставьте оценку.",
        "uz": "Avval baho qo'ying.",
    },
    "review_denied_already_left": {
        "ru": "Вы уже оставили отзыв об этом визите.",
        "uz": "Siz bu tashrif haqida sharh qoldirgansiz.",
    },
    "kb_stylist_reviews": {
        "ru": "💬 Отзывы ({count})",
        "uz": "💬 Sharhlar ({count})",
    },
    "reviews_title": {
        "ru": "<b>Отзывы: {name}</b>",
        "uz": "<b>Sharhlar: {name}</b>",
    },
    "reviews_empty": {
        "ru": "Об этом мастере пока никто не написал. Будете первым?",
        "uz": "Bu maestro haqida hozircha hech kim yozmagan. Birinchi bo'lasizmi?",
    },
    "reviews_more": {
        "ru": "И ещё {count}. Показаны последние {shown}.",
        "uz": "Yana {count} ta. Oxirgi {shown} tasi ko'rsatilgan.",
    },
    "reviews_anonymous": {
        "ru": "Клиент",
        "uz": "Mijoz",
    },
    "offline_badge": {
        "ru": "🚶 Офлайн-запись",
        "uz": "🚶 Oflayn yozuv",
    },
    "offline_guest_unnamed": {
        "ru": "Без имени",
        "uz": "Ismsiz",
    },
    "kb_offline_new": {
        "ru": "➕ Записать клиента",
        "uz": "➕ Mijozni yozish",
    },
    "offline_pick_service": {
        "ru": "<b>Запись офлайн-клиента</b>\n\nЭто время перестанет предлагаться другим.\n\nВыберите услугу:",
        "uz": "<b>Oflayn mijozni yozish</b>\n\nBu vaqt boshqalarga taklif qilinmaydi.\n\nXizmatni tanlang:",
    },
    "offline_no_services": {
        "ru": "Сначала добавьте хотя бы одну услугу — из неё берётся длительность записи.",
        "uz": "Avval kamida bitta xizmat qo'shing — yozuv davomiyligi undan olinadi.",
    },
    "offline_pick_date": {
        "ru": "Выберите дату. Активны только дни, где есть свободное время.",
        "uz": "Sanani tanlang. Faqat bo'sh vaqti bor kunlar faol.",
    },
    "offline_no_free_dates": {
        "ru": "Свободного времени под эту услугу нет. Проверьте расписание и перерывы.",
        "uz": "Bu xizmat uchun bo'sh vaqt yo'q. Jadval va tanaffuslarni tekshiring.",
    },
    "offline_pick_time": {
        "ru": "{date}: выберите время.",
        "uz": "{date}: vaqtni tanlang.",
    },
    "offline_no_free_slots": {
        "ru": "На этот день свободного времени не осталось.",
        "uz": "Bu kunda bo'sh vaqt qolmadi.",
    },
    "offline_ask_name": {
        "ru": "{slot}\n\nКак зовут клиента? Имя видите только вы — оно нужно, чтобы не перепутать записи.\n\nМожно пропустить.",
        "uz": "{slot}\n\nMijozning ismi nima? Ismni faqat siz ko'rasiz — yozuvlarni adashtirmaslik uchun kerak.\n\nO'tkazib yuborish mumkin.",
    },
    "kb_offline_skip_name": {
        "ru": "Пропустить",
        "uz": "O'tkazib yuborish",
    },
    "offline_saved": {
        "ru": "Готово: {slot} — {name}.\n\nЭто время больше не предлагается клиентам.",
        "uz": "Tayyor: {slot} — {name}.\n\nBu vaqt endi mijozlarga taklif qilinmaydi.",
    },
    "offline_slot_taken": {
        "ru": "Это время только что заняли. Выберите другое.",
        "uz": "Bu vaqtni hozirgina band qilishdi. Boshqasini tanlang.",
    },
    "schedule_break_label": {
        "ru": "обед {start}-{end}",
        "uz": "tushlik {start}-{end}",
    },
    "kb_breaks": {
        "ru": "☕ Перерывы",
        "uz": "☕ Tanaffuslar",
    },
    "kb_buffer": {
        "ru": "⏱ Буфер между записями: {value}",
        "uz": "⏱ Yozuvlar orasidagi tanaffus: {value}",
    },
    "buffer_off": {
        "ru": "нет",
        "uz": "yo'q",
    },
    "buffer_minutes": {
        "ru": "{minutes} мин",
        "uz": "{minutes} daq",
    },
    "buffer_title": {
        "ru": "<b>Буфер между записями</b>\n\nСколько минут оставить себе между клиентами: убрать рабочее место, продезинфицировать инструмент, выдохнуть.\n\nЭто время клиент не увидит в календаре — слоты сдвинутся сами.",
        "uz": "<b>Yozuvlar orasidagi tanaffus</b>\n\nMijozlar orasida o'zingizga necha daqiqa qoldirish kerak: ish joyini yig'ish, asbobni dezinfeksiya qilish, nafas rostlash.\n\nMijoz bu vaqtni kalendarda ko'rmaydi — bo'sh vaqtlar o'zi suriladi.",
    },
    "buffer_saved": {
        "ru": "Буфер: {value}",
        "uz": "Tanaffus: {value}",
    },
    "break_title": {
        "ru": "<b>Перерывы по дням недели</b>\n\nОбед или любой другой постоянный перерыв. В это время клиент не сможет записаться.\n\nВыберите день:",
        "uz": "<b>Hafta kunlari bo'yicha tanaffuslar</b>\n\nTushlik yoki boshqa doimiy tanaffus. Bu vaqtda mijoz yozila olmaydi.\n\nKunni tanlang:",
    },
    "break_none": {
        "ru": "без перерыва",
        "uz": "tanaffussiz",
    },
    "break_day_off_hint": {
        "ru": "{day} — выходной. Сначала задайте рабочие часы этого дня.",
        "uz": "{day} — dam olish kuni. Avval shu kunning ish vaqtini belgilang.",
    },
    "break_pick_start": {
        "ru": "{day}: начало перерыва.\nРабочий день: {start}-{end}",
        "uz": "{day}: tanaffus boshlanishi.\nIsh kuni: {start}-{end}",
    },
    "break_pick_end": {
        "ru": "{day}: конец перерыва. Начало — {start}.",
        "uz": "{day}: tanaffus tugashi. Boshlanishi — {start}.",
    },
    "break_saved": {
        "ru": "{day}: перерыв {start}-{end}",
        "uz": "{day}: tanaffus {start}-{end}",
    },
    "break_cleared": {
        "ru": "{day}: перерыв убран",
        "uz": "{day}: tanaffus olib tashlandi",
    },
    "kb_break_clear": {
        "ru": "🚫 Убрать перерыв",
        "uz": "🚫 Tanaffusni olib tashlash",
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
    "kb_back": {
        "ru": "⬅️ Назад",
        "uz": "⬅️ Ortga",
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
    "stats_favorites_count": {
        "ru": "Вас добавили в избранное {count} раз(а).",
        "uz": "Sizni {count} marta sevimlilarga qo'shishdi.",
    },
    "stats_choose_period": {
        "ru": "Выберите период для отчёта:",
        "uz": "Hisobot uchun davrni tanlang:",
    },
    "stats_period_today": {
        "ru": "За сегодня",
        "uz": "Bugun uchun",
    },
    "stats_period_yesterday": {
        "ru": "За вчера",
        "uz": "Kecha uchun",
    },
    "stats_period_week": {
        "ru": "За последние 7 дней",
        "uz": "Oxirgi 7 kun uchun",
    },
    "stats_label_today": {
        "ru": "сегодня",
        "uz": "bugun",
    },
    "stats_label_yesterday": {
        "ru": "вчера",
        "uz": "kecha",
    },
    "stats_label_week": {
        "ru": "последние 7 дней",
        "uz": "oxirgi 7 kun",
    },
    "stats_unknown_period": {
        "ru": "Неизвестный период.",
        "uz": "Noma'lum davr.",
    },
    "stats_report_title": {
        "ru": "Отчёт за {period}:",
        "uz": "{period} uchun hisobot:",
    },
    "stats_total": {
        "ru": "Всего записей",
        "uz": "Jami yozuvlar",
    },
    "stats_pending": {
        "ru": "Новые заявки",
        "uz": "Yangi so'rovlar",
    },
    "stats_approved": {
        "ru": "Подтверждённые",
        "uz": "Tasdiqlangan",
    },
    "stats_completed": {
        "ru": "Завершённые",
        "uz": "Yakunlangan",
    },
    "stats_revenue": {
        "ru": "Доход",
        "uz": "Daromad",
    },
    "services_title": {
        "ru": "Ваши услуги:",
        "uz": "Sizning xizmatlaringiz:",
    },
    "services_subtitle": {
        "ru": "Клиенты видят цену и длительность.",
        "uz": "Mijozlar narx va davomiylikni ko'radi.",
    },
    "services_empty": {
        "ru": "У вас пока нет добавленных услуг. Давайте создадим первую.",
        "uz": "Sizda hozircha xizmatlar yo'q. Keling, birinchisini qo'shamiz.",
    },
    "services_minutes_short": {
        "ru": "мин",
        "uz": "daq",
    },
    "services_delete": {
        "ru": "Удалить: {name}",
        "uz": "O'chirish: {name}",
    },
    "services_add_new": {
        "ru": "Добавить новую услугу",
        "uz": "Yangi xizmat qo'shish",
    },
    "services_deleted": {
        "ru": "✅ Услуга удалена",
        "uz": "✅ Xizmat o'chirildi",
    },
    "services_not_found": {
        "ru": "❌ Ошибка: услуга не найдена",
        "uz": "❌ Xatolik: xizmat topilmadi",
    },
    "services_delete_blocked": {
        "ru": "⚠️ Нельзя удалить услугу, на которую уже есть записи. Сначала отмените эти записи.",
        "uz": "⚠️ Yozuvlari bor xizmatni o'chirib bo'lmaydi. Avval o'sha yozuvlarni bekor qiling.",
    },
    "services_choose_catalog": {
        "ru": "Выберите тип услуги из каталога:",
        "uz": "Katalogdan xizmat turini tanlang:",
    },
    "services_ask_price": {
        "ru": "Теперь укажите вашу цену для этой услуги. Только цифры:",
        "uz": "Endi ushbu xizmat uchun narxingizni kiriting. Faqat raqamlar:",
    },
    "services_price_invalid": {
        "ru": "Ошибка. Введите цену только цифрами.",
        "uz": "Xatolik. Narxni faqat raqamlar bilan kiriting.",
    },
    "services_ask_duration": {
        "ru": "Цена принята. Теперь выберите длительность услуги:",
        "uz": "Narx qabul qilindi. Endi xizmat davomiyligini tanlang:",
    },
    "services_duration_option": {
        "ru": "{minutes} минут",
        "uz": "{minutes} daqiqa",
    },
    "services_added": {
        "ru": "Новая услуга «{name}» добавлена.",
        "uz": "«{name}» yangi xizmati qo'shildi.",
    },
    "bookings_period_today": {
        "ru": "☀️ На сегодня",
        "uz": "☀️ Bugunga",
    },
    "bookings_period_week": {
        "ru": "📅 На неделю",
        "uz": "📅 Haftaga",
    },
    "bookings_period_all": {
        "ru": "📚 Все записи",
        "uz": "📚 Barcha yozuvlar",
    },
    "bookings_choose_period": {
        "ru": "Выберите период для просмотра записей:",
        "uz": "Yozuvlarni ko'rish uchun davrni tanlang:",
    },
    "bookings_title_today": {
        "ru": "☀️ Записи на сегодня ({date})",
        "uz": "☀️ Bugungi yozuvlar ({date})",
    },
    "bookings_title_week": {
        "ru": "📅 Записи на неделю (до {date})",
        "uz": "📅 Haftalik yozuvlar ({date} gacha)",
    },
    "bookings_title_all": {
        "ru": "📚 Все предстоящие записи",
        "uz": "📚 Barcha kelgusi yozuvlar",
    },
    "bookings_empty": {
        "ru": "📭 Актуальных записей нет.",
        "uz": "📭 Dolzarb yozuvlar yo'q.",
    },
    "bookings_found": {
        "ru": "Найдено: {count}",
        "uz": "Topildi: {count}",
    },
    "bookings_complete_visit": {
        "ru": "🏁 Завершить визит",
        "uz": "🏁 Tashrifni yakunlash",
    },
    "booking_approved_client": {
        "ru": "✨ <b>Прекрасный выбор!</b>\n\nВаша запись подтверждена. Мастер уже готовится к вашему визиту.\n\n📅 Ждём вас: <b>{when}</b>\n\nДо встречи в Maestro! ✂️",
        "uz": "✨ <b>Ajoyib tanlov!</b>\n\nYozuvingiz tasdiqlandi. Maestro tashrifingizga tayyorgarlik ko'rmoqda.\n\n📅 Sizni kutamiz: <b>{when}</b>\n\nMaestro'da ko'rishguncha! ✂️",
    },
    "booking_declined_client": {
        "ru": "<b>Запись отклонена.</b>\n\nВремя {when} уже недоступно. Пожалуйста, выберите другое.",
        "uz": "<b>Yozuv rad etildi.</b>\n\n{when} vaqti endi mavjud emas. Iltimos, boshqa vaqtni tanlang.",
    },
    "booking_rate_request": {
        "ru": "Как вам сервис? Пожалуйста, оцените визит.",
        "uz": "Xizmat sizga yoqdimi? Iltimos, baho bering.",
    },
    "toast_done": {
        "ru": "Готово",
        "uz": "Tayyor",
    },
    "fallback_in_scenario": {
        "ru": "Не понял ответ. Воспользуйтесь кнопками выше или отправьте /start, чтобы начать заново.",
        "uz": "Javobni tushunmadim. Yuqoridagi tugmalardan foydalaning yoki qaytadan boshlash uchun /start yuboring.",
    },
    "fallback_use_menu": {
        "ru": "Я понимаю только кнопки меню. Выберите действие ниже.",
        "uz": "Men faqat menyu tugmalarini tushunaman. Quyidan amalni tanlang.",
    },
    "fallback_button_outdated": {
        "ru": "Эта кнопка устарела. Откройте меню заново.",
        "uz": "Bu tugma eskirgan. Menyuni qaytadan oching.",
    },
    "repeat_button": {
        "ru": "🔁 Повторить: {service} у {stylist}",
        "uz": "🔁 Takrorlash: {stylist}da {service}",
    },
    "repeat_hint": {
        "ru": "Или повторите прошлую запись одним нажатием:",
        "uz": "Yoki oldingi yozuvni bir bosishda takrorlang:",
    },
    "repeat_service_gone": {
        "ru": "Эту услугу мастер больше не оказывает. Откройте его карточку и выберите другую.",
        "uz": "Maestro bu xizmatni endi ko'rsatmaydi. Uning kartasini ochib, boshqasini tanlang.",
    },
    "booking_stylist_closed": {
        "ru": "Запись к этому мастеру временно закрыта.",
        "uz": "Bu maestroga yozilish vaqtincha yopiq.",
    },
    "booking_no_free_dates": {
        "ru": "Для этой услуги пока нет свободных дат.",
        "uz": "Bu xizmat uchun hozircha bo'sh sanalar yo'q.",
    },
    "booking_pick_date": {
        "ru": "Выберите дату. Активны только дни со свободным временем.",
        "uz": "Sanani tanlang. Faqat bo'sh vaqti bor kunlar faol.",
    },
    "booking_session_expired": {
        "ru": "Время выбора истекло. Начните запись заново.",
        "uz": "Tanlov sessiyasi tugadi. Qaytadan boshlang.",
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
    "my_profile_card": {
        "ru": "👤 Моя карточка",
        "uz": "👤 Mening kartam",
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
