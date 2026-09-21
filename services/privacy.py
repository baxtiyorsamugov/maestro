"""
Персональные данные: что храним и как удаляем по запросу.

Удалить аккаунт по просьбе человека было нельзя вовсе — ни кнопкой, ни через
администратора, у которого не было для этого инструмента.

Главное решение здесь смысловое, а не техническое: **обезличивать, а не
стирать всё подряд**. Правило одно — удаляется всё, что указывает на человека;
остаются обезличенные факты, от которых зависят другие:

  * удаляется: имя, телефон, telegram_id, тексты отзывов (это его слова,
    в них бывает имя), избранные мастера (это его предпочтения);
  * остаётся без привязки к человеку: сам факт визита — на него опирается
    выручка мастера за прошлые месяцы; звёздная оценка — на ней держится
    рейтинг, который мастер заработал работой; запись в журнале действий —
    она доказательство, и «кто-то отменил запись» остаётся правдой и после.

Стереть визиты целиком значило бы переписать задним числом чужую бухгалтерию.
Оставить имя в журнале значило бы не выполнить просьбу.

Мастера удаляют аккаунт только через владельца сервиса: за учёткой мастера
стоят подписка, расписание, клиенты с записями на будущее — это решение
не для одной кнопки.
"""
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import joinedload

import database as db
import timeutils
from database import ACTIVE_BOOKING_STATUSES, BOOKING_CANCELLED
from services import audit

#: Подпись в журнале вместо удалённого человека. Факт действия остаётся,
#: личность — нет.
DELETED_ACTOR_LABEL = "удалённый пользователь"

#: Действие в журнале: сам факт удаления. Нужен, чтобы на вопрос «удалили ли
#: вы мои данные и когда» был ответ — без него удаление не оставляет следа.
ACCOUNT_DELETED = "account.deleted"


class DeletionRefused(Exception):
    """Удаление недоступно для этой учётной записи — с причиной для человека."""

    def __init__(self, reason_key: str):
        super().__init__(reason_key)
        self.reason_key = reason_key


@dataclass
class UserDataSummary:
    """Что о человеке хранится — показываем до удаления, чтобы решение было осознанным."""

    has_phone: bool
    bookings: int
    upcoming: int
    reviews: int
    favorites: int


@dataclass
class CancelledVisit:
    """Запись, отменённая при удалении: мастера надо предупредить."""

    booking_id: int
    starts_at: datetime
    stylist_telegram_id: int | None
    stylist_lang: str


@dataclass
class DeletionReport:
    cancelled: list[CancelledVisit] = field(default_factory=list)
    bookings_unlinked: int = 0
    reviews_removed: int = 0
    favorites_removed: int = 0
    audit_anonymized: int = 0


async def summarize(session, user: db.User) -> UserDataSummary:
    """Сводка того, что хранится. Всё — отдельными дешёвыми COUNT."""
    from sqlalchemy import func

    async def count(*where):
        return await session.scalar(
            select(func.count()).select_from(db.Booking).where(*where)
        ) or 0

    favorites = await session.scalar(
        select(func.count()).select_from(db.Favorite).where(db.Favorite.user_id == user.id)
    ) or 0

    return UserDataSummary(
        has_phone=bool(user.phone_number),
        bookings=await count(db.Booking.user_id == user.id),
        upcoming=await count(
            db.Booking.user_id == user.id,
            db.Booking.starts_at >= timeutils.now(),
            db.Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        ),
        reviews=await count(
            db.Booking.user_id == user.id, db.Booking.review_text.is_not(None)
        ),
        favorites=favorites,
    )


async def delete_client_account(session, user_id: int) -> DeletionReport:
    """
    Удаляет учётную запись клиента, обезличивая то, от чего зависят другие.

    Всё — одной транзакцией, и коммит здесь же. Удаление, оставленное на
    вызывающем, при забытом commit выглядело бы выполненным для человека,
    а данные остались бы — худший из возможных исходов для такой операции.

    Порядок шагов не случаен: внешние ключи без каскадов, и строку users
    можно удалить только последней, когда на неё уже никто не ссылается.
    """
    user = await session.get(db.User, user_id)
    if user is None:
        # Повторное нажатие после удаления: делать нечего, и это не ошибка.
        return DeletionReport()
    if user.role == "stylist":
        raise DeletionRefused("privacy_stylist_refused")

    report = DeletionReport()
    now = timeutils.now()

    # 1. Будущие записи отменяем, а не отвязываем молча: мастер ждёт человека,
    #    которого больше нет, и должен узнать об этом до визита, а не в момент.
    upcoming = (await session.execute(
        select(db.Booking)
        .where(
            db.Booking.user_id == user.id,
            db.Booking.starts_at >= now,
            db.Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .options(joinedload(db.Booking.stylist).joinedload(db.Stylist.user_account))
    )).scalars().unique().all()

    for booking in upcoming:
        booking.status = BOOKING_CANCELLED
        audit.record_client(
            session, audit.BOOKING_CANCELLED, booking, details="удаление аккаунта"
        )
        stylist_user = booking.stylist.user_account if booking.stylist else None
        report.cancelled.append(CancelledVisit(
            booking_id=booking.id,
            starts_at=booking.starts_at,
            stylist_telegram_id=stylist_user.telegram_id if stylist_user else None,
            stylist_lang=(stylist_user.language_code if stylist_user else None) or "ru",
        ))

    # flush, чтобы записи журнала из шага 1 уже лежали в базе к шагу 3 —
    # иначе UPDATE их не увидит, и имя останется ровно в свежих строках.
    await session.flush()

    # 2. Тексты отзывов — слова человека, в них бывает имя. Звёзды остаются:
    #    на них держится рейтинг, который мастер заработал работой.
    report.reviews_removed = (await session.execute(
        update(db.Booking)
        .where(db.Booking.user_id == user.id, db.Booking.review_text.is_not(None))
        .values(review_text=None)
    )).rowcount or 0

    # 3. Журнал обезличиваем, а не чистим: «кто-то отменил запись» остаётся
    #    правдой и доказательством, но уже не говорит, кто это был.
    report.audit_anonymized = (await session.execute(
        update(db.AuditLog)
        .where(db.AuditLog.actor_user_id == user.id)
        .values(actor_user_id=None, actor_label=DELETED_ACTOR_LABEL)
    )).rowcount or 0

    # 4. Визиты отвязываем от человека. Факт визита остаётся — на нём стоит
    #    выручка мастера за прошлые месяцы, переписывать её задним числом нельзя.
    report.bookings_unlinked = (await session.execute(
        update(db.Booking).where(db.Booking.user_id == user.id).values(user_id=None)
    )).rowcount or 0

    # 5. Избранное — это предпочтения человека, а не чужой факт.
    report.favorites_removed = (await session.execute(
        delete(db.Favorite).where(db.Favorite.user_id == user.id)
    )).rowcount or 0

    # 6. Факт удаления — в журнал, уже без привязки к человеку. Без этого
    #    на вопрос «удалили ли вы мои данные и когда» не было бы ответа.
    audit.record(
        session, ACCOUNT_DELETED, db.ACTOR_CLIENT,
        actor_label=DELETED_ACTOR_LABEL,
        details=(
            f"визитов отвязано: {report.bookings_unlinked}, "
            f"отменено будущих: {len(report.cancelled)}"
        ),
    )

    # 7. Строку users — последней: теперь на неё никто не ссылается.
    await session.delete(user)
    await session.commit()
    return report
