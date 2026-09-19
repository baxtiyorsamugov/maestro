"""
Тесты переноса записи (docs/ROADMAP.md, Фаза 4).

Раньше клиент, которому не подошло время, был вынужден отменить визит и
записаться заново. В промежутке между двумя действиями слот становился
свободным для всех — и мог уйти другому человеку, пока клиент листал календарь.

Перенос двигает ту же самую бронь: старое время держится до последнего.
Отсюда два правила, которые здесь и проверяются.

1. Переносимая запись не должна считаться занятостью для самой себя. Иначе
   клиент не увидит ни своё текущее время, ни соседние слоты, которые его же
   бронь перекрывает длительностью услуги.
2. Менять запись можно не в любой момент: за CHANGE_WINDOW_HOURS до визита
   мастер уже построил на неё день.
"""
from datetime import timedelta

import database as db
import timeutils
from services.booking import (
    CHANGE_WINDOW_HOURS,
    can_change_booking,
    exclude_booking,
    get_available_dates_for_month,
    get_available_slots_for_date,
)


async def _workday(fixture_data, day_of_week: int) -> None:
    """Расписание мастера на нужный день недели: 10:00-18:00."""
    session = fixture_data["session"]
    session.add(db.Schedule(
        stylist_id=fixture_data["stylist"].id,
        day_of_week=day_of_week,
        start_time="10:00",
        end_time="18:00",
    ))
    await session.commit()


async def _booking_at(fixture_data, slot: str, status: str = db.BOOKING_PENDING) -> db.Booking:
    session = fixture_data["session"]
    starts_at = timeutils.parse_slot(slot)
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


class TestChangeWindow:
    """Окно, внутри которого запись ещё можно трогать."""

    def test_far_booking_can_be_changed(self):
        now = timeutils.now()
        booking = db.Booking(starts_at=now + timedelta(days=3), status=db.BOOKING_PENDING)

        allowed, reason = can_change_booking(booking, now=now)

        assert allowed is True
        assert reason is None

    def test_booking_inside_window_is_locked(self):
        now = timeutils.now()
        booking = db.Booking(
            starts_at=now + timedelta(hours=CHANGE_WINDOW_HOURS) - timedelta(minutes=1),
            status=db.BOOKING_PENDING,
        )

        allowed, reason = can_change_booking(booking, now=now)

        assert allowed is False
        assert reason == "change_denied_too_late"

    def test_boundary_is_inclusive(self):
        """Ровно CHANGE_WINDOW_HOURS до визита — ещё можно."""
        now = timeutils.now()
        booking = db.Booking(
            starts_at=now + timedelta(hours=CHANGE_WINDOW_HOURS),
            status=db.BOOKING_PENDING,
        )

        assert can_change_booking(booking, now=now)[0] is True

    def test_past_booking_is_locked(self):
        now = timeutils.now()
        booking = db.Booking(starts_at=now - timedelta(hours=1), status=db.BOOKING_APPROVED)

        assert can_change_booking(booking, now=now)[0] is False

    def test_approved_booking_can_be_changed(self):
        """Подтверждённую мастером запись клиент тоже вправе перенести."""
        now = timeutils.now()
        booking = db.Booking(starts_at=now + timedelta(days=1), status=db.BOOKING_APPROVED)

        assert can_change_booking(booking, now=now)[0] is True

    def test_closed_statuses_are_locked(self):
        now = timeutils.now()
        for status in (db.BOOKING_CANCELLED, db.BOOKING_DECLINED, db.BOOKING_COMPLETED):
            booking = db.Booking(starts_at=now + timedelta(days=3), status=status)

            allowed, reason = can_change_booking(booking, now=now)

            assert allowed is False, f"статус {status} не должен позволять перенос"
            assert reason == "change_denied_closed"

    def test_reason_key_exists_in_both_languages(self):
        """
        Сервис возвращает ключ texts.py, а не готовую строку. Ключа может
        не оказаться в словаре — тогда клиент увидит сам ключ вместо текста.
        """
        import texts

        for key in ("change_denied_closed", "change_denied_too_late"):
            for lang in ("ru", "uz"):
                assert texts.get_text(key, lang) != key, f"{key}/{lang} не переведён"

    def test_too_late_text_has_hours_placeholder(self):
        """Шаблон форматируется с hours — без плейсхолдера число потеряется."""
        import texts

        for lang in ("ru", "uz"):
            rendered = texts.get_text("change_denied_too_late", lang).format(
                hours=CHANGE_WINDOW_HOURS
            )
            assert str(CHANGE_WINDOW_HOURS) in rendered


