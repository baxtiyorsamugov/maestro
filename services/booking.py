"""
Расчёт свободного времени.

Главная бизнес-логика продукта: какое расписание действует на дату, какие слоты
свободны, пересекается ли новая бронь с существующими. Ничего не отправляет
пользователю и не знает про aiogram — поэтому целиком покрыта тестами.
"""
import calendar as calendar_module
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import joinedload

import database as db
import timeutils
from database import ACTIVE_BOOKING_STATUSES, BOOKING_DECLINED
from services.access import is_stylist_subscription_active


async def get_effective_schedule_for_date(session, stylist_id: int, selected_date):
    special_schedule = await session.scalar(
        select(db.SpecialSchedule).where(
            db.SpecialSchedule.stylist_id == stylist_id,
            db.SpecialSchedule.work_date == selected_date,
        )
    )
    if special_schedule:
        if special_schedule.is_day_off or not (special_schedule.start_time and special_schedule.end_time):
            return None, special_schedule
        return special_schedule, special_schedule

    weekly_schedule = await session.scalar(
        select(db.Schedule).where(db.Schedule.stylist_id == stylist_id, db.Schedule.day_of_week == selected_date.isoweekday())
    )
    return weekly_schedule, special_schedule

async def load_special_dates(session, stylist_id: int) -> list[db.SpecialSchedule]:
    return (await session.execute(
        select(db.SpecialSchedule)
        .where(db.SpecialSchedule.stylist_id == stylist_id)
        .order_by(db.SpecialSchedule.work_date)
    )).scalars().all()

def get_time_bounds(start_time: str, end_time: str):
    return datetime.strptime(start_time, "%H:%M"), datetime.strptime(end_time, "%H:%M")

def slot_overlaps_existing(slot_start: datetime, service_duration_min: int, bookings: list[db.Booking]) -> bool:
    slot_end = slot_start + timedelta(minutes=service_duration_min)
    for booking in bookings:
        if booking.status == BOOKING_DECLINED:
            continue
        if slot_start < booking.ends_at and slot_end > booking.starts_at:
            return True
    return False

def calculate_available_slots(selected_date, schedule, service_duration_min: int, bookings: list[db.Booking]):
    available_slots = []
    start_time, end_time = get_time_bounds(schedule.start_time, schedule.end_time)
    current_time = start_time
    now = timeutils.now()

    while current_time < end_time:
        slot_datetime = datetime.combine(selected_date, current_time.time())
        slot_end = slot_datetime + timedelta(minutes=service_duration_min)
        if slot_end <= datetime.combine(selected_date, end_time.time()):
            if slot_datetime > now and not slot_overlaps_existing(slot_datetime, service_duration_min, bookings):
                available_slots.append(current_time.strftime("%H:%M"))
        current_time += timedelta(minutes=service_duration_min)

    return available_slots

async def get_available_slots_for_date(session, stylist_id: int, service_id: int, selected_date):
    schedule, _ = await get_effective_schedule_for_date(session, stylist_id, selected_date)
    if not schedule:
        return None, []

    service = await session.get(db.Service, service_id)
    if not service:
        return schedule, []

    day_start, day_end = timeutils.day_bounds(selected_date)
    bookings = (await session.execute(
        select(db.Booking)
        .where(
            db.Booking.stylist_id == stylist_id,
            db.Booking.starts_at >= day_start,
            db.Booking.starts_at < day_end,
            db.Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
    )).scalars().all()

    return schedule, calculate_available_slots(selected_date, schedule, service.duration_min, bookings)

def resolve_schedule_for_date(
    selected_date,
    weekly_by_day: dict[int, db.Schedule],
    special_by_date: dict,
):
    """
    Какое расписание действует на дату: персональное исключение важнее недельного.
    Чистая функция — вся выборка из базы делается вызывающим кодом одним разом.
    """
    special = special_by_date.get(selected_date)
    if special:
        if special.is_day_off or not (special.start_time and special.end_time):
            return None
        return special
    return weekly_by_day.get(selected_date.isoweekday())

async def get_available_dates_for_month(session, stylist_id: int, service_id: int, year: int, month: int):
    """
    Даты месяца, где у мастера есть хотя бы один свободный слот.

    Раньше здесь был запрос на каждый день месяца (около 124 запросов на один
    показ календаря). Теперь всё нужное забирается четырьмя запросами,
    а пересечения считаются в памяти.
    """

    service = await session.get(db.Service, service_id)
    if not service:
        return []

    first_day = date(year, month, 1)
    last_day = date(year, month, calendar_module.monthrange(year, month)[1])
    today = timeutils.today()

    weekly_schedules = (await session.execute(
        select(db.Schedule).where(db.Schedule.stylist_id == stylist_id)
    )).scalars().all()
    weekly_by_day = {schedule.day_of_week: schedule for schedule in weekly_schedules}

    special_schedules = (await session.execute(
        select(db.SpecialSchedule).where(
            db.SpecialSchedule.stylist_id == stylist_id,
            db.SpecialSchedule.work_date >= first_day,
            db.SpecialSchedule.work_date <= last_day,
        )
    )).scalars().all()
    special_by_date = {schedule.work_date: schedule for schedule in special_schedules}

    month_start, month_end = timeutils.range_bounds(first_day, last_day)
    month_bookings = (await session.execute(
        select(db.Booking)
        .where(
            db.Booking.stylist_id == stylist_id,
            db.Booking.starts_at >= month_start,
            db.Booking.starts_at < month_end,
            db.Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
    )).scalars().all()

    bookings_by_date: dict = {}
    for booking in month_bookings:
        bookings_by_date.setdefault(booking.starts_at.date(), []).append(booking)

    result = []
    for day in range(1, last_day.day + 1):
        current_date = date(year, month, day)
        if current_date < today:
            continue
        schedule = resolve_schedule_for_date(current_date, weekly_by_day, special_by_date)
        if not schedule:
            continue
        slots = calculate_available_slots(
            current_date,
            schedule,
            service.duration_min,
            bookings_by_date.get(current_date, []),
        )
        if slots:
            result.append(current_date)

    return result


async def get_last_booking_for_repeat(session, user_id: int) -> db.Booking | None:
    """
    Последняя запись клиента, которую имеет смысл повторить.

    Отсекаем случаи, когда кнопка привела бы в тупик: мастер закрыт по тарифу
    или услуга удалена. Лучше не показывать кнопку, чем показать неработающую.
    """
    booking = await session.scalar(
        select(db.Booking)
        .join(db.Stylist, db.Stylist.id == db.Booking.stylist_id)
        .join(db.Service, db.Service.id == db.Booking.service_id)
        .where(db.Booking.user_id == user_id)
        .options(
            joinedload(db.Booking.stylist).joinedload(db.Stylist.user_account),
            joinedload(db.Booking.service).joinedload(db.Service.catalog_service),
        )
        .order_by(db.Booking.starts_at.desc())
        .limit(1)
    )
    if not booking or not booking.stylist or not booking.service:
        return None
    if not is_stylist_subscription_active(booking.stylist.user_account):
        return None
    return booking
