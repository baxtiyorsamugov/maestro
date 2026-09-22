"""
Сквозные сценарии через настоящий диспетчер (docs/ROADMAP.md, Фаза 5).

Каждый апдейт идёт тем же путём, что у живого бота: middleware, порядок
роутеров, фильтры, FSM между шагами. Подменена только сессия Telegram —
запросы записываются, а не отправляются.

Такие тесты ловят то, чего не видят юнит-тесты и не видели смоук-скрипты:
хендлер, до которого апдейт никогда не доходит, потому что его перехватил
соседний роутер; кнопку, которая перестала работать после переключения
языка; состояние FSM, которое не пережило переход между шагами.
"""
from datetime import timedelta

import pytest_asyncio

import bot  # noqa: F401 — импорт подключает роутеры к диспетчеру
import database as db
import loader
import timeutils
from scenario_harness import RecordingSession, Scenario


@pytest_asyncio.fixture
async def world(session):
    """
    Живой диспетчер с подменённой сессией и чистым состоянием.

    Антифлуд на время сценария отключаем: тест шлёт апдейты подряд быстрее
    любого человека, и middleware справедливо принял бы это за атаку.
    Сам антифлуд проверяется отдельным тестом ниже, с включённой защитой.
    """
    recording = RecordingSession()
    original_session = loader.bot.session
    loader.bot.session = recording

    original_is_throttled = loader.throttling._is_throttled
    loader.throttling._is_throttled = lambda user_id: False

    # FSM в памяти общий на весь процесс: без очистки состояние одного
    # теста доезжало бы до следующего, и порядок запуска менял бы результат.
    loader.dp.storage.storage.clear()

    yield recording

    loader.bot.session = original_session
    loader.throttling._is_throttled = original_is_throttled
    loader.dp.storage.storage.clear()


def person(world, telegram_id, first_name="Тест") -> Scenario:
    return Scenario(loader.dp, loader.bot, world, telegram_id, first_name)


class TestRegistration:
    async def test_new_person_is_asked_for_language(self, world):
        new = person(world, 7001)

        replies = await new.command("/start")

        assert replies.buttons(), "новому человеку нужно предложить выбор языка"
        assert any(data and data.startswith("lang_") for data in replies.callbacks())

    async def test_full_registration_creates_the_user(self, world):
        """
        Язык → имя → контакт: три шага через FSM. Юнит-тест каждого шага
        по отдельности не заметил бы, что состояние не доехало до следующего.
        """
        new = person(world, 7002, "Гульнора")

        await new.command("/start")
        await new.press("lang_ru")
        await new.say("Гульнора")
        await new.share_contact("+998901112233")

        async with db.async_session() as s:
            from sqlalchemy import select

            user = await s.scalar(select(db.User).where(db.User.telegram_id == 7002))

        assert user is not None
        assert user.language_code == "ru"
        assert user.first_name == "Гульнора"
        assert user.phone_number == "+998901112233"

    async def test_uzbek_registration_answers_in_uzbek(self, world):
        """
        Перевод, лежащий в texts.py, но не получивший язык от вызывающего кода,
        не доезжает до человека (CLAUDE.md, 4.5). Проверяем по живым ответам.
        """
        new = person(world, 7003, "Alisher")

        await new.command("/start")
        after_language = await new.press("lang_uz")

        text = after_language.last_text
        # Сначала — что ответ вообще был. Проверка «русского нет» на пустом
        # ответе проходит всегда: именно так этот тест однажды и зеленел,
        # когда до хендлеров не доходил ни один апдейт.
        assert text, "бот ничего не ответил — проверка языка ничего бы не значила"
        russian = ("Как вас", "Введите", "Отправьте", "Пожалуйста")
        assert not any(word in text for word in russian), f"русский текст на uz: {text!r}"


async def _open_workday(fixture_data):
    """Мастер работает каждый день 10–18: календарю есть что показать."""
    session = fixture_data["session"]
    for day in range(1, 8):
        session.add(db.Schedule(
            stylist_id=fixture_data["stylist"].id, day_of_week=day,
            start_time="10:00", end_time="18:00",
        ))
    # Подписка обязательна: без неё мастер закрыт для записи.
    fixture_data["stylist_user"].subscription_until = (
        timeutils.today() + timedelta(days=365)
    )
    fixture_data["client_user"].language_code = "ru"
    fixture_data["stylist_user"].language_code = "ru"
    await session.commit()


async def _free_date(fixture_data):
    """Дата через неделю — заведомо в будущем и в пределах текущего окна."""
    return timeutils.today() + timedelta(days=7)


