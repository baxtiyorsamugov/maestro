"""
Права доступа и состояние подписки.

Модуль намеренно ничего не знает ни про aiogram-контекст, ни про клавиатуры:
это чистые запросы к базе, которые можно вызвать откуда угодно и покрыть тестами
без поднятия бота.

Функции, которые не просто проверяют, а ещё и отвечают пользователю
(ensure_*, deny_access), живут в guards.py — уровнем выше.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import joinedload

import database as db
import timeutils


async def get_stylist_profile_by_telegram(session, telegram_id: int):
    user = await session.scalar(select(db.User).where(db.User.telegram_id == telegram_id))
    if not user:
        return None, None
    stylist = await session.scalar(select(db.Stylist).where(db.Stylist.user_id == user.id))
    return user, stylist

def is_stylist_subscription_active(user: db.User | None, today: date | None = None) -> bool:
    if not user or user.role != "stylist" or not user.is_active:
        return False
    today = today or timeutils.today()
    return user.subscription_until is None or user.subscription_until >= today

def get_subscription_days_left(user: db.User | None, today: date | None = None) -> int | None:
    if not user or user.subscription_until is None:
        return None
    today = today or timeutils.today()
    return (user.subscription_until - today).days

def is_registration_complete(user: db.User | None) -> bool:
    return bool(user and user.language_code and user.first_name and user.phone_number)

BOOKING_CARD_OPTIONS = (
    joinedload(db.Booking.user),
    joinedload(db.Booking.stylist).joinedload(db.Stylist.user_account),
    joinedload(db.Booking.service).joinedload(db.Service.catalog_service),
)

async def load_booking_for_stylist(session, booking_id: int, telegram_id: int) -> db.Booking | None:
    """
    Запись, доступная мастеру: только если она принадлежит его собственному профилю.
    Идентификатор из callback_data — недоверенный ввод, владельца сверяем в самом запросе.
    """
    return await session.scalar(
        select(db.Booking)
        .join(db.Stylist, db.Stylist.id == db.Booking.stylist_id)
        .join(db.User, db.User.id == db.Stylist.user_id)
        .where(db.Booking.id == booking_id, db.User.telegram_id == telegram_id)
        .options(*BOOKING_CARD_OPTIONS)
    )

async def load_booking_for_client(session, booking_id: int, telegram_id: int) -> db.Booking | None:
    """Запись, доступная клиенту: только его собственная."""
    return await session.scalar(
        select(db.Booking)
        .join(db.User, db.User.id == db.Booking.user_id)
        .where(db.Booking.id == booking_id, db.User.telegram_id == telegram_id)
        .options(*BOOKING_CARD_OPTIONS)
    )
