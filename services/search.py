"""
Подбор мастера: факты для списка и сортировка.

Список мастеров в салоне показывал только имена. Чтобы понять, кто дороже,
у кого рейтинг выше и кто освободится раньше, приходилось открывать карточки
по одной и возвращаться назад. Обычно человек так не делает — он жмёт первого
в списке или уходит.

Теперь рядом с именем стоят три факта, по которым и выбирают: рейтинг, цена
«от» и ближайшее свободное время. По ним же работает сортировка.

Про цену запросов. Ближайший слот — самая дорогая величина: у каждого мастера
своё расписание, свои особые даты и свои брони. Считать это запросом на день
на мастера значило бы сотни запросов на один экран, поэтому всё нужное
забирается четырьмя запросами на весь список, а пересечения считаются в памяти.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

import database as db
import timeutils
from database import ACTIVE_BOOKING_STATUSES
from services.booking import calculate_available_slots, resolve_schedule_for_date

#: На сколько дней вперёд ищем ближайшее окно. Две недели — горизонт,
#: за которым «ближайшее свободное время» перестаёт быть аргументом:
#: человек, готовый ждать три недели, выбирает не по этому признаку.
LOOKAHEAD_DAYS = 14

SORT_RATING = "rating"
SORT_PRICE = "price"
SORT_SOONEST = "soonest"
SORT_MODES = (SORT_RATING, SORT_PRICE, SORT_SOONEST)
DEFAULT_SORT = SORT_RATING


@dataclass
class StylistCard:
    """Строка списка: то, по чему человек выбирает, не открывая карточку."""

    stylist: db.Stylist
    min_price: float | None
    rating: float
    reviews: int
    nearest: datetime | None

    @property
    def id(self) -> int:
        return self.stylist.id

    @property
    def name(self) -> str:
        return self.stylist.name


def _sort_key(card: StylistCard, mode: str):
    """
    Ключ сортировки.

    Мастера без услуг и без свободного времени всегда уходят вниз, какой бы
    режим ни выбрали: показывать первым того, к кому нельзя записаться, —
    худшее, что может сделать список.
    """
    if mode == SORT_PRICE:
        missing = card.min_price is None
        return (missing, card.min_price or 0, -card.rating, card.name)
    if mode == SORT_SOONEST:
        missing = card.nearest is None
        return (missing, card.nearest or datetime.max, -card.rating, card.name)
    # По рейтингу: сначала оценка, при равной — число отзывов.
    # Мастер с одной пятёркой не должен обходить мастера с сорока.
    return (-card.rating, -card.reviews, card.name)


def sort_cards(cards: list[StylistCard], mode: str) -> list[StylistCard]:
    return sorted(cards, key=lambda card: _sort_key(card, mode))


def find_nearest_slot(
    stylist_id: int,
    duration_min: int,
    buffer_min: int,
    weekly: dict[int, db.Schedule],
    special: dict[date, db.SpecialSchedule],
    bookings_by_date: dict[date, list[db.Booking]],
    today: date,
    days: int = LOOKAHEAD_DAYS,
) -> datetime | None:
    """
    Первое свободное время в ближайшие `days` дней — или None.

    Считает в памяти по уже загруженным расписаниям и броням: на один экран
    со списком мастеров приходится не больше четырёх запросов на всех.
    """
    for offset in range(days):
        current = today + timedelta(days=offset)
        schedule = resolve_schedule_for_date(current, weekly, special)
        if not schedule:
            continue
        slots = calculate_available_slots(
            current, schedule, duration_min, bookings_by_date.get(current, []), buffer_min
        )
        if slots:
            return timeutils.parse_slot(f"{current:%Y-%m-%d} {slots[0]}")
    return None


async def load_stylist_cards(session, stylists: list[db.Stylist]) -> list[StylistCard]:
    """
    Факты по списку мастеров: рейтинг, цена «от», ближайшее свободное время.

    Четыре запроса на весь список независимо от его длины.
    """
    if not stylists:
        return []

    stylist_ids = [stylist.id for stylist in stylists]
    today = timeutils.today()
    window_end = today + timedelta(days=LOOKAHEAD_DAYS)

    # 1. Цена «от» и самая короткая услуга. Короткая — потому что именно она
    #    даёт самое раннее окно: по ней и считается «ближайшее свободное».
    service_rows = (await session.execute(
        select(
            db.Service.stylist_id,
            func.min(db.Service.price),
            func.min(db.Service.duration_min),
        )
        .where(db.Service.stylist_id.in_(stylist_ids))
        .group_by(db.Service.stylist_id)
    )).all()
    services = {
        row[0]: {"price": row[1], "duration": row[2]} for row in service_rows
    }

    # 2. Недельные расписания.
    weekly_by_stylist: dict[int, dict[int, db.Schedule]] = {}
    for schedule in (await session.execute(
        select(db.Schedule).where(db.Schedule.stylist_id.in_(stylist_ids))
    )).scalars().all():
        weekly_by_stylist.setdefault(schedule.stylist_id, {})[schedule.day_of_week] = schedule

    # 3. Особые даты в окне.
    special_by_stylist: dict[int, dict[date, db.SpecialSchedule]] = {}
    for item in (await session.execute(
        select(db.SpecialSchedule).where(
            db.SpecialSchedule.stylist_id.in_(stylist_ids),
            db.SpecialSchedule.work_date >= today,
            db.SpecialSchedule.work_date <= window_end,
        )
    )).scalars().all():
        special_by_stylist.setdefault(item.stylist_id, {})[item.work_date] = item

    # 4. Активные брони в окне.
    window_start, window_stop = timeutils.range_bounds(today, window_end)
    bookings_by_stylist: dict[int, dict[date, list[db.Booking]]] = {}
    for booking in (await session.execute(
        select(db.Booking).where(
            db.Booking.stylist_id.in_(stylist_ids),
            db.Booking.starts_at >= window_start,
            db.Booking.starts_at < window_stop,
            db.Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
    )).scalars().all():
        by_date = bookings_by_stylist.setdefault(booking.stylist_id, {})
        by_date.setdefault(booking.starts_at.date(), []).append(booking)

    cards = []
    for stylist in stylists:
        service = services.get(stylist.id)
        nearest = None
        if service:
            nearest = find_nearest_slot(
                stylist.id,
                service["duration"],
                stylist.buffer_min or 0,
                weekly_by_stylist.get(stylist.id, {}),
                special_by_stylist.get(stylist.id, {}),
                bookings_by_stylist.get(stylist.id, {}),
                today,
            )
        cards.append(StylistCard(
            stylist=stylist,
            min_price=service["price"] if service else None,
            rating=stylist.avg_rating or 0.0,
            reviews=stylist.reviews_count or 0,
            nearest=nearest,
        ))
    return cards
