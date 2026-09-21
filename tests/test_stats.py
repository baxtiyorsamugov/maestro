"""
Статистика мастера (services/stats.py, presenters.build_stats_report).

Старый отчёт ошибался в двух местах, которые здесь закреплены:
«последние 7 дней» были восемью, а в доход шли визиты, которые ещё
не состоялись.
"""
from datetime import date, timedelta

import pytest

import database as db
import presenters
import timeutils
from services import stats
from test_scenarios import _open_workday, person, world  # noqa: F401 — фикстура world

TODAY = date(2030, 5, 15)
CYRILLIC = __import__("re").compile(r"[а-яА-ЯёЁ]")


class TestPeriods:
    def test_week_is_seven_days_including_today(self):
        start, end = stats.period_bounds("7", TODAY)
        assert (end - start).days == 7
        assert start == date(2030, 5, 9)
        assert end == date(2030, 5, 16)

    def test_yesterday_ends_at_today(self):
        assert stats.period_bounds("yesterday", TODAY) == (date(2030, 5, 14), TODAY)

    def test_previous_period_is_same_length_right_before(self):
        start, end = stats.period_bounds("30", TODAY)
        prev_start, prev_end = stats.previous_bounds(start, end)
        assert prev_end == start
        assert (prev_end - prev_start) == (end - start)

    @pytest.mark.parametrize(
        ("current", "previous", "expected"),
        [(12, 10, 20), (8, 10, -20), (10, 10, 0), (5, 0, None), (0, 0, None)],
    )
    def test_change_percent(self, current, previous, expected):
        assert stats.change_percent(current, previous) == expected


async def _add(fixture_data, day: date, hour: int, status: str, user=None, guest=False):
    starts_at = timeutils.combine(day, f"{hour:02d}:00")
    booking = db.Booking(
        user_id=None if guest else (user or fixture_data["client_user"]).id,
        guest_name="Гость" if guest else None,
        stylist_id=fixture_data["stylist"].id,
        service_id=fixture_data["service"].id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        status=status,
    )
    fixture_data["session"].add(booking)
    await fixture_data["session"].flush()
    return booking


async def _clear(fixture_data):
    """Убираем заявку из фикстуры: она в 2099 году и в окно не попадает, но пусть не путает."""
    session = fixture_data["session"]
    await session.delete(fixture_data["booking"])
    await session.flush()