class TestBookingFunnel:
    """
    Главный сценарий продукта целиком: мастер → услуга → дата → время.

    Юнит-тесты проверяют каждый шаг отдельно. Здесь проверяется то, что
    между шагами: доехал ли выбор услуги до календаря, а даты — до слотов.
    Это состояние FSM, и именно оно ломается незаметно.
    """

    async def test_client_books_a_visit(self, world, fixture_data):
        await _open_workday(fixture_data)
        client = person(world, fixture_data["client_user"].telegram_id, "Клиент")
        stylist_id = fixture_data["stylist"].id
        service_id = fixture_data["service"].id
        target = await _free_date(fixture_data)

        services = await client.press(f"book_{stylist_id}")
        assert f"srv_{service_id}" in services.callbacks(), "услуги мастера не показаны"

        calendar = await client.press(f"srv_{service_id}")
        assert any(c.startswith("date_") for c in calendar.callbacks()), "календарь не открылся"

        slots = await client.press(f"date_{target:%Y-%m-%d}")
        assert "time_15:00" in slots.callbacks(), f"нет слота 15:00: {slots.callbacks()}"

        await client.press("time_15:00")

        async with db.async_session() as s:
            from sqlalchemy import select

            created = (await s.execute(
                select(db.Booking).where(
                    db.Booking.starts_at == timeutils.parse_slot(f"{target:%Y-%m-%d} 15:00")
                )
            )).scalars().all()

        assert len(created) == 1, "запись не создана"
        assert created[0].status == db.BOOKING_PENDING
        # Цена зафиксирована при записи, а не подтягивается из услуги потом.
        assert created[0].price == int(fixture_data["service"].price)

    async def test_stylist_is_notified_with_buttons(self, world, fixture_data):
        """
        Уведомление мастеру — единственный способ узнать о заявке.
        Без кнопок подтверждения оно бесполезно.
        """
        await _open_workday(fixture_data)
        client = person(world, fixture_data["client_user"].telegram_id, "Клиент")
        target = await _free_date(fixture_data)

        await client.press(f"book_{fixture_data['stylist'].id}")
        await client.press(f"srv_{fixture_data['service'].id}")
        await client.press(f"date_{target:%Y-%m-%d}")
        final = await client.press("time_12:00")

        stylist_telegram_id = fixture_data["stylist_user"].telegram_id
        notices = final.sent_to(stylist_telegram_id)
        assert notices, "мастеру ничего не пришло"

        approve_buttons = [
            c for c in world.calls
            if type(c).__name__ == "SendMessage"
            and getattr(c, "chat_id", None) == stylist_telegram_id
        ][-1].reply_markup.inline_keyboard[0]
        assert any(b.callback_data.startswith("approve_") for b in approve_buttons)

    async def test_every_step_closes_the_callback(self, world, fixture_data):
        """
        Каждое нажатие обязано получить answer(), иначе у человека висят
        «часики» (CLAUDE.md, 4.5). Проверяем на всей воронке разом.
        """
        await _open_workday(fixture_data)
        client = person(world, fixture_data["client_user"].telegram_id, "Клиент")
        target = await _free_date(fixture_data)

        for data in (
            f"book_{fixture_data['stylist'].id}",
            f"srv_{fixture_data['service'].id}",
            f"date_{target:%Y-%m-%d}",
            "time_11:00",
        ):
            replies = await client.press(data)
            assert replies.answered_callback, f"нажатие {data} оставило «часики»"


