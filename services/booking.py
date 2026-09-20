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
from database import ACTIVE_BOOKING_STATUSES, BOOKING_APPROVED, BOOKING_DECLINED
from services.access import is_stylist_subscription_active

#: За сколько часов до визита клиент ещё может отменить или перенести запись.
#: Мастер планирует день заранее: отмена за пять минут до прихода — это дыра
#: в расписании, которую уже нечем закрыть. Два часа — компромисс: клиент
#: успевает передумать, мастер успевает предложить слот другому.
CHANGE_WINDOW_HOURS = 2


def can_change_booking(booking: db.Booking, now: datetime | None = None) -> tuple[bool, str | None]:
    """
    Можно ли клиенту отменить или перенести эту запись.

    Возвращает (можно, ключ_причины). Причина — ключ из texts.py, а не готовый
    текст: сервис не знает язык пользователя и не должен знать (CLAUDE.md, 4.5).
    """
    if booking.status not in ACTIVE_BOOKING_STATUSES:
        return False, "change_denied_closed"

    now = now or timeutils.now()
    if booking.starts_at - now < timedelta(hours=CHANGE_WINDOW_HOURS):
        return False, "change_denied_too_late"

    return True, None


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

def exclude_booking(bookings: list[db.Booking], booking_id: int | None) -> list[db.Booking]:
    """
    Убирает из списка занятости саму переносимую запись.

    При переносе клиент двигает свой же визит, и без этого его текущий слот
    (а при длинной услуге — и соседние) показывался бы занятым им самим.
    Человек видел бы меньше вариантов, чем есть на самом деле, и не понимал,
    почему время, которое он вот-вот освободит, выбрать нельзя.
    """
    if booking_id is None:
        return bookings
    return [booking for booking in bookings if booking.id != booking_id]

def slot_overlaps_existing(
    slot_start: datetime,
    service_duration_min: int,
    bookings: list[db.Booking],
    buffer_min: int = 0,
) -> bool:
    """
    Пересекается ли слот с существующими бронями.

    Буфер раздвигает каждую бронь в обе стороны: время нужно и после клиента,
    который уже сидит в кресле, и перед тем, который придёт следующим. Считать
    его на самой брони, а не на слоте, проще — тогда пересечение остаётся
    обычным сравнением двух отрезков.
    """
    slot_end = slot_start + timedelta(minutes=service_duration_min)
    gap = timedelta(minutes=buffer_min)
    for booking in bookings:
        if booking.status == BOOKING_DECLINED:
            continue
        if slot_start < booking.ends_at + gap and slot_end + gap > booking.starts_at:
            return True
    return False


def get_break_bounds(schedule) -> tuple[datetime, datetime] | None:
    """
    Перерыв как пара datetime — или None, если его нет.

    Одна заполненная колонка из двух означает недонастроенный перерыв. Такой
    день считается днём без обеда: молча пропустить полдня расписания хуже,
    чем не заметить перерыв, который мастер не дозадал.
    """
    start_raw = getattr(schedule, "break_start", None)
    end_raw = getattr(schedule, "break_end", None)
    if not (start_raw and end_raw):
        return None
    try:
        return get_time_bounds(start_raw, end_raw)
    except ValueError:
        return None


