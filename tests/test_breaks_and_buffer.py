"""
Тесты перерыва в расписании и буфера между записями (docs/ROADMAP.md, Фаза 4).

Слоты шли вплотную: мастер физически не успевал убрать за клиентом, а обед
приходилось закрывать особой датой на каждый день.

Здесь два правила, и оба легко сделать неправильно.

1. Буфер должен менять шаг сетки, а не только занятость. Иначе при часовой
   услуге и буфере 15 минут запись в 10:00 закрывала бы и 11:00, хотя мастер
   свободен с 11:15 — буфер съедал бы целый слот вместо четверти.
2. После перерыва сетка обязана начинаться заново от его конца. Иначе обед
   13:00-13:30 отнимал бы у мастера полчаса, которые некуда деть.

Отдельно проверяется, что значение по умолчанию (буфера нет, перерыва нет)
оставляет расчёт ровно таким, каким он был до этой задачи.
"""
from datetime import date, timedelta

import database as db
import timeutils
from services.booking import (
    BUFFER_CHOICES,
    calculate_available_slots,
    get_break_bounds,
    get_stylist_buffer,
    slot_overlaps_existing,
)


class FakeSchedule:
    """Расписание как простой объект: считать слоты можно и без базы."""

    def __init__(self, start_time, end_time, break_start=None, break_end=None):
        self.start_time = start_time
        self.end_time = end_time
        self.break_start = break_start
        self.break_end = break_end


def _future_date() -> date:
    """Дата заведомо в будущем: прошедшие слоты расчёт отбрасывает."""
    return timeutils.today() + timedelta(days=30)


def _booking(day: date, start: str, duration_min: int = 60) -> db.Booking:
    starts_at = timeutils.parse_slot(f"{day:%Y-%m-%d} {start}")
    return db.Booking(
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=duration_min),
        status=db.BOOKING_APPROVED,
    )


class TestNothingChangesByDefault:
    """Мастера, которые ничего не настраивали, не должны заметить изменений."""

    def test_grid_without_buffer_is_hourly(self):
        day = _future_date()
        slots = calculate_available_slots(day, FakeSchedule("10:00", "14:00"), 60, [])

        assert slots == ["10:00", "11:00", "12:00", "13:00"]

    def test_booking_blocks_exactly_its_own_slot(self):
        day = _future_date()
        slots = calculate_available_slots(
            day, FakeSchedule("10:00", "14:00"), 60, [_booking(day, "11:00")]
        )

        assert slots == ["10:00", "12:00", "13:00"]

    def test_adjacent_slot_stays_free_without_buffer(self):
        """Без буфера записи идут вплотную — это прежнее поведение."""
        day = _future_date()
        slots = calculate_available_slots(
            day, FakeSchedule("10:00", "13:00"), 60, [_booking(day, "10:00")], 0
        )

        assert "11:00" in slots


class TestBuffer:
    def test_grid_step_includes_buffer(self):
        """
        Главное в буфере: он двигает сетку, а не просто вычёркивает слоты.
        При шаге в 60 минут вместо 75 мастер терял бы целый час вместо 15 минут.
        """
        day = _future_date()
        slots = calculate_available_slots(day, FakeSchedule("10:00", "14:00"), 60, [], 15)

        assert slots == ["10:00", "11:15", "12:30"]

    def test_buffer_blocks_time_after_booking(self):
        day = _future_date()
        slots = calculate_available_slots(
            day, FakeSchedule("10:00", "18:00"), 60, [_booking(day, "11:15")], 15
        )

        assert "10:00" in slots, "запись в 11:15 не должна мешать слоту 10:00-11:00"
        assert "11:15" not in slots

    def test_buffer_blocks_time_before_booking(self):
        """
        Буфер нужен с обеих сторон: перед следующим клиентом тоже.
        Слот 10:30-11:30 вплотную упирается в запись на 11:30 — значит занят.
        """
        day = _future_date()
        booking = _booking(day, "11:30")

        assert slot_overlaps_existing(
            timeutils.parse_slot(f"{day:%Y-%m-%d} 10:30"), 60, [booking], 15
        ) is True
        assert slot_overlaps_existing(
            timeutils.parse_slot(f"{day:%Y-%m-%d} 10:30"), 60, [booking], 0
        ) is False

    def test_declined_booking_does_not_reserve_buffer(self):
        """Отклонённая заявка не занимает ни слот, ни буфер вокруг него."""
        day = _future_date()
        declined = _booking(day, "11:00")
        declined.status = db.BOOKING_DECLINED

        assert slot_overlaps_existing(
            timeutils.parse_slot(f"{day:%Y-%m-%d} 11:00"), 60, [declined], 30
        ) is False

    def test_last_slot_fits_even_though_buffer_does_not(self):
        """
        Буфер после последнего клиента в день никому не мешает: за ним
        никого нет. Слот 13:00-14:00 при закрытии в 14:00 должен остаться.
        """
        day = _future_date()
        slots = calculate_available_slots(day, FakeSchedule("10:00", "14:00"), 60, [], 30)

        assert slots[-1] == "13:00"