class TestExcludeBooking:
    def test_none_keeps_list_untouched(self, fixture_data):
        bookings = [fixture_data["booking"]]

        assert exclude_booking(bookings, None) is bookings

    def test_named_booking_is_removed(self, fixture_data):
        booking = fixture_data["booking"]

        assert exclude_booking([booking], booking.id) == []

    def test_other_bookings_survive(self, fixture_data):
        booking = fixture_data["booking"]
        other = db.Booking(id=booking.id + 1)

        assert exclude_booking([booking, other], booking.id) == [other]


class TestSlotsDuringReschedule:
    """
    Клиент двигает свою же бронь: её время должно снова стать выбираемым.

    Без этого перенос выглядел бы сломанным — человек видит в календаре
    меньше вариантов, чем есть, и не понимает, куда делось его собственное время.
    """

    async def test_own_slot_is_offered_back(self, fixture_data):
        session = fixture_data["session"]
        future = timeutils.today() + timedelta(days=7)
        await _workday(fixture_data, future.isoweekday())
        mine = await _booking_at(fixture_data, f"{future:%Y-%m-%d} 12:00")

        _, without_exclusion = await get_available_slots_for_date(
            session, fixture_data["stylist"].id, fixture_data["service"].id, future
        )
        _, with_exclusion = await get_available_slots_for_date(
            session, fixture_data["stylist"].id, fixture_data["service"].id, future,
            exclude_booking_id=mine.id,
        )

        assert "12:00" not in without_exclusion
        assert "12:00" in with_exclusion

    async def test_someone_elses_slot_stays_busy(self, fixture_data):
        """Исключается ровно одна бронь, а не вся занятость дня."""
        session = fixture_data["session"]
        future = timeutils.today() + timedelta(days=7)
        await _workday(fixture_data, future.isoweekday())
        mine = await _booking_at(fixture_data, f"{future:%Y-%m-%d} 12:00")
        await _booking_at(fixture_data, f"{future:%Y-%m-%d} 14:00")

        _, slots = await get_available_slots_for_date(
            session, fixture_data["stylist"].id, fixture_data["service"].id, future,
            exclude_booking_id=mine.id,
        )

        assert "12:00" in slots
        assert "14:00" not in slots

    async def test_day_reappears_in_calendar(self, fixture_data):
        """
        Крайний случай: единственный слот дня занят самим клиентом.
        Без исключения день был бы серым, и до слотов клиент не дошёл бы.
        """
        session = fixture_data["session"]
        future = timeutils.today() + timedelta(days=7)
        session.add(db.Schedule(
            stylist_id=fixture_data["stylist"].id,
            day_of_week=future.isoweekday(),
            start_time="10:00",
            end_time="11:00",  # ровно один часовой слот
        ))
        await session.commit()
        mine = await _booking_at(fixture_data, f"{future:%Y-%m-%d} 10:00")

        without_exclusion = await get_available_dates_for_month(
            session, fixture_data["stylist"].id, fixture_data["service"].id,
            future.year, future.month,
        )
        with_exclusion = await get_available_dates_for_month(
            session, fixture_data["stylist"].id, fixture_data["service"].id,
            future.year, future.month, exclude_booking_id=mine.id,
        )

        assert future not in without_exclusion
        assert future in with_exclusion


class TestSlotGuardStillHolds:
    """
    Перенос двигает существующую строку, а не вставляет новую. Частичный
    уникальный индекс обязан ловить и UPDATE — иначе через перенос можно
    посадить двух клиентов на одно время в обход защиты.
    """

    async def test_moving_onto_a_taken_slot_is_rejected(self, fixture_data):
        from sqlalchemy.exc import IntegrityError

        session = fixture_data["session"]
        taken = await _booking_at(fixture_data, "2099-03-01 12:00")
        mine = await _booking_at(fixture_data, "2099-03-01 15:00")

        mine.starts_at = taken.starts_at
        mine.ends_at = taken.ends_at

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
        else:
            raise AssertionError("перенос на занятое время прошёл мимо uq_active_booking_slot")

    async def test_moving_onto_a_cancelled_slot_is_allowed(self, fixture_data):
        """Индекс частичный: отменённая бронь время не держит."""
        session = fixture_data["session"]
        freed = await _booking_at(fixture_data, "2099-03-02 12:00", status=db.BOOKING_CANCELLED)
        mine = await _booking_at(fixture_data, "2099-03-02 15:00")

        mine.starts_at = freed.starts_at
        mine.ends_at = freed.ends_at
        await session.commit()

        assert mine.starts_at == freed.starts_at