def calculate_available_slots(
    selected_date,
    schedule,
    service_duration_min: int,
    bookings: list[db.Booking],
    buffer_min: int = 0,
):
    """
    Свободное время мастера на дату.

    Шаг сетки — длительность услуги плюс буфер. Без этого буфер съедал бы
    целый слот: сетка осталась бы часовой, а запись в 10:00 при буфере
    15 минут закрывала бы и 11:00, хотя мастер свободен с 11:15.

    После перерыва сетка начинается заново от его конца, а не продолжает
    утреннюю. Иначе обед 13:00-13:30 при часовых слотах отнимал бы полчаса
    рабочего времени, которое мастеру некуда деть.
    """
    available_slots = []
    start_time, end_time = get_time_bounds(schedule.start_time, schedule.end_time)
    break_bounds = get_break_bounds(schedule)
    current_time = start_time
    step = timedelta(minutes=service_duration_min + buffer_min)
    now = timeutils.now()
    day_end = datetime.combine(selected_date, end_time.time())

    while current_time < end_time:
        slot_datetime = datetime.combine(selected_date, current_time.time())
        slot_end = slot_datetime + timedelta(minutes=service_duration_min)

        if break_bounds:
            break_start = datetime.combine(selected_date, break_bounds[0].time())
            break_end = datetime.combine(selected_date, break_bounds[1].time())
            if slot_datetime < break_end and slot_end > break_start:
                # Упёрлись в обед — переносим сетку на его конец. Условие выше
                # гарантирует slot_datetime < break_end, то есть шаг строго
                # вперёд: зациклиться здесь нельзя.
                current_time = break_bounds[1]
                continue

        if slot_end <= day_end:
            if slot_datetime > now and not slot_overlaps_existing(
                slot_datetime, service_duration_min, bookings, buffer_min
            ):
                available_slots.append(current_time.strftime("%H:%M"))
        current_time += step

    return available_slots

#: Варианты буфера, которые мастер выбирает кнопками. Ввод числа руками
#: не нужен: между «15» и «20» минутами разницы для планирования дня нет,
#: а лишний экран с клавиатурой есть.
BUFFER_CHOICES = (0, 5, 10, 15, 20, 30)


async def get_stylist_buffer(session, stylist_id: int) -> int:
    """Буфер мастера в минутах. У удалённого мастера — ноль, а не падение."""
    buffer_min = await session.scalar(
        select(db.Stylist.buffer_min).where(db.Stylist.id == stylist_id)
    )
    return buffer_min or 0


async def get_available_slots_for_date(
    session, stylist_id: int, service_id: int, selected_date, exclude_booking_id: int | None = None
):
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

    bookings = exclude_booking(bookings, exclude_booking_id)
    buffer_min = await get_stylist_buffer(session, stylist_id)
    return schedule, calculate_available_slots(
        selected_date, schedule, service.duration_min, bookings, buffer_min
    )

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

async def get_available_dates_for_month(
    session, stylist_id: int, service_id: int, year: int, month: int, exclude_booking_id: int | None = None
):
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

    buffer_min = await get_stylist_buffer(session, stylist_id)

    bookings_by_date: dict = {}
    for booking in exclude_booking(month_bookings, exclude_booking_id):
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
            buffer_min,
        )
        if slots:
            result.append(current_date)

    return result


#: Сколько символов имени офлайн-клиента мастер может сохранить.
#: Ограничение колонки — 100; обрезаем на входе, чтобы не ловить ошибку базы
#: после того, как человек уже набрал текст.
GUEST_NAME_MAX_LEN = 100


def normalize_guest_name(raw: str | None) -> str | None:
    """
    Имя офлайн-клиента: без лишних пробелов, не длиннее колонки.

    Пустая строка превращается в None — «занятое время без имени» и
    «время клиента, которого зовут пустотой» должны выглядеть одинаково.
    """
    if not raw:
        return None
    cleaned = " ".join(raw.split())[:GUEST_NAME_MAX_LEN]
    return cleaned or None


def build_offline_booking(
    stylist_id: int,
    service: db.Service,
    starts_at: datetime,
    guest_name: str | None = None,
) -> db.Booking:
    """
    Запись, которую мастер завёл сам.

    Статус сразу approved: подтверждать нечего, мастер и есть тот, кто
    подтверждает. Из этого следует, что такая запись попадает в частичный
    индекс uq_active_booking_slot и честно занимает слот для всех остальных —
    ровно то, ради чего задача и делалась.
    """
    return db.Booking(
        user_id=None,
        stylist_id=stylist_id,
        service_id=service.id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=service.duration_min),
        status=BOOKING_APPROVED,
        guest_name=normalize_guest_name(guest_name),
    )


def is_offline_booking(booking: db.Booking) -> bool:
    """Запись без клиента в Telegram: уведомлять и напоминать некому."""
    return booking.user_id is None


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
