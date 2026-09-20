"""
Метрики для внешнего наблюдения.

`/health` отвечает «жив или нет», и этого мало: сервис бывает живым и при этом
сломанным. Заявка, которую мастер не разобрал третьи сутки, ничего не роняет —
клиент просто не дождался ответа и ушёл. Такое видно только по числам.

Формат — текстовый вывод Prometheus. Не потому, что Prometheus обязательно
будет: это формат, который читают все системы наблюдения и, при нужде, глаза.
JSON пришлось бы под каждую из них переписывать.

Отдельно про алерты: числа, на которые никто не смотрит, не отличаются
от их отсутствия. `problems()` превращает метрики в список человеческих
претензий, и его же отправляет шедулер в Telegram владельцу.
"""
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select

import database as db
import timeutils
from database import ACTIVE_BOOKING_STATUSES, BOOKING_PENDING

#: Заявка, которую мастер не разобрал за это время, — потерянный клиент.
#: Сутки, а не час: мастер работает руками и в телефон смотрит не всегда.
PENDING_ALERT_HOURS = 24

#: Сколько записей на ближайшие сутки считается «день пустой». Ноль записей
#: у сервиса с активными мастерами — повод посмотреть, а не норма.
EMPTY_DAY_THRESHOLD = 0


@dataclass
class Metrics:
    users: int
    stylists_active: int
    bookings_today: int
    bookings_pending: int
    bookings_pending_stale: int
    reviews_hidden: int
    audit_entries_today: int

    def as_prometheus(self) -> str:
        """
        Текстовый формат Prometheus: HELP, TYPE, значение.

        Имена с префиксом maestro_ — иначе в общей системе наблюдения
        метрика «users» сольётся с чужой.
        """
        lines = []
        for name, help_text, value in (
            ("maestro_users_total", "Зарегистрированных пользователей", self.users),
            ("maestro_stylists_active", "Мастеров с активной подпиской", self.stylists_active),
            ("maestro_bookings_today", "Записей на сегодня", self.bookings_today),
            ("maestro_bookings_pending", "Заявок в ожидании ответа мастера", self.bookings_pending),
            ("maestro_bookings_pending_stale",
             f"Заявок без ответа дольше {PENDING_ALERT_HOURS} ч.", self.bookings_pending_stale),
            ("maestro_reviews_hidden", "Отзывов скрыто модератором", self.reviews_hidden),
            ("maestro_audit_entries_today", "Действий над записями за сегодня",
             self.audit_entries_today),
        ):
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"


def problems(metrics: Metrics) -> list[str]:
    """
    Человеческие претензии к текущему состоянию.

    Пустой список — всё в порядке. Это же сообщение уходит владельцу
    в Telegram: числа, на которые никто не смотрит, не отличаются
    от их отсутствия.
    """
    found = []

    if metrics.bookings_pending_stale:
        found.append(
            f"Заявок без ответа мастера дольше {PENDING_ALERT_HOURS} ч.: "
            f"{metrics.bookings_pending_stale}. Клиент столько не ждёт."
        )

    if metrics.stylists_active == 0:
        found.append(
            "Ни одного мастера с активной подпиской — записаться не к кому."
        )
    elif metrics.bookings_today <= EMPTY_DAY_THRESHOLD:
        # Проверяем только когда мастера вообще есть: иначе это та же
        # проблема, сказанная дважды.
        found.append("На сегодня нет ни одной записи.")

    return found


async def collect(session) -> Metrics:
    """Все числа одним проходом. Каждое — отдельный дешёвый COUNT по индексу."""
    today = timeutils.today()
    day_start, day_end = timeutils.day_bounds(today)
    stale_before = timeutils.now() - timedelta(hours=PENDING_ALERT_HOURS)

    async def count(model, *where):
        return await session.scalar(
            select(func.count()).select_from(model).where(*where)
        ) or 0

    return Metrics(
        users=await count(db.User),
        stylists_active=await count(
            db.User, db.User.role == "stylist", db.User.is_active.is_(True)
        ),
        bookings_today=await count(
            db.Booking,
            db.Booking.starts_at >= day_start,
            db.Booking.starts_at < day_end,
            db.Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        ),
        bookings_pending=await count(db.Booking, db.Booking.status == BOOKING_PENDING),
        # Считаем по created_at, а не по starts_at: «заявка висит третьи сутки»
        # — про момент подачи, а не про дату визита. Запись на следующий месяц,
        # поданная час назад, застарелой не является.
        bookings_pending_stale=await count(
            db.Booking,
            db.Booking.status == BOOKING_PENDING,
            db.Booking.created_at < stale_before,
        ),
        reviews_hidden=await count(db.Booking, db.Booking.review_hidden.is_(True)),
        audit_entries_today=await count(
            db.AuditLog,
            db.AuditLog.created_at >= day_start,
            db.AuditLog.created_at < day_end,
        ),
    )
