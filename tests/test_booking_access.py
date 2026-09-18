"""
Тесты правил доступа к записям (docs/AUDIT.md, A-2) и пересчёта рейтинга (A-3).
"""
from datetime import timedelta

import presenters
import timeutils
from services import access, rating


class TestStylistAccess:
    async def test_stylist_sees_own_booking(self, fixture_data):
        booking = await access.load_booking_for_stylist(
            fixture_data["session"],
            fixture_data["booking"].id,
            fixture_data["stylist_user"].telegram_id,
        )
        assert booking is not None
        assert booking.id == fixture_data["booking"].id

    async def test_intruder_cannot_access_foreign_booking(self, fixture_data):
        booking = await access.load_booking_for_stylist(
            fixture_data["session"],
            fixture_data["booking"].id,
            fixture_data["intruder"].telegram_id,
        )
        assert booking is None, "посторонний не должен получать чужую заявку"

    async def test_client_cannot_approve_own_booking_as_stylist(self, fixture_data):
        booking = await access.load_booking_for_stylist(
            fixture_data["session"],
            fixture_data["booking"].id,
            fixture_data["client_user"].telegram_id,
        )
        assert booking is None, "клиент не должен подтверждать собственную заявку"


class TestClientAccess:
    async def test_client_sees_own_booking(self, fixture_data):
        booking = await access.load_booking_for_client(
            fixture_data["session"],
            fixture_data["booking"].id,
            fixture_data["client_user"].telegram_id,
        )
        assert booking is not None

    async def test_intruder_cannot_cancel_foreign_booking(self, fixture_data):
        booking = await access.load_booking_for_client(
            fixture_data["session"],
            fixture_data["booking"].id,
            fixture_data["intruder"].telegram_id,
        )
        assert booking is None, "посторонний не должен отменять чужую запись"

    async def test_stylist_is_not_client_of_booking(self, fixture_data):
        booking = await access.load_booking_for_client(
            fixture_data["session"],
            fixture_data["booking"].id,
            fixture_data["stylist_user"].telegram_id,
        )
        assert booking is None


class TestRatingRecalculation:
    async def test_rating_starts_at_zero(self, fixture_data):
        assert fixture_data["stylist"].avg_rating == 0.0

    async def test_single_rating_becomes_average(self, fixture_data):
        session = fixture_data["session"]
        fixture_data["booking"].rating = 5
        await session.commit()

        value = await rating.recalculate_stylist_rating(session, fixture_data["stylist"].id)
        assert value == 5.0
        assert fixture_data["stylist"].avg_rating == 5.0

    async def test_average_of_several_ratings(self, fixture_data):
        import database as db

        session = fixture_data["session"]
        fixture_data["booking"].rating = 5

        second_starts = timeutils.parse_slot("2099-01-02 12:00")
        second = db.Booking(
            user_id=fixture_data["client_user"].id,
            stylist_id=fixture_data["stylist"].id,
            service_id=fixture_data["service"].id,
            starts_at=second_starts,
            ends_at=second_starts + timedelta(minutes=60),
            status=db.BOOKING_COMPLETED,
            rating=4,
        )
        session.add(second)
        await session.commit()

        value = await rating.recalculate_stylist_rating(session, fixture_data["stylist"].id)
        assert value == 4.5

    async def test_unrated_bookings_are_ignored(self, fixture_data):
        import database as db

        session = fixture_data["session"]
        fixture_data["booking"].rating = 4
        session.add(
            db.Booking(
                user_id=fixture_data["client_user"].id,
                stylist_id=fixture_data["stylist"].id,
                service_id=fixture_data["service"].id,
                starts_at=timeutils.parse_slot("2099-01-03 12:00"),
                ends_at=timeutils.parse_slot("2099-01-03 13:00"),
                status=db.BOOKING_COMPLETED,
                rating=None,
            )
        )
        await session.commit()

        value = await rating.recalculate_stylist_rating(session, fixture_data["stylist"].id)
        assert value == 4.0, "записи без оценки не должны занижать средний балл"


class TestBookingCard:
    async def test_card_escapes_user_input(self, fixture_data):
        session = fixture_data["session"]
        fixture_data["client_user"].first_name = "<b>Взлом</b>"
        await session.commit()

        booking = await access.load_booking_for_stylist(
            session, fixture_data["booking"].id, fixture_data["stylist_user"].telegram_id
        )
        card = presenters.build_booking_card(booking)

        assert "<b>Взлом</b>" not in card.replace("<b>Новая заявка</b>", "")
        assert "&lt;b&gt;Взлом&lt;/b&gt;" in card

    async def test_card_uses_database_not_message_text(self, fixture_data):
        booking = await access.load_booking_for_stylist(
            fixture_data["session"],
            fixture_data["booking"].id,
            fixture_data["stylist_user"].telegram_id,
        )
        card = presenters.build_booking_card(booking, footer="Запись подтверждена")

        assert "+998901234567" in card
        assert "Стрижка" in card
        assert "2099-01-01 12:00" in card
        assert "Запись подтверждена" in card