class TestApprovalAndCancellation:
    async def _booked(self, world, fixture_data, slot="16:00"):
        await _open_workday(fixture_data)
        client = person(world, fixture_data["client_user"].telegram_id, "Клиент")
        target = await _free_date(fixture_data)
        await client.press(f"book_{fixture_data['stylist'].id}")
        await client.press(f"srv_{fixture_data['service'].id}")
        await client.press(f"date_{target:%Y-%m-%d}")
        await client.press(f"time_{slot}")

        async with db.async_session() as s:
            from sqlalchemy import select

            booking = await s.scalar(select(db.Booking).where(
                db.Booking.starts_at == timeutils.parse_slot(f"{target:%Y-%m-%d} {slot}")
            ))
        return client, booking

    async def test_stylist_approves_and_client_is_told(self, world, fixture_data):
        client, booking = await self._booked(world, fixture_data)
        stylist = person(world, fixture_data["stylist_user"].telegram_id, "Мастер")

        replies = await stylist.press(f"approve_{booking.id}")

        async with db.async_session() as s:
            assert (await s.get(db.Booking, booking.id)).status == db.BOOKING_APPROVED
        assert replies.sent_to(fixture_data["client_user"].telegram_id), (
            "клиент не узнал, что запись подтверждена"
        )

    async def test_stranger_cannot_approve(self, world, fixture_data):
        """
        Идентификатор из callback_data — недоверенный ввод (CLAUDE.md, 4.4).
        Проверяем через настоящий диспетчер, а не вызовом функции.
        """
        _, booking = await self._booked(world, fixture_data)
        stranger = person(world, fixture_data["intruder"].telegram_id, "Посторонний")

        replies = await stranger.press(f"approve_{booking.id}")

        async with db.async_session() as s:
            assert (await s.get(db.Booking, booking.id)).status == db.BOOKING_PENDING
        assert replies.alerts, "посторонний не получил отказа"

    async def test_client_cancels_and_stylist_is_told(self, world, fixture_data):
        client, booking = await self._booked(world, fixture_data)

        replies = await client.press(f"booking_cancel_{booking.id}")

        async with db.async_session() as s:
            assert (await s.get(db.Booking, booking.id)).status == db.BOOKING_CANCELLED
        assert replies.sent_to(fixture_data["stylist_user"].telegram_id), (
            "мастер не узнал об отмене"
        )

    async def test_whole_story_lands_in_the_journal(self, world, fixture_data):
        """
        Запись → подтверждение → отмена через настоящие хендлеры.
        Журнал должен рассказать историю целиком — с автором каждого шага.
        """
        from services import audit

        client, booking = await self._booked(world, fixture_data)
        stylist = person(world, fixture_data["stylist_user"].telegram_id, "Мастер")
        await stylist.press(f"approve_{booking.id}")
        await client.press(f"booking_cancel_{booking.id}")

        async with db.async_session() as s:
            history = await audit.load_history_for_booking(s, booking.id)

        assert [e.action for e in history] == [
            audit.BOOKING_CREATED, audit.BOOKING_APPROVED, audit.BOOKING_CANCELLED,
        ]
        assert [e.actor_kind for e in history] == ["client", "stylist", "client"]


CYRILLIC = __import__("re").compile(r"[а-яА-ЯёЁ]")


class TestStylistLanguage:
    """
    Уведомления читает мастер, а не клиент. Раньше «Новая заявка» и
    «Запись отменена» уходили мастеру по-русски при любом его языке —
    хотя кнопки под заявкой уже были на его языке.
    """

    async def _uzbek_stylist(self, fixture_data):
        await _open_workday(fixture_data)
        fixture_data["stylist_user"].language_code = "uz"
        await fixture_data["session"].commit()

    async def test_new_request_reaches_uzbek_stylist_in_uzbek(self, world, fixture_data):
        await self._uzbek_stylist(fixture_data)
        client = person(world, fixture_data["client_user"].telegram_id, "Клиент")
        target = await _free_date(fixture_data)

        await client.press(f"book_{fixture_data['stylist'].id}")
        await client.press(f"srv_{fixture_data['service'].id}")
        await client.press(f"date_{target:%Y-%m-%d}")
        final = await client.press("time_13:00")

        notices = final.sent_to(fixture_data["stylist_user"].telegram_id)
        assert notices, "мастеру ничего не пришло"
        # Имя клиента и название услуги — данные, а не интерфейс: вырезаем их.
        chrome = notices[-1].replace("Клиент", "").replace("Стрижка", "")
        assert not CYRILLIC.search(chrome), f"русский в уведомлении мастеру-узбеку: {notices[-1]!r}"

    async def test_cancellation_reaches_uzbek_stylist_in_uzbek(self, world, fixture_data):
        await self._uzbek_stylist(fixture_data)
        client = person(world, fixture_data["client_user"].telegram_id, "Клиент")

        replies = await client.press(f"booking_cancel_{fixture_data['booking'].id}")

        notices = replies.sent_to(fixture_data["stylist_user"].telegram_id)
        assert notices, "мастер не узнал об отмене"
        chrome = notices[-1].replace("Клиент", "")
        assert not CYRILLIC.search(chrome), f"русский в уведомлении мастеру-узбеку: {notices[-1]!r}"