class TestBreak:
    def test_slots_skip_the_break(self):
        day = _future_date()
        slots = calculate_available_slots(
            day, FakeSchedule("10:00", "16:00", "13:00", "14:00"), 60, []
        )

        assert slots == ["10:00", "11:00", "12:00", "14:00", "15:00"]

    def test_grid_restarts_after_the_break(self):
        """
        Получасовой обед не должен стоить мастеру часа. После перерыва
        сетка начинается заново от его конца: 13:30, а не 14:00.
        """
        day = _future_date()
        slots = calculate_available_slots(
            day, FakeSchedule("10:00", "16:00", "13:00", "13:30"), 60, []
        )

        assert slots == ["10:00", "11:00", "12:00", "13:30", "14:30"]

    def test_slot_overlapping_break_start_is_dropped(self):
        """Слот 12:30-13:30 залезает на обед — предлагать его нельзя."""
        day = _future_date()
        slots = calculate_available_slots(
            day, FakeSchedule("10:30", "16:00", "13:00", "14:00"), 60, []
        )

        assert "12:30" not in slots
        assert "14:00" in slots

    def test_break_covering_whole_day_leaves_nothing(self):
        day = _future_date()
        slots = calculate_available_slots(
            day, FakeSchedule("10:00", "14:00", "10:00", "14:00"), 60, []
        )

        assert slots == []

    def test_break_and_buffer_work_together(self):
        day = _future_date()
        slots = calculate_available_slots(
            day, FakeSchedule("10:00", "17:00", "13:00", "14:00"), 60, [], 15
        )

        assert slots == ["10:00", "11:15", "14:00", "15:15"]


class TestBreakBounds:
    """
    Половинчатый перерыв — это данные, которых быть не должно, но они могут
    появиться после ручной правки базы. Расчёт обязан их пережить.
    """

    def test_full_pair_is_parsed(self):
        bounds = get_break_bounds(FakeSchedule("10:00", "18:00", "13:00", "14:00"))

        assert bounds is not None
        assert bounds[0].strftime("%H:%M") == "13:00"

    def test_half_filled_break_is_ignored(self):
        assert get_break_bounds(FakeSchedule("10:00", "18:00", "13:00", None)) is None
        assert get_break_bounds(FakeSchedule("10:00", "18:00", None, "14:00")) is None

    def test_garbage_does_not_crash(self):
        assert get_break_bounds(FakeSchedule("10:00", "18:00", "обед", "14:00")) is None

    def test_schedule_without_break_columns_is_fine(self):
        """SpecialSchedule перерыва не имеет — getattr не должен падать."""
        special = db.SpecialSchedule(start_time="10:00", end_time="18:00")

        assert get_break_bounds(special) is None

    def test_half_filled_break_leaves_the_day_working(self):
        """
        Осознанный выбор: недонастроенный перерыв игнорируется, а не съедает
        полдня. Молча потерять рабочее время хуже, чем не заметить обед.
        """
        day = _future_date()
        slots = calculate_available_slots(
            day, FakeSchedule("10:00", "13:00", "11:00", None), 60, []
        )

        assert slots == ["10:00", "11:00", "12:00"]


class TestStylistBuffer:
    async def test_default_is_zero(self, fixture_data):
        value = await get_stylist_buffer(fixture_data["session"], fixture_data["stylist"].id)

        assert value == 0

    async def test_saved_value_is_returned(self, fixture_data):
        session = fixture_data["session"]
        fixture_data["stylist"].buffer_min = 15
        await session.commit()

        assert await get_stylist_buffer(session, fixture_data["stylist"].id) == 15

    async def test_missing_stylist_gives_zero(self, fixture_data):
        """Удалённый мастер не должен ронять расчёт слотов."""
        assert await get_stylist_buffer(fixture_data["session"], 999999) == 0

    async def test_buffer_reaches_slot_calculation(self, fixture_data):
        """
        Связка целиком: значение из базы должно доехать до сетки слотов.
        Настройка, которая сохранилась, но не применяется, — худший вид бага:
        мастер уверен, что перерыв есть, а клиенты записываются вплотную.
        """
        from services.booking import get_available_slots_for_date

        session = fixture_data["session"]
        day = _future_date()
        session.add(db.Schedule(
            stylist_id=fixture_data["stylist"].id,
            day_of_week=day.isoweekday(),
            start_time="10:00",
            end_time="14:00",
        ))
        fixture_data["stylist"].buffer_min = 15
        await session.commit()

        _, slots = await get_available_slots_for_date(
            session, fixture_data["stylist"].id, fixture_data["service"].id, day
        )

        assert slots == ["10:00", "11:15", "12:30"]

    async def test_break_reaches_slot_calculation(self, fixture_data):
        from services.booking import get_available_slots_for_date

        session = fixture_data["session"]
        day = _future_date()
        session.add(db.Schedule(
            stylist_id=fixture_data["stylist"].id,
            day_of_week=day.isoweekday(),
            start_time="10:00",
            end_time="16:00",
            break_start="13:00",
            break_end="14:00",
        ))
        await session.commit()

        _, slots = await get_available_slots_for_date(
            session, fixture_data["stylist"].id, fixture_data["service"].id, day
        )

        assert slots == ["10:00", "11:00", "12:00", "14:00", "15:00"]

    async def test_break_hides_day_from_calendar_when_nothing_is_left(self, fixture_data):
        from services.booking import get_available_dates_for_month

        session = fixture_data["session"]
        day = _future_date()
        session.add(db.Schedule(
            stylist_id=fixture_data["stylist"].id,
            day_of_week=day.isoweekday(),
            start_time="10:00",
            end_time="12:00",
            break_start="10:00",
            break_end="12:00",
        ))
        await session.commit()

        available = await get_available_dates_for_month(
            session, fixture_data["stylist"].id, fixture_data["service"].id, day.year, day.month
        )

        assert day not in available


class TestBufferChoices:
    def test_zero_is_offered(self):
        """Без нуля буфер нельзя выключить обратно."""
        assert 0 in BUFFER_CHOICES

    def test_choices_are_sorted_and_unique(self):
        assert list(BUFFER_CHOICES) == sorted(set(BUFFER_CHOICES))
