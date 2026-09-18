"""
Рейтинг мастера.

Денормализованные avg_rating и reviews_count пересчитываются после каждой оценки:
их читают карточка мастера, поиск и дашборд, и раньше они не обновлялись вообще —
в карточке всегда было «Нет оценок» (docs/AUDIT.md, A-3).
"""
import logging

from sqlalchemy import func, select

import database as db


async def recalculate_stylist_rating(session, stylist_id: int) -> float:
    """
    Пересчитывает средний рейтинг мастера по завершённым визитам с оценкой.
    Вызывается после каждой новой оценки: денормализованное поле Stylist.avg_rating
    читают карточка мастера, поиск и дашборд.
    """
    row = (
        await session.execute(
            select(func.avg(db.Booking.rating), func.count(db.Booking.rating)).where(
                db.Booking.stylist_id == stylist_id,
                db.Booking.rating.isnot(None),
            )
        )
    ).one()
    average, count = row
    value = round(float(average), 2) if average is not None else 0.0

    stylist = await session.get(db.Stylist, stylist_id)
    if stylist:
        stylist.avg_rating = value
        stylist.reviews_count = int(count or 0)
        await session.commit()
        logging.info(
            "rating.recalculated stylist_id=%s value=%s count=%s", stylist_id, value, count
        )
    return value
