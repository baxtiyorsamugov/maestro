"""
Тесты подбора свободных дат месяца.

Раньше get_available_dates_for_month делал запрос на каждый день месяца
(~124 запроса на один показ календаря). Теперь выборка пакетная, а пересечения
считаются в памяти — поведение должно остаться прежним.
"""
from datetime import date, timedelta

import bot
import database as db


def _future_month() -> tuple[int, int]:
    """Месяц целиком в будущем, чтобы прошедшие дни не отфильтровывались."""
    target = date.today().replace(day=1) + timedelta(days=62)
    return target.year, target.month


async def _add_weekly_schedule(session, stylist_id: int, start="09:00", end="18:00"):
    for day_of_week in range(1, 8):
        session.add(
            db.Schedule(
                stylist_id=stylist_id,
                day_of_week=day_of_week,
                start_time=start,
                end_time=end,
            )
        )
    await session.commit()


class TestAvailableDates:
    async def test_no_schedule_means_no_dates(self, fixture_data):
        year, month = _future_month()
        dates = await bot.get_available_dates_for_month(
            fixture_data["session"], fixture_data["stylist"].id, fixture_data["service"].id, year, month
        )
        assert dates == []

    async def test_full_week_schedule_opens_every_day(self, fixture_data):
        session = fixture_data["session"]
        await _add_weekly_schedule(session, fixture_data["stylist"].id)

        year, month = _future_month()
        dates = await bot.get_available_dates_for_month(
            session, fixture_data["stylist"].id, fixture_data["service"].id, year, month
        )
        assert len(dates) >= 28
        assert all(d.month == month and d.year == year for d in dates)

    async def test_day_off_is_excluded(self, fixture_data):
        session = fixture_data["session"]
        await _add_weekly_schedule(session, fixture_data["stylist"].id)

        year, month = _future_month()
        day_off = date(year, month, 15)
        session.add(
            db.SpecialSchedule(
                stylist_id=fixture_data["stylist"].id,
                work_date=day_off,
                is_day_off=True,
            )
        )
        await session.commit()

        dates = await bot.get_available_dates_for_month(
            session, fixture_data["stylist"].id, fixture_data["service"].id, year, month
        )
        assert day_off not in dates

    async def test_special_hours_override_weekly(self, fixture_data):
        """Персональные часы важнее недельного расписания."""
        session = fixture_data["session"]
        await _add_weekly_schedule(session, fixture_data["stylist"].id)

        year, month = _future_month()
        short_day = date(year, month, 16)
        session.add(
            db.SpecialSchedule(
                stylist_id=fixture_data["stylist"].id,
                work_date=short_day,
                start_time="10:00",
                end_time="11:00",
                is_day_off=False,
            )
        )
        await session.commit()

        # Услуга длится 60 минут — ровно один слот 10:00 помещается.
        dates = await bot.get_available_dates_for_month(
            session, fixture_data["stylist"].id, fixture_data["service"].id, year, month
        )
        assert short_day in dates

    async def test_fully_booked_day_is_excluded(self, fixture_data):
        session = fixture_data["session"]
        await _add_weekly_schedule(session, fixture_data["stylist"].id, start="10:00", end="11:00")

        year, month = _future_month()
        busy_day = date(year, month, 17)
        session.add(
            db.Booking(
                user_id=fixture_data["client_user"].id,
                stylist_id=fixture_data["stylist"].id,
                service_id=fixture_data["service"].id,
                datetime=f"{busy_day.strftime('%Y-%m-%d')} 10:00",
                status=db.BOOKING_APPROVED,
            )
        )
        await session.commit()

        dates = await bot.get_available_dates_for_month(
            session, fixture_data["stylist"].id, fixture_data["service"].id, year, month
        )
        assert busy_day not in dates

    async def test_declined_booking_frees_the_day(self, fixture_data):
        session = fixture_data["session"]
        await _add_weekly_schedule(session, fixture_data["stylist"].id, start="10:00", end="11:00")

        year, month = _future_month()
        day = date(year, month, 18)
        session.add(
            db.Booking(
                user_id=fixture_data["client_user"].id,
                stylist_id=fixture_data["stylist"].id,
                service_id=fixture_data["service"].id,
                datetime=f"{day.strftime('%Y-%m-%d')} 10:00",
                status=db.BOOKING_DECLINED,
            )
        )
        await session.commit()

        dates = await bot.get_available_dates_for_month(
            session, fixture_data["stylist"].id, fixture_data["service"].id, year, month
        )
        assert day in dates

    async def test_past_days_are_skipped(self, fixture_data):
        session = fixture_data["session"]
        await _add_weekly_schedule(session, fixture_data["stylist"].id)

        today = date.today()
        dates = await bot.get_available_dates_for_month(
            session, fixture_data["stylist"].id, fixture_data["service"].id, today.year, today.month
        )
        assert all(d >= today for d in dates)

    async def test_missing_service_returns_empty(self, fixture_data):
        year, month = _future_month()
        dates = await bot.get_available_dates_for_month(
            fixture_data["session"], fixture_data["stylist"].id, 999999, year, month
        )
        assert dates == []


class TestResolveSchedule:
    def test_special_day_off_wins_over_weekly(self):
        weekly = {1: db.Schedule(day_of_week=1, start_time="09:00", end_time="18:00")}
        day = date(2099, 1, 5)  # понедельник
        special = {day: db.SpecialSchedule(work_date=day, is_day_off=True)}

        assert bot.resolve_schedule_for_date(day, weekly, special) is None

    def test_special_without_hours_is_treated_as_day_off(self):
        day = date(2099, 1, 5)
        weekly = {1: db.Schedule(day_of_week=1, start_time="09:00", end_time="18:00")}
        special = {day: db.SpecialSchedule(work_date=day, is_day_off=False, start_time=None, end_time=None)}

        assert bot.resolve_schedule_for_date(day, weekly, special) is None

    def test_falls_back_to_weekly(self):
        day = date(2099, 1, 5)
        weekly_schedule = db.Schedule(day_of_week=1, start_time="09:00", end_time="18:00")

        assert bot.resolve_schedule_for_date(day, {1: weekly_schedule}, {}) is weekly_schedule

    def test_no_schedule_at_all(self):
        assert bot.resolve_schedule_for_date(date(2099, 1, 5), {}, {}) is None