class TestClientLanguage:
    async def test_uzbek_client_sees_uzbek_calendar(self, world, fixture_data):
        """
        Календарь рисовался по-русски для всех: вызывающий код не передавал
        язык, а у generate_calendar было значение по умолчанию.
        """
        await _open_workday(fixture_data)
        fixture_data["client_user"].language_code = "uz"
        await fixture_data["session"].commit()
        client = person(world, fixture_data["client_user"].telegram_id, "Mijoz")
        target = await _free_date(fixture_data)

        await client.press(f"book_{fixture_data['stylist'].id}")
        calendar = await client.press(f"srv_{fixture_data['service'].id}")
        month_forward = await client.press(
            f"cal_{target.year + 1}-{target.month}_{fixture_data['stylist'].id}"
        )
        slots = await client.press(f"date_{target:%Y-%m-%d}")

        for screen in (calendar, month_forward, slots):
            labels = " ".join(text for text, _ in screen.buttons()) + screen.last_text
            assert labels.strip(), "экран пустой — проверка языка ничего бы не значила"
            assert not CYRILLIC.search(labels), f"русский на экране узбекского клиента: {labels!r}"


class TestFavorites:
    async def test_add_then_remove_from_list(self, world, fixture_data):
        """
        Удаление из избранного раньше падало: хендлер звал show_favorites()
        без state и с сообщением бота вместо сообщения клиента.
        """
        from sqlalchemy import select

        await _open_workday(fixture_data)
        client = person(world, fixture_data["client_user"].telegram_id, "Клиент")
        stylist_id = fixture_data["stylist"].id

        added = await client.press(f"fav_add_{stylist_id}")
        assert added.alerts, "добавление не подтверждено"

        removed = await client.press(f"fav_rem_{stylist_id}")
        assert removed.answered_callback
        assert removed.texts, "список не перерисован после удаления"

        async with db.async_session() as s:
            left = await s.scalar(select(db.Favorite).where(
                db.Favorite.user_id == fixture_data["client_user"].id
            ))
        assert left is None

    async def test_unregistered_person_gets_an_answer(self, world, fixture_data):
        """Кнопка из пересланной карточки: раньше AttributeError и «часики»."""
        stranger = person(world, 7777, "Новичок")
        replies = await stranger.press(f"fav_add_{fixture_data['stylist'].id}")
        # Именно просьба зарегистрироваться, а не «что-то пошло не так»:
        # общий обработчик ошибок тоже отвечает всплывашкой, и проверка
        # «ответ был» проходила бы на упавшем хендлере.
        assert any("/start" in alert for alert in replies.alerts), replies.alerts


class TestAccountDeletion:
    async def test_client_deletes_account_through_the_bot(self, world, fixture_data):
        """
        /privacy → «Удалить» → подтверждение. Сервис удаления покрыт своими
        тестами; здесь — что до него вообще можно дойти кнопками.
        """
        from sqlalchemy import select

        client = person(world, fixture_data["client_user"].telegram_id, "Клиент")

        menu = await client.command("/privacy")
        assert "privacy_delete_ask" in menu.callbacks(), "в /privacy нет кнопки удаления"

        confirm = await client.press("privacy_delete_ask")
        assert "privacy_delete_confirm" in confirm.callbacks(), "нет шага подтверждения"
        assert "privacy_delete_cancel" in confirm.callbacks(), "с подтверждения некуда уйти"

        done = await client.press("privacy_delete_confirm")
        assert done.answered_callback

        async with db.async_session() as s:
            gone = await s.scalar(
                select(db.User).where(db.User.telegram_id == fixture_data["client_user"].telegram_id)
            )
            booking = await s.get(db.Booking, fixture_data["booking"].id)
        assert gone is None, "аккаунт не удалён"
        assert booking.status == db.BOOKING_CANCELLED, "будущая запись осталась активной"
        assert done.sent_to(fixture_data["stylist_user"].telegram_id), (
            "мастер не узнал, что визит отменён"
        )


class TestThrottling:
    """
    Здесь антифлуд включён по-настоящему: подмену из фикстуры world снимаем.
    """

    async def test_burst_of_presses_is_cut_and_every_press_answered(self, world, fixture_data):
        import middlewares

        loader.throttling._is_throttled = (
            middlewares.ThrottlingMiddleware._is_throttled.__get__(loader.throttling)
        )
        telegram_id = fixture_data["client_user"].telegram_id
        loader.throttling._history.pop(telegram_id, None)
        loader.throttling._last_warning.pop(telegram_id, None)
        client = person(world, telegram_id, "Клиент")

        results = [await client.press("privacy_policy") for _ in range(10)]

        reached = [r for r in results if r.texts]
        assert 0 < len(reached) <= loader.throttling.burst, (
            f"до хендлера дошло {len(reached)} нажатий из 10"
        )
        # Отсечённое нажатие всё равно закрывается — иначе «часики» висят именно
        # у того, кто и так раздражённо жмёт кнопку.
        assert all(r.answered_callback for r in results)

        loader.throttling._history.pop(telegram_id, None)
        loader.throttling._last_warning.pop(telegram_id, None)
