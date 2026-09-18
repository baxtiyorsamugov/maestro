def get_text(key, lang='ru'):
    texts = {
        'welcome_new': {
            'ru': '\u0417\u0434\u0440\u0430\u0432\u0441\u0442\u0432\u0443\u0439\u0442\u0435! \u041b\u0443\u0447\u0448\u0438\u0435 \u041c\u0430\u044d\u0441\u0442\u0440\u043e \u0422\u0430\u0448\u043a\u0435\u043d\u0442\u0430 \u043a \u0432\u0430\u0448\u0438\u043c \u0443\u0441\u043b\u0443\u0433\u0430\u043c. \u0414\u0430\u0432\u0430\u0439\u0442\u0435 \u043d\u0430\u0447\u043d\u0435\u043c \u0441 \u0432\u044b\u0431\u043e\u0440\u0430 \u044f\u0437\u044b\u043a\u0430.',
            'uz': "Assalomu alaykum! Toshkentning eng zo'r Maestrolari xizmatingizda. Boshlash uchun tilni tanlang.",
        },
        'welcome_back': {
            'ru': '\u0421 \u0432\u043e\u0437\u0432\u0440\u0430\u0449\u0435\u043d\u0438\u0435\u043c, {}! \u0420\u0430\u0434\u044b \u0432\u0438\u0434\u0435\u0442\u044c \u0432\u0430\u0441 \u0441\u043d\u043e\u0432\u0430.',
            'uz': "Xush kelibsiz, {}! Sizni yana ko'rib turganimizdan xursandmiz.",
        },
        'ask_search_method': {
            'ru': '\u041a\u0430\u043a \u0432\u044b \u0445\u043e\u0442\u0438\u0442\u0435 \u043d\u0430\u0439\u0442\u0438 \u0441\u0432\u043e\u0435\u0433\u043e \u041c\u0430\u044d\u0441\u0442\u0440\u043e?',
            'uz': 'Maestroyingizni qanday topishni xohlaysiz?',
        },
        'language_menu_title': {
            'ru': '\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u044f\u0437\u044b\u043a \u0438\u043d\u0442\u0435\u0440\u0444\u0435\u0439\u0441\u0430.',
            'uz': 'Interfeys tilini tanlang.',
        },
        'language_changed': {
            'ru': '\u042f\u0437\u044b\u043a \u0438\u043d\u0442\u0435\u0440\u0444\u0435\u0439\u0441\u0430 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d.',
            'uz': 'Interfeys tili yangilandi.',
        },
        'profile_empty': {
            'ru': '\u0423 \u0432\u0430\u0441 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442 \u0437\u0430\u043f\u0438\u0441\u0435\u0439.',
            'uz': "Sizda hozircha yozuvlar yo'q.",
        },
        'profile_bookings_title': {
            'ru': '\u0412\u0430\u0448\u0438 \u0437\u0430\u043f\u0438\u0441\u0438:',
            'uz': 'Sizning yozuvlaringiz:',
        },
        'profile_lang_ru': {
            'ru': '\u0420\u0443\u0441\u0441\u043a\u0438\u0439',
            'uz': 'Ruscha',
        },
        'profile_lang_uz': {
            'ru': '\u0423\u0437\u0431\u0435\u043a\u0441\u043a\u0438\u0439',
            'uz': "O'zbekcha",
        },
        'master_label': {
            'ru': '\u041c\u0430\u0441\u0442\u0435\u0440',
            'uz': 'Maestro',
        },
        'status_label': {
            'ru': '\u0421\u0442\u0430\u0442\u0443\u0441',
            'uz': 'Holat',
        },
        'status_pending': {
            'ru': '\u23f3 \u041e\u0436\u0438\u0434\u0430\u043d\u0438\u0435',
            'uz': '\u23f3 Kutilmoqda',
        },
        'status_approved': {
            'ru': '\u2705 \u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043e',
            'uz': '\u2705 Tasdiqlangan',
        },
        'status_declined': {
            'ru': '\u274c \u041e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e',
            'uz': '\u274c Bekor qilingan',
        },
        'status_completed': {
            'ru': '\U0001f3c1 \u0417\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e',
            'uz': '\U0001f3c1 Yakunlangan',
        },
        'status_cancelled': {
            'ru': '\ud83d\udeab \u041e\u0442\u043c\u0435\u043d\u0435\u043d\u043e \u043a\u043b\u0438\u0435\u043d\u0442\u043e\u043c',
            'uz': '\ud83d\udeab Mijoz bekor qildi',
        },
        'cancel_booking': {
            'ru': '\u274c \u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c',
            'uz': '\u274c Bekor qilish',
        },
        'favorites_empty': {
            'ru': '\u0423 \u0432\u0430\u0441 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442 \u0438\u0437\u0431\u0440\u0430\u043d\u043d\u044b\u0445 \u043c\u0430\u0441\u0442\u0435\u0440\u043e\u0432.',
            'uz': "Sizda hozircha sevimli maestrolar yo'q.",
        },
        'favorites_title': {
            'ru': '\u0412\u0430\u0448\u0438 \u0438\u0437\u0431\u0440\u0430\u043d\u043d\u044b\u0435 \u043c\u0430\u0441\u0442\u0435\u0440\u0430:\n\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u043d\u0430 \u0438\u043c\u044f, \u0447\u0442\u043e\u0431\u044b \u043e\u0442\u043a\u0440\u044b\u0442\u044c \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0443 \u043c\u0430\u0441\u0442\u0435\u0440\u0430.',
            'uz': 'Sevimli maestrolaringiz:\nProfilni ochish uchun ism ustiga bosing.',
        },
        'search_by_id': {
            'ru': '\U0001f194 \u0412\u0432\u0435\u0441\u0442\u0438 ID \u041c\u0430\u044d\u0441\u0442\u0440\u043e',
            'uz': '\U0001f194 Maestro ID sini kiritish',
        },
        'language_name_ru': {
            'ru': '\U0001f1f7\U0001f1fa \u0420\u0443\u0441\u0441\u043a\u0438\u0439',
            'uz': '\U0001f1f7\U0001f1fa Ruscha',
        },
        'language_name_uz': {
            'ru': '\U0001f1fa\U0001f1ff \u0423\u0437\u0431\u0435\u043a\u0441\u043a\u0438\u0439',
            'uz': '\U0001f1fa\U0001f1ff O\'zbekcha',
        },
    }
    return texts.get(key, {}).get(lang, texts.get(key, {}).get('ru', 'Text not found'))


def get_buttons(lang='ru'):
    buttons = {
        'search_menu': {
            'ru': '\u2702\ufe0f \u0417\u0430\u043f\u0438\u0441\u0430\u0442\u044c\u0441\u044f / \u041f\u043e\u0438\u0441\u043a',
            'uz': '\u2702\ufe0f Yozilish / Izlash',
        },
        'my_masters': {
            'ru': '\u2b50 \u041c\u043e\u0438 \u043c\u0430\u0441\u0442\u0435\u0440\u0430',
            'uz': '\u2b50 Mening maestrolarim',
        },
        'my_profile': {
            'ru': '\U0001f464 \u041c\u043e\u0439 \u043f\u0440\u043e\u0444\u0438\u043b\u044c',
            'uz': '\U0001f464 Mening profilim',
        },
        'change_language': {
            'ru': '\U0001f310 \u042f\u0437\u044b\u043a',
            'uz': '\U0001f310 Til',
        },
    }
    return {k: v.get(lang, v.get('ru', '')) for k, v in buttons.items()}
