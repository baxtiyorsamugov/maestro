"""
Тесты записи офлайн-клиента (docs/ROADMAP.md, Фаза 4).

Клиент, пришедший с улицы или позвонивший, существовал только в голове мастера:
занять его время было нечем, и бот продолжал предлагать этот слот другим.

Такая запись — строка Booking с user_id IS NULL. Отсюда два класса рисков,
которые здесь и проверяются.

1. Запись обязана честно занимать слот: ради этого всё и делалось.
2. Половина кода бота считает, что у записи есть клиент в Telegram.
   Напоминание, follow-up, запрос оценки, карточка заявки — всё это
   обращается к booking.user. На офлайн-записи там None.

Второе опаснее первого: падает оно не в момент создания записи, а ночью
в шедулере, и мастер об этом не узнает.
"""
from datetime import timedelta

import database as db
import texts
import timeutils
from services.booking import (
    GUEST_NAME_MAX_LEN,
    build_offline_booking,
    get_available_slots_for_date,
    is_offline_booking,
    normalize_guest_name,
)


async def _service(fixture_data) -> db.Service:
    return await fixture_data["session"].get(db.Service, fixture_data["service"].id)


async def _workday(fixture_data, day) -> None:
    session = fixture_data["session"]
    session.add(db.Schedule(
        stylist_id=fixture_data["stylist"].id,
        day_of_week=day.isoweekday(),
        start_time="10:00",
        end_time="14:00",
    ))
    await session.commit()


class TestGuestName:
    def test_extra_spaces_are_collapsed(self):
        assert normalize_guest_name("  Али   Валиев  ") == "Али Валиев"

    def test_empty_becomes_none(self):
        """«Время без имени» и «имя из пробелов» должны выглядеть одинаково."""
        assert normalize_guest_name("") is None
        assert normalize_guest_name("   ") is None
        assert normalize_guest_name(None) is None

    def test_long_name_is_trimmed_to_column_width(self):
        """
        Обрезаем на входе, а не ловим ошибку базы после того,
        как человек уже набрал текст.
        """
        result = normalize_guest_name("я" * 500)

        assert len(result) == GUEST_NAME_MAX_LEN

    def test_newlines_do_not_survive(self):
        # Перенос собирается из частей намеренно. Литерал «Али<перенос>Валиев» —
        # это ровно тот шаблон, который ищет scripts/check_encoding.py
        # (кириллица вплотную перед переносом = съеденный символ), и проверка
        # упала бы на этом тесте, не отличив фикстуру от настоящей порчи.
        assert normalize_guest_name("Али" + chr(10) + "Валиев") == "Али Валиев"


class TestBuildOfflineBooking:
    async def test_status_is_approved_immediately(self, fixture_data):
        """Подтверждать нечего: мастер и есть тот, кто подтверждает."""
        booking = build_offline_booking(
            fixture_data["stylist"].id,
            await _service(fixture_data),
            timeutils.parse_slot("2099-05-05 12:00"),
        )

        assert booking.status == db.BOOKING_APPROVED

    async def test_price_is_saved(self, fixture_data):
        """Офлайн-визит тоже выручка — и тоже по цене на момент записи."""
        service = await _service(fixture_data)
        booking = build_offline_booking(
            fixture_data["stylist"].id, service, timeutils.parse_slot("2099-05-05 12:00"),
        )

        assert booking.price == int(round(service.price))

    async def test_has_no_client(self, fixture_data):
        booking = build_offline_booking(
            fixture_data["stylist"].id,
            await _service(fixture_data),
            timeutils.parse_slot("2099-05-05 12:00"),
        )

        assert booking.user_id is None
        assert is_offline_booking(booking) is True

    async def test_duration_comes_from_service(self, fixture_data):
        service = await _service(fixture_data)
        booking = build_offline_booking(
            fixture_data["stylist"].id, service, timeutils.parse_slot("2099-05-05 12:00")
        )

        assert booking.ends_at - booking.starts_at == timedelta(minutes=service.duration_min)

    async def test_client_booking_is_not_offline(self, fixture_data):
        assert is_offline_booking(fixture_data["booking"]) is False

    async def test_it_saves(self, fixture_data):
        session = fixture_data["session"]
        booking = build_offline_booking(
            fixture_data["stylist"].id,
            await _service(fixture_data),
            timeutils.parse_slot("2099-05-05 12:00"),
            "Али",
        )
        session.add(booking)
        await session.commit()

        assert booking.id is not None
        assert booking.guest_name == "Али"


