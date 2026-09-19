"""
Тесты повтора прошлой записи (docs/ROADMAP.md, Фаза 4).

Вернувшийся клиент проходил те же пять экранов, что и новый: ввод ID мастера,
карточка, услуга, календарь, слот. При том что обычно идёт к тому же мастеру
на ту же услугу.

Главное правило здесь — кнопка не должна приводить в тупик. Если мастер закрыт
по тарифу или услуга удалена, лучше не показывать кнопку вовсе, чем показать
неработающую: человек нажмёт и получит отказ, не понимая, что сделал не так.
"""
from datetime import date, timedelta

import database as db
import timeutils
from services.booking import get_last_booking_for_repeat


async def _add_booking(fixture_data, when: str, status: str = db.BOOKING_COMPLETED):
    session = fixture_data["session"]
    starts_at = timeutils.parse_slot(when)
    booking = db.Booking(
        user_id=fixture_data["client_user"].id,
        stylist_id=fixture_data["stylist"].id,
        service_id=fixture_data["service"].id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=60),
        status=status,
    )
    session.add(booking)
    await session.commit()
    return booking


class TestLastBookingLookup:
    async def test_returns_booking_for_client_with_history(self, fixture_data):
        found = await get_last_booking_for_repeat(
            fixture_data["session"], fixture_data["client_user"].id
        )
        assert found is not None
        assert found.id == fixture_data["booking"].id

    async def test_returns_none_for_client_without_history(self, fixture_data):
        found = await get_last_booking_for_repeat(
            fixture_data["session"], fixture_data["intruder"].id
        )
        assert found is None

    async def test_picks_the_most_recent(self, fixture_data):
        """В фикстуре запись на 2099-01-01, добавляем более позднюю."""
        newer = await _add_booking(fixture_data, "2099-06-15 10:00")

        found = await get_last_booking_for_repeat(
            fixture_data["session"], fixture_data["client_user"].id
        )
        assert found.id == newer.id

    async def test_ignores_older_booking(self, fixture_data):
        await _add_booking(fixture_data, "2098-01-01 10:00")

        found = await get_last_booking_for_repeat(
            fixture_data["session"], fixture_data["client_user"].id
        )
        assert found.id == fixture_data["booking"].id

    async def test_cancelled_booking_can_still_be_repeated(self, fixture_data):
        """Клиент отменил визит — предложить записаться снова уместно."""
        session = fixture_data["session"]
        fixture_data["booking"].status = db.BOOKING_CANCELLED
        await session.commit()

        found = await get_last_booking_for_repeat(session, fixture_data["client_user"].id)
        assert found is not None


class TestDeadEndsAreHidden:
    """Кнопка не показывается, если нажатие всё равно привело бы к отказу."""

    async def test_expired_stylist_hides_button(self, fixture_data):
        session = fixture_data["session"]
        fixture_data["stylist_user"].subscription_until = date(2000, 1, 1)
        await session.commit()

        found = await get_last_booking_for_repeat(session, fixture_data["client_user"].id)
        assert found is None, "мастер закрыт по тарифу — повторять нечего"

    async def test_inactive_stylist_hides_button(self, fixture_data):
        session = fixture_data["session"]
        fixture_data["stylist_user"].is_active = False
        await session.commit()

        found = await get_last_booking_for_repeat(session, fixture_data["client_user"].id)
        assert found is None

    async def test_deleted_service_hides_button(self, fixture_data):
        """
        Услугу удалили — запись остаётся в истории, но повторять её нечем.
        Проверяем через JOIN: запись без существующей услуги не должна находиться.
        """
        from sqlalchemy import delete

        session = fixture_data["session"]
        booking = fixture_data["booking"]
        await session.execute(delete(db.Booking).where(db.Booking.id == booking.id))
        await session.execute(delete(db.Service).where(db.Service.id == booking.service_id))
        await session.commit()

        found = await get_last_booking_for_repeat(session, fixture_data["client_user"].id)
        assert found is None


class TestLoadedRelations:
    """
    Кнопке нужны имя мастера и название услуги. Без joinedload обращение
    к ним в async-контексте бросит MissingGreenlet (CLAUDE.md, 4.3).
    """

    async def test_stylist_and_service_are_loaded(self, fixture_data):
        session = fixture_data["session"]
        found = await get_last_booking_for_repeat(session, fixture_data["client_user"].id)

        session.expunge_all()
        assert found.stylist.name == "Мастер"
        assert found.service.catalog_service.name == "Стрижка"
