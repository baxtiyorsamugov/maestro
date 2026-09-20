"""
Текстовые отзывы о мастере.

Колонка review_text была в схеме с самого начала, но UI под неё не было:
клиент ставил звёзды вслепую, а новый человек видел в карточке только цифру
без единого слова о том, как всё прошло.

Модерация постфактум: отзыв виден сразу, владелец может его скрыть. Премодерация
в сервисе с одним администратором означала бы, что отзывы не появляются вообще —
очередь некому разбирать.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

import database as db
from database import BOOKING_COMPLETED

#: Ограничение колонки review_text. Обрезаем на входе, чтобы не ловить ошибку
#: базы после того, как человек уже написал текст.
REVIEW_MAX_LEN = 500

#: Сколько отзывов показывать в карточке мастера. Больше в одно сообщение
#: Telegram и не влезет, а листать карточку никто не станет.
REVIEWS_PREVIEW_LIMIT = 5


def normalize_review(raw: str | None) -> str | None:
    """
    Текст отзыва: без хвостовых пробелов и не длиннее колонки.

    Переносы строк внутри сохраняются — человек мог разбить отзыв на абзацы,
    и склеивать их в одну строку значит портить то, что он написал.
    """
    if not raw:
        return None
    cleaned = "\n".join(line.strip() for line in raw.strip().splitlines())
    cleaned = cleaned[:REVIEW_MAX_LEN].strip()
    return cleaned or None


def can_leave_review(booking: db.Booking) -> tuple[bool, str | None]:
    """
    Может ли клиент написать отзыв по этой записи.

    Возвращает (можно, ключ_причины) — ключ из texts.py, а не готовый текст:
    сервис не знает язык пользователя и не должен знать (CLAUDE.md, 4.5).
    """
    if booking.status != BOOKING_COMPLETED:
        return False, "review_denied_not_completed"
    if booking.rating is None:
        # Отзыв без оценки осиротел бы: в карточке отзывы показываются
        # вместе со звёздами, и взять их будет неоткуда.
        return False, "review_denied_no_rating"
    if booking.review_text:
        return False, "review_denied_already_left"
    return True, None


async def load_reviews_for_stylist(
    session, stylist_id: int, limit: int = REVIEWS_PREVIEW_LIMIT
) -> list[db.Booking]:
    """
    Последние видимые отзывы о мастере.

    joinedload(user) обязателен: подпись отзыва берёт имя клиента, а ленивая
    подгрузка в async-контексте бросит MissingGreenlet (CLAUDE.md, 4.3).
    """
    return (await session.execute(
        select(db.Booking)
        .where(
            db.Booking.stylist_id == stylist_id,
            db.Booking.review_text.is_not(None),
            db.Booking.review_hidden.is_(False),
        )
        .options(joinedload(db.Booking.user))
        .order_by(db.Booking.starts_at.desc())
        .limit(limit)
    )).scalars().all()


async def count_reviews_for_stylist(session, stylist_id: int) -> int:
    """Сколько видимых отзывов всего — чтобы честно написать «и ещё N»."""
    return await session.scalar(
        select(func.count())
        .select_from(db.Booking)
        .where(
            db.Booking.stylist_id == stylist_id,
            db.Booking.review_text.is_not(None),
            db.Booking.review_hidden.is_(False),
        )
    ) or 0


async def load_reviews_for_moderation(session, limit: int = 50) -> list[db.Booking]:
    """
    Все отзывы для админки, включая скрытые: скрытие нужно уметь отменить.

    Порядок — от новых к старым: модератор разбирает то, что только что пришло.
    """
    return (await session.execute(
        select(db.Booking)
        .where(db.Booking.review_text.is_not(None))
        .options(
            joinedload(db.Booking.user),
            joinedload(db.Booking.stylist),
        )
        .order_by(db.Booking.starts_at.desc())
        .limit(limit)
    )).scalars().all()