class TestSlotIsReallyTaken:
    """Главное, ради чего задача делалась."""

    async def test_offline_booking_removes_the_slot(self, fixture_data):
        session = fixture_data["session"]
        day = timeutils.today() + timedelta(days=10)
        await _workday(fixture_data, day)

        _, before = await get_available_slots_for_date(
            session, fixture_data["stylist"].id, fixture_data["service"].id, day
        )

        session.add(build_offline_booking(
            fixture_data["stylist"].id,
            await _service(fixture_data),
            timeutils.parse_slot(f"{day:%Y-%m-%d} 12:00"),
        ))
        await session.commit()

        _, after = await get_available_slots_for_date(
            session, fixture_data["stylist"].id, fixture_data["service"].id, day
        )

        assert "12:00" in before
        assert "12:00" not in after

    async def test_double_booking_is_rejected_by_the_index(self, fixture_data):
        """
        Тот же частичный уникальный индекс, что защищает клиентские записи.
        Он построен по stylist_id и starts_at, поэтому про user_id ему всё равно.
        """
        from sqlalchemy.exc import IntegrityError

        session = fixture_data["session"]
        service = await _service(fixture_data)
        slot = timeutils.parse_slot("2099-05-06 12:00")

        session.add(build_offline_booking(fixture_data["stylist"].id, service, slot))
        await session.commit()

        session.add(build_offline_booking(fixture_data["stylist"].id, service, slot, "Второй"))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
        else:
            raise AssertionError("две офлайн-записи заняли один слот")

    async def test_offline_booking_blocks_a_client(self, fixture_data):
        """Встречная проверка: клиент не должен записаться на занятое время."""
        from sqlalchemy.exc import IntegrityError

        session = fixture_data["session"]
        service = await _service(fixture_data)
        slot = timeutils.parse_slot("2099-05-07 12:00")

        session.add(build_offline_booking(fixture_data["stylist"].id, service, slot))
        await session.commit()

        session.add(db.Booking(
            user_id=fixture_data["client_user"].id,
            stylist_id=fixture_data["stylist"].id,
            service_id=service.id,
            starts_at=slot,
            ends_at=slot + timedelta(minutes=60),
            status=db.BOOKING_PENDING,
        ))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
        else:
            raise AssertionError("клиент записался поверх офлайн-записи")


class TestClientsCannotSeeOfflineBookings:
    async def test_load_booking_for_client_does_not_find_it(self, fixture_data):
        """
        Запрос клиента идёт через JOIN по user_id. Офлайн-запись в него
        не попадает — отменить или перенести чужое занятое время нельзя.
        """
        from services.access import load_booking_for_client

        session = fixture_data["session"]
        booking = build_offline_booking(
            fixture_data["stylist"].id,
            await _service(fixture_data),
            timeutils.parse_slot("2099-05-08 12:00"),
        )
        session.add(booking)
        await session.commit()

        found = await load_booking_for_client(
            session, booking.id, fixture_data["client_user"].telegram_id
        )

        assert found is None

    async def test_stylist_still_owns_it(self, fixture_data):
        from services.access import load_booking_for_stylist

        session = fixture_data["session"]
        booking = build_offline_booking(
            fixture_data["stylist"].id,
            await _service(fixture_data),
            timeutils.parse_slot("2099-05-09 12:00"),
        )
        session.add(booking)
        await session.commit()

        found = await load_booking_for_stylist(
            session, booking.id, fixture_data["stylist_user"].telegram_id
        )

        assert found is not None