class TestCollect:
    async def test_earned_and_expected_are_separate(self, fixture_data):
        """Подтверждённый, но не состоявшийся визит — это план, а не доход."""
        await _clear(fixture_data)
        await _add(fixture_data, TODAY - timedelta(days=1), 10, db.BOOKING_COMPLETED)
        await _add(fixture_data, TODAY, 18, db.BOOKING_APPROVED)
        await fixture_data["session"].commit()

        report = await stats.collect(fixture_data["session"], fixture_data["stylist"].id, "7", TODAY)

        price = fixture_data["service"].price
        assert report.current.earned == price
        assert report.current.expected == price
        assert report.current.total == 2

    async def test_eighth_day_is_not_in_the_week(self, fixture_data):
        await _clear(fixture_data)
        await _add(fixture_data, TODAY - timedelta(days=7), 12, db.BOOKING_COMPLETED)
        await fixture_data["session"].commit()

        report = await stats.collect(fixture_data["session"], fixture_data["stylist"].id, "7", TODAY)

        assert report.current.total == 0, "восьмой день попал в «последние 7 дней»"
        assert report.previous.completed == 1

    async def test_lost_bookings_not_in_total_or_load(self, fixture_data):
        await _clear(fixture_data)
        await _add(fixture_data, TODAY, 11, db.BOOKING_CANCELLED)
        await _add(fixture_data, TODAY, 12, db.BOOKING_DECLINED)
        await _add(fixture_data, TODAY, 13, db.BOOKING_PENDING)
        await fixture_data["session"].commit()

        report = await stats.collect(fixture_data["session"], fixture_data["stylist"].id, "today", TODAY)

        assert (report.current.cancelled, report.current.declined) == (1, 1)
        assert report.current.total == 1
        assert report.current.peak_hours == [(13, 1)]

    async def test_returning_clients_and_guests(self, fixture_data):
        await _clear(fixture_data)
        session = fixture_data["session"]
        newcomer = db.User(telegram_id=5005, first_name="Новый", phone_number="+998900000005")
        session.add(newcomer)
        await session.flush()

        # Постоянный клиент был в прошлом месяце, новичок — впервые.
        await _add(fixture_data, TODAY - timedelta(days=40), 10, db.BOOKING_COMPLETED)
        await _add(fixture_data, TODAY, 10, db.BOOKING_APPROVED)
        await _add(fixture_data, TODAY, 11, db.BOOKING_APPROVED, user=newcomer)
        await _add(fixture_data, TODAY, 12, db.BOOKING_APPROVED, guest=True)
        await session.commit()

        report = await stats.collect(session, fixture_data["stylist"].id, "7", TODAY)

        assert report.current.clients == 2
        assert report.current.returning_clients == 1
        assert report.current.guests == 1

    async def test_peak_hours_ordered_by_load(self, fixture_data):
        await _clear(fixture_data)
        for day in range(3):
            await _add(fixture_data, TODAY - timedelta(days=day), 18, db.BOOKING_COMPLETED)
        await _add(fixture_data, TODAY, 10, db.BOOKING_COMPLETED)
        await fixture_data["session"].commit()

        report = await stats.collect(fixture_data["session"], fixture_data["stylist"].id, "7", TODAY)

        assert report.current.peak_hours[0] == (18, 3)

    async def test_other_stylists_bookings_not_counted(self, fixture_data):
        await _clear(fixture_data)
        await _add(fixture_data, TODAY, 10, db.BOOKING_COMPLETED)
        await fixture_data["session"].commit()

        report = await stats.collect(fixture_data["session"], fixture_data["stylist"].id + 999, "7", TODAY)

        assert report.current.total == 0


def _report(**current):
    return stats.StatsReport(current=stats.PeriodStats(**current), previous=stats.PeriodStats())


class TestPresenter:
    def test_uzbek_report_has_no_russian(self):
        report = stats.StatsReport(
            current=stats.PeriodStats(
                completed=8, approved=2, pending=1, cancelled=1, earned=800_000,
                expected=200_000, clients=9, returning_clients=4, guests=1,
                peak_hours=[(18, 4), (17, 3)],
            ),
            previous=stats.PeriodStats(completed=6, earned=600_000),
        )
        text = presenters.build_stats_report(report, "oxirgi 7 kun", "uz")
        assert not CYRILLIC.search(text), text
        assert "800 000" in text
        assert "↑" in text

    def test_empty_period_says_so(self):
        text = presenters.build_stats_report(_report(), "сегодня", "ru")
        assert "записей нет" in text

    def test_zero_lines_are_omitted(self):
        text = presenters.build_stats_report(_report(completed=1, earned=100), "сегодня", "ru")
        assert "отменено" not in text
        assert "Ожидается" not in text

    def test_no_percent_when_previous_was_zero(self):
        """«+∞%» человеку ничего не скажет — лучше промолчать."""
        text = presenters.build_stats_report(_report(completed=3, earned=300), "сегодня", "ru")
        assert "%" not in text


class TestThroughDispatcher:
    async def test_report_has_period_switch_and_way_back(self, world, fixture_data):  # noqa: F811
        await _open_workday(fixture_data)
        stylist = person(world, fixture_data["stylist_user"].telegram_id, "Мастер")

        replies = await stylist.press("stats_7")

        assert replies.answered_callback
        callbacks = replies.callbacks()
        assert "stats_menu" in callbacks, "экран отчёта — тупик"
        assert {"stats_today", "stats_30"} <= set(callbacks)

        back = await stylist.press("stats_menu")
        assert "stats_7" in back.callbacks()

    async def test_old_button_still_works(self, world, fixture_data):  # noqa: F811
        """В чатах остались сообщения со старой кнопкой «stats_7_days»."""
        await _open_workday(fixture_data)
        stylist = person(world, fixture_data["stylist_user"].telegram_id, "Мастер")

        replies = await stylist.press("stats_7_days")

        assert replies.texts and "stats_menu" in replies.callbacks()
