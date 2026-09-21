"""
Статистика мастера за период — с динамикой к предыдущему такому же периоду.

Раньше отчёт был четырьмя счётчиками без сравнения: «12 записей» ничего
не говорит, пока не видно, что на прошлой неделе было 20. Ещё две ошибки
старого отчёта исправлены здесь:

- «последние 7 дней» на деле были восемью (от «сегодня минус 7» по сегодня
  включительно);
- в «доход» попадали подтверждённые визиты, которые ещё не состоялись.
  Заработанное и ожидаемое теперь разделены: первое — деньги, второе — план.

Ограничение, о котором стоит знать: цена берётся из услуги сейчас, а не на
момент визита — отдельной колонки с ценой в записи нет. Мастер, поднявший
цену, увидит прошлую выручку пересчитанной по новой.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select

import database as db
import timeutils

#: Период → (сколько дней, сдвиг конца от сегодня). Конец не включается.
PERIODS = {
    "today": (1, 1),
    "yesterday": (1, 0),
    "7": (7, 1),
    "30": (30, 1),
}
PEAK_HOURS_SHOWN = 3


def period_bounds(period: str, today: date | None = None) -> tuple[date, date]:
    """[первый день, день после последнего) — полуинтервал, как везде в проекте."""
    days, end_shift = PERIODS[period]
    today = today or timeutils.today()
    end = today + timedelta(days=end_shift)
    return end - timedelta(days=days), end


def previous_bounds(start: date, end: date) -> tuple[date, date]:
    """Такой же по длине период прямо перед данным."""
    length = end - start
    return start - length, start


@dataclass
class PeriodStats:
    pending: int = 0
    approved: int = 0
    completed: int = 0
    cancelled: int = 0
    declined: int = 0
    earned: int = 0
    expected: int = 0
    clients: int = 0
    returning_clients: int = 0
    guests: int = 0
    peak_hours: list[tuple[int, int]] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Записи, которые состоялись или ещё могут состояться."""
        return self.pending + self.approved + self.completed

    @property
    def lost(self) -> int:
        return self.cancelled + self.declined


@dataclass
class StatsReport:
    current: PeriodStats
    previous: PeriodStats


def change_percent(current: int, previous: int) -> int | None:
    """
    Изменение в процентах. None — сравнивать не с чем (в прошлом периоде
    был ноль): «+∞%» человеку ничего не скажет.
    """
    if not previous:
        return None
    return round((current - previous) * 100 / previous)


def _summarize(rows, start, end, returning_ids: set[int]) -> PeriodStats:
    stats = PeriodStats()
    start_dt, end_dt = timeutils.range_bounds(start, end - timedelta(days=1))
    hours: Counter[int] = Counter()
    clients: set[int] = set()

    for status, user_id, starts_at, price in rows:
        if not (start_dt <= starts_at < end_dt):
            continue
        price = int(price or 0)
        if status == db.BOOKING_PENDING:
            stats.pending += 1
        elif status == db.BOOKING_APPROVED:
            stats.approved += 1
            stats.expected += price
        elif status == db.BOOKING_COMPLETED:
            stats.completed += 1
            stats.earned += price
        elif status == db.BOOKING_CANCELLED:
            stats.cancelled += 1
            continue
        elif status == db.BOOKING_DECLINED:
            stats.declined += 1
            continue

        # Загрузка и клиенты — только по визитам, которые были или будут.
        hours[starts_at.hour] += 1
        if user_id is None:
            stats.guests += 1
        else:
            clients.add(user_id)

    stats.clients = len(clients)
    stats.returning_clients = len(clients & returning_ids)
    stats.peak_hours = hours.most_common(PEAK_HOURS_SHOWN)
    return stats


async def collect(session, stylist_id: int, period: str, today: date | None = None) -> StatsReport:
    start, end = period_bounds(period, today)
    prev_start, prev_end = previous_bounds(start, end)
    window_start, window_end = timeutils.range_bounds(prev_start, end - timedelta(days=1))

    # Одна выборка на оба периода: записей у мастера за 60 дней — сотни,
    # считать в Python проще и переносимее, чем часы через SQL-функции,
    # которые у SQLite и PostgreSQL разные.
    rows = (await session.execute(
        select(db.Booking.status, db.Booking.user_id, db.Booking.starts_at, db.Service.price)
        .join(db.Service, db.Service.id == db.Booking.service_id, isouter=True)
        .where(
            db.Booking.stylist_id == stylist_id,
            db.Booking.starts_at >= window_start,
            db.Booking.starts_at < window_end,
        )
    )).all()

    async def returning_before(day: date) -> set[int]:
        """Клиенты, уже побывавшие у этого мастера до начала периода."""
        boundary, _ = timeutils.day_bounds(day)
        return set((await session.execute(
            select(db.Booking.user_id).distinct().where(
                db.Booking.stylist_id == stylist_id,
                db.Booking.status == db.BOOKING_COMPLETED,
                db.Booking.user_id.is_not(None),
                db.Booking.starts_at < boundary,
            )
        )).scalars())

    return StatsReport(
        current=_summarize(rows, start, end, await returning_before(start)),
        previous=_summarize(rows, prev_start, prev_end, await returning_before(prev_start)),
    )
