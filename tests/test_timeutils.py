"""
Тесты работы со временем (docs/AUDIT.md, B-2).

Главное, что здесь проверяется: время визита не сдвигается ни на одном переходе
через границу «код — база — экран». Сдвиг на 5 часов не падает с ошибкой,
он просто покажет клиенту не тот час — это худший вид бага.
"""
from datetime import date, datetime, timedelta

import database as db
import timeutils


class TestParsing:
    def test_parse_slot_keeps_wall_clock(self):
        assert timeutils.parse_slot("2099-03-15 14:30") == datetime(2099, 3, 15, 14, 30)

    def test_parse_slot_rejects_garbage(self):
        for bad in ("мусор", "", "2099-13-45 99:99", "15.03.2099 14:30"):
            try:
                timeutils.parse_slot(bad)
            except ValueError:
                continue
            raise AssertionError(f"не отклонено: {bad!r}")

    def test_combine_builds_local_datetime(self):
        assert timeutils.combine(date(2099, 3, 15), "09:05") == datetime(2099, 3, 15, 9, 5)

    def test_now_is_naive(self):
        """Наивный datetime: смешивание с aware даёт TypeError при сравнении."""
        assert timeutils.now().tzinfo is None

    def test_now_matches_tashkent_wall_clock(self):
        from datetime import timezone

        utc_now = datetime.now(timezone.utc)
        expected = utc_now.astimezone(timeutils.TZ).replace(tzinfo=None)
        assert abs((timeutils.now() - expected).total_seconds()) < 5


class TestBounds:
    def test_day_bounds_is_half_open(self):
        start, end = timeutils.day_bounds(date(2099, 3, 15))
        assert start == datetime(2099, 3, 15, 0, 0)
        assert end == datetime(2099, 3, 16, 0, 0)

    def test_day_bounds_covers_last_minute(self):
        start, end = timeutils.day_bounds(date(2099, 3, 15))
        last_slot = datetime(2099, 3, 15, 23, 59)
        assert start <= last_slot < end

    def test_day_bounds_excludes_next_day_midnight(self):
        _, end = timeutils.day_bounds(date(2099, 3, 15))
        assert not (datetime(2099, 3, 16, 0, 0) < end)

    def test_range_bounds_includes_both_ends(self):
        start, end = timeutils.range_bounds(date(2099, 3, 1), date(2099, 3, 31))
        assert start == datetime(2099, 3, 1, 0, 0)
        assert end == datetime(2099, 4, 1, 0, 0)
        assert start <= datetime(2099, 3, 31, 23, 59) < end

    def test_range_bounds_single_day(self):
        start, end = timeutils.range_bounds(date(2099, 3, 15), date(2099, 3, 15))
        assert (end - start) == timedelta(days=1)


class TestFormatting:
    def test_format_slot_is_machine_readable(self):
        assert timeutils.format_slot(datetime(2099, 3, 15, 14, 30)) == "2099-03-15 14:30"

    def test_format_slot_handles_none(self):
        assert timeutils.format_slot(None) == "-"

    def test_today_is_named(self):
        value = timeutils.now().replace(hour=15, minute=0)
        assert timeutils.format_human(value, "ru").startswith("сегодня")
        assert timeutils.format_human(value, "uz").startswith("bugun")

    def test_tomorrow_is_named(self):
        value = (timeutils.now() + timedelta(days=1)).replace(hour=15, minute=0)
        assert timeutils.format_human(value, "ru").startswith("завтра")
        assert timeutils.format_human(value, "uz").startswith("ertaga")

    def test_distant_date_uses_month_name(self):
        assert timeutils.format_human(datetime(2099, 3, 15, 14, 30), "ru") == "15 марта, 14:30"
        assert timeutils.format_human(datetime(2099, 3, 15, 14, 30), "uz") == "15 mart, 14:30"

    def test_format_human_handles_none(self):
        assert timeutils.format_human(None) == "-"


class TestDatabaseRoundTrip:
    async def test_stored_time_comes_back_unchanged(self, fixture_data):
        """Запись на 14:30 обязана прочитаться как 14:30, без сдвига на зону."""
        session = fixture_data["session"]
        starts_at = timeutils.parse_slot("2099-05-20 14:30")

        booking = db.Booking(
            user_id=fixture_data["client_user"].id,
            stylist_id=fixture_data["stylist"].id,
            service_id=fixture_data["service"].id,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=60),
            status=db.BOOKING_PENDING,
        )
        session.add(booking)
        await session.commit()
        session.expunge_all()

        loaded = await session.get(db.Booking, booking.id)
        assert loaded.starts_at == datetime(2099, 5, 20, 14, 30)
        assert loaded.ends_at == datetime(2099, 5, 20, 15, 30)
        assert timeutils.format_slot(loaded.starts_at) == "2099-05-20 14:30"

    async def test_range_query_finds_booking_of_that_day(self, fixture_data):
        """Выборка за день должна находить запись — раньше это делалось через LIKE."""
        from sqlalchemy import select

        session = fixture_data["session"]
        day_start, day_end = timeutils.day_bounds(date(2099, 1, 1))

        found = (await session.execute(
            select(db.Booking).where(
                db.Booking.starts_at >= day_start,
                db.Booking.starts_at < day_end,
            )
        )).scalars().all()

        assert len(found) == 1
        assert found[0].id == fixture_data["booking"].id

    async def test_range_query_excludes_neighbouring_day(self, fixture_data):
        from sqlalchemy import select

        session = fixture_data["session"]
        day_start, day_end = timeutils.day_bounds(date(2099, 1, 2))

        found = (await session.execute(
            select(db.Booking).where(
                db.Booking.starts_at >= day_start,
                db.Booking.starts_at < day_end,
            )
        )).scalars().all()

        assert found == []