class TestNotificationsSkipOfflineBookings:
    """
    Код напоминаний обращается к b.user.language_code. На офлайн-записи
    там None, и падало бы это ночью в шедулере — там, где никто не смотрит.
    """

    async def test_reminder_query_excludes_them(self, fixture_data):
        from sqlalchemy import select

        session = fixture_data["session"]
        soon = timeutils.now() + timedelta(hours=24)
        booking = build_offline_booking(
            fixture_data["stylist"].id, await _service(fixture_data), soon
        )
        session.add(booking)
        await session.commit()

        # Тот же фильтр, что в scheduler.check_reminders.
        found = (await session.execute(
            select(db.Booking).where(
                db.Booking.status == db.BOOKING_APPROVED,
                db.Booking.user_id.is_not(None),
            )
        )).scalars().all()

        assert booking.id not in [item.id for item in found]

    async def test_follow_up_query_excludes_them(self, fixture_data):
        from sqlalchemy import select

        session = fixture_data["session"]
        booking = build_offline_booking(
            fixture_data["stylist"].id,
            await _service(fixture_data),
            timeutils.now() - timedelta(days=20),
        )
        booking.status = db.BOOKING_COMPLETED
        session.add(booking)
        await session.commit()

        found = (await session.execute(
            select(db.Booking).where(
                db.Booking.status == db.BOOKING_COMPLETED,
                db.Booking.follow_up_sent.is_(False),
                db.Booking.user_id.is_not(None),
            )
        )).scalars().all()

        assert booking.id not in [item.id for item in found]


class TestBookingCardSurvivesMissingClient:
    """
    Карточка заявки обращалась к booking.user.first_name, .phone_number
    и .telegram_id тремя строками подряд. Проверяем, что она собирается.
    """

    async def _card(self, fixture_data, guest_name):
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from presenters import build_booking_card

        session = fixture_data["session"]
        booking = build_offline_booking(
            fixture_data["stylist"].id,
            await _service(fixture_data),
            timeutils.parse_slot("2099-05-10 12:00"),
            guest_name,
        )
        session.add(booking)
        await session.commit()

        loaded = await session.scalar(
            select(db.Booking)
            .where(db.Booking.id == booking.id)
            .options(
                joinedload(db.Booking.user),
                joinedload(db.Booking.service).joinedload(db.Service.catalog_service),
            )
        )
        return build_booking_card(loaded, lang="ru")

    async def test_named_guest_is_shown(self, fixture_data):
        card = await self._card(fixture_data, "Али")

        assert "Али" in card

    async def test_unnamed_guest_gets_a_placeholder(self, fixture_data):
        card = await self._card(fixture_data, None)

        assert texts.get_text("offline_guest_unnamed", "ru") in card

    async def test_no_telegram_link_is_rendered(self, fixture_data):
        """Ссылка tg://user?id=None была бы нерабочей кнопкой в карточке."""
        card = await self._card(fixture_data, "Али")

        assert "tg://user" not in card

    async def test_badge_explains_why_there_is_no_phone(self, fixture_data):
        card = await self._card(fixture_data, "Али")

        assert texts.get_text("offline_badge", "ru") in card


class TestRevenueStillCounts:
    async def test_offline_booking_is_not_joined_away_from_stats(self, fixture_data):
        """
        Выручка считается через JOIN по услуге, а не по клиенту. Офлайн-визит
        мастер отработал и деньги получил — в статистику он входить обязан.
        """
        from sqlalchemy import func, select

        session = fixture_data["session"]
        service = await _service(fixture_data)
        booking = build_offline_booking(
            fixture_data["stylist"].id, service, timeutils.parse_slot("2099-05-11 12:00")
        )
        booking.status = db.BOOKING_COMPLETED
        session.add(booking)
        await session.commit()

        total = await session.scalar(
            select(func.sum(db.Service.price))
            .select_from(db.Booking)
            .join(db.Service, db.Service.id == db.Booking.service_id)
            .where(
                db.Booking.stylist_id == fixture_data["stylist"].id,
                db.Booking.status == db.BOOKING_COMPLETED,
            )
        )

        assert total == service.price


class TestRatingIsNotDiluted:
    async def test_offline_booking_does_not_enter_the_average(self, fixture_data):
        """У офлайн-визита оценки нет: рейтинг считается по rating IS NOT NULL."""
        from services.rating import recalculate_stylist_rating

        session = fixture_data["session"]
        rated = fixture_data["booking"]
        rated.status = db.BOOKING_COMPLETED
        rated.rating = 5
        session.add(build_offline_booking(
            fixture_data["stylist"].id,
            await _service(fixture_data),
            timeutils.parse_slot("2099-05-12 12:00"),
        ))
        await session.commit()

        average = await recalculate_stylist_rating(session, fixture_data["stylist"].id)

        assert average == 5.0
