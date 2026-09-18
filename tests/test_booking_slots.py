"""
Тесты защиты слота от двойной брони (docs/AUDIT.md, A-4) и расчёта свободного времени.
"""
import pytest
from sqlalchemy.exc import IntegrityError

import database as db


def _booking(fixture_data, when: str, status: str = "pending") -> db.Booking:
    return db.Booking(
        user_id=fixture_data["client_user"].id,
        stylist_id=fixture_data["stylist"].id,
        service_id=fixture_data["service"].id,
        datetime=when,
        status=status,
    )


class TestSlotUniqueness:
    async def test_second_active_booking_on_same_slot_is_rejected(self, fixture_data):
        session = fixture_data["session"]
        # В фикстуре уже есть pending-запись на 2099-01-01 12:00.
        session.add(_booking(fixture_data, "2099-01-01 12:00"))

        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async def test_approved_also_blocks_the_slot(self, fixture_data):
        session = fixture_data["session"]
        session.add(_booking(fixture_data, "2099-01-01 12:00", status="approved"))

        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async def test_declined_slot_can_be_booked_again(self, fixture_data):
        session = fixture_data["session"]
        fixture_data["booking"].status = "declined"
        await session.commit()

        session.add(_booking(fixture_data, "2099-01-01 12:00"))
        await session.commit()  # не должно бросать

    async def test_cancelled_slot_can_be_booked_again(self, fixture_data):
        session = fixture_data["session"]
        fixture_data["booking"].status = "cancelled"
        await session.commit()

        session.add(_booking(fixture_data, "2099-01-01 12:00"))
        await session.commit()

    async def test_other_time_is_free(self, fixture_data):
        session = fixture_data["session"]
        session.add(_booking(fixture_data, "2099-01-01 13:00"))
        await session.commit()

    async def test_same_time_different_stylist_is_allowed(self, fixture_data):
        session = fixture_data["session"]
        other_stylist = db.Stylist(
            name="Второй мастер",
            barbershop_id=fixture_data["stylist"].barbershop_id,
        )
        session.add(other_stylist)
        await session.flush()

        session.add(
            db.Booking(
                user_id=fixture_data["client_user"].id,
                stylist_id=other_stylist.id,
                service_id=fixture_data["service"].id,
                datetime="2099-01-01 12:00",
                status="pending",
            )
        )
        await session.commit()


class TestReviewsCount:
    async def test_reviews_count_tracks_number_of_ratings(self, fixture_data):
        import bot

        session = fixture_data["session"]
        fixture_data["booking"].rating = 5
        session.add(_booking(fixture_data, "2099-02-01 12:00", status="completed"))
        await session.flush()

        second = await session.scalar(
            db.select(db.Booking).where(db.Booking.datetime == "2099-02-01 12:00")
        )
        second.rating = 3
        await session.commit()

        await bot.recalculate_stylist_rating(session, fixture_data["stylist"].id)
        assert fixture_data["stylist"].reviews_count == 2
        assert fixture_data["stylist"].avg_rating == 4.0
