"""
Журнал действий над записями.

Раньше на вопрос «кто отменил эту запись и когда» ответить было нечем:
статус менялся, а следов не оставалось. Для сервиса, где клиент и мастер
спорят о том, кто что отменил, это не мелочь, а отсутствие доказательства.

Главное правило здесь одно: **запись журнала кладётся в ту же сессию,
что и само изменение, и уезжает тем же commit'ом**. Отдельная сессия
означала бы, что при сбое между ними изменение есть, а следа нет —
то есть журнал врёт ровно в тех случаях, ради которых его читают.

Поэтому функции ниже ничего не коммитят. Они добавляют строку в переданную
сессию, а commit остаётся за вызывающим кодом.
"""
from sqlalchemy import select
from sqlalchemy.orm import joinedload

import database as db
from database import ACTOR_ADMIN, ACTOR_CLIENT, ACTOR_STYLIST, ACTOR_SYSTEM

#: Действия над записью. Строки собраны здесь, чтобы опечатка в одном
#: хендлере не рассыпала историю на два похожих значения.
BOOKING_CREATED = "booking.created"
BOOKING_CREATED_OFFLINE = "booking.created_offline"
BOOKING_APPROVED = "booking.approved"
BOOKING_DECLINED = "booking.declined"
BOOKING_COMPLETED = "booking.completed"
BOOKING_CANCELLED = "booking.cancelled"
BOOKING_RESCHEDULED = "booking.rescheduled"
REVIEW_HIDDEN = "review.hidden"
REVIEW_RESTORED = "review.restored"

#: Сколько строк отдаёт лента в админке за раз.
FEED_LIMIT = 100

#: Ограничение колонки details.
DETAILS_MAX_LEN = 500


def record(
    session,
    action: str,
    actor_kind: str,
    booking_id: int | None = None,
    actor_user_id: int | None = None,
    actor_label: str | None = None,
    details: str | None = None,
) -> db.AuditLog:
    """
    Добавляет строку журнала в сессию. Commit — на вызывающем.

    Возвращает объект, чтобы вызывающий мог при желании посмотреть на него
    в тестах; в рабочем коде возвращаемое значение обычно не нужно.
    """
    entry = db.AuditLog(
        action=action,
        actor_kind=actor_kind,
        actor_user_id=actor_user_id,
        actor_label=actor_label,
        booking_id=booking_id,
        details=(details or None) and details[:DETAILS_MAX_LEN],
    )
    session.add(entry)
    return entry


def record_client(session, action: str, booking: db.Booking, details: str | None = None):
    """Действие клиента над своей записью."""
    return record(
        session,
        action,
        ACTOR_CLIENT,
        booking_id=booking.id,
        actor_user_id=booking.user_id,
        details=details,
    )


def record_stylist(
    session,
    action: str,
    booking: db.Booking,
    stylist_user_id: int | None = None,
    details: str | None = None,
):
    """Действие мастера над записью клиента."""
    return record(
        session,
        action,
        ACTOR_STYLIST,
        booking_id=booking.id,
        actor_user_id=stylist_user_id,
        details=details,
    )


def record_admin(
    session,
    action: str,
    admin_username: str,
    booking_id: int | None = None,
    details: str | None = None,
):
    """
    Действие из веб-панели.

    У администратора нет строки в users, поэтому он подписывается логином.
    """
    return record(
        session,
        action,
        ACTOR_ADMIN,
        booking_id=booking_id,
        actor_label=admin_username,
        details=details,
    )


def record_system(session, action: str, booking_id: int | None = None, details: str | None = None):
    """Действие фоновой задачи: у него нет человека-автора."""
    return record(
        session, action, ACTOR_SYSTEM, booking_id=booking_id, actor_label="scheduler",
        details=details,
    )


async def load_history_for_booking(session, booking_id: int) -> list[db.AuditLog]:
    """Что происходило с одной записью — от старого к новому."""
    return (await session.execute(
        select(db.AuditLog)
        .where(db.AuditLog.booking_id == booking_id)
        .options(joinedload(db.AuditLog.actor))
        .order_by(db.AuditLog.created_at, db.AuditLog.id)
    )).scalars().all()


async def load_feed(session, limit: int = FEED_LIMIT) -> list[db.AuditLog]:
    """
    Общая лента для админки — от новых к старым.

    joinedload(actor) обязателен: лента показывает имя автора, а ленивая
    подгрузка в async-контексте бросит MissingGreenlet (CLAUDE.md, 4.3).
    """
    return (await session.execute(
        select(db.AuditLog)
        .options(joinedload(db.AuditLog.actor))
        .order_by(db.AuditLog.created_at.desc(), db.AuditLog.id.desc())
        .limit(limit)
    )).scalars().all()
