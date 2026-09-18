"""
Статистика мастера за период.
"""
from datetime import timedelta

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, select

import database as db
import timeutils
from database import BOOKING_APPROVED, BOOKING_COMPLETED, BOOKING_PENDING
from guards import (
    ensure_active_stylist_callback,
    ensure_active_stylist_message,
)

router = Router(name="stylist_stats")


@router.message(F.text == "📊 Моя статистика")
async def show_stats_menu(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    async with db.async_session() as session:
        fav_count = await session.scalar(select(func.count(db.Favorite.id)).where(db.Favorite.stylist_id == stylist.id))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u0417\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f", callback_data="stats_today")],
        [InlineKeyboardButton(text="\u0417\u0430 \u0432\u0447\u0435\u0440\u0430", callback_data="stats_yesterday")],
        [InlineKeyboardButton(text="\u0417\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 7 \u0434\u043d\u0435\u0439", callback_data="stats_7_days")],
    ])
    await message.answer(
        f"<b>\u0412\u0430\u0441 \u0434\u043e\u0431\u0430\u0432\u0438\u043b\u0438 \u0432 \u0438\u0437\u0431\u0440\u0430\u043d\u043d\u043e\u0435 {fav_count} \u0440\u0430\u0437(\u0430).</b>\n\n\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u0435\u0440\u0438\u043e\u0434 \u0434\u043b\u044f \u043e\u0442\u0447\u0451\u0442\u0430:",
        reply_markup=kb,
        parse_mode="HTML",
    )

@router.callback_query(F.data.startswith("stats_"))
async def get_statistics(cb: CallbackQuery):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        return

    period = cb.data.split("_")[1]
    today = timeutils.today()
    if period == "today":
        start_date = today
        end_date = today + timedelta(days=1)
        period_text = "\u0441\u0435\u0433\u043e\u0434\u043d\u044f"
    elif period == "yesterday":
        start_date = today - timedelta(days=1)
        end_date = today
        period_text = "\u0432\u0447\u0435\u0440\u0430"
    elif period == "7":
        start_date = today - timedelta(days=7)
        end_date = today + timedelta(days=1)
        period_text = "\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 7 \u0434\u043d\u0435\u0439"
    else:
        await cb.answer("\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u044b\u0439 \u043f\u0435\u0440\u0438\u043e\u0434.")
        return

    # start_date/end_date заданы в днях, а запросы сравнивают моменты времени.
    period_start, period_end = timeutils.range_bounds(start_date, end_date - timedelta(days=1))

    async with db.async_session() as session:
        pending_count = await session.scalar(
            select(func.count(db.Booking.id)).where(
                db.Booking.stylist_id == stylist.id,
                db.Booking.status == BOOKING_PENDING,
                db.Booking.starts_at >= period_start,
                db.Booking.starts_at < period_end,
            )
        ) or 0
        approved_count = await session.scalar(
            select(func.count(db.Booking.id)).where(
                db.Booking.stylist_id == stylist.id,
                db.Booking.status == BOOKING_APPROVED,
                db.Booking.starts_at >= period_start,
                db.Booking.starts_at < period_end,
            )
        ) or 0
        completed_count = await session.scalar(
            select(func.count(db.Booking.id)).where(
                db.Booking.stylist_id == stylist.id,
                db.Booking.status == BOOKING_COMPLETED,
                db.Booking.starts_at >= period_start,
                db.Booking.starts_at < period_end,
            )
        ) or 0
        revenue = await session.scalar(
            select(func.coalesce(func.sum(db.Service.price), 0))
            .select_from(db.Booking)
            .join(db.Service, db.Service.id == db.Booking.service_id)
            .where(
                db.Booking.stylist_id == stylist.id,
                db.Booking.status.in_((BOOKING_APPROVED, BOOKING_COMPLETED)),
                db.Booking.starts_at >= period_start,
                db.Booking.starts_at < period_end,
            )
        ) or 0

    total_count = pending_count + approved_count + completed_count
    await cb.message.edit_text(
        f"<b>\u041e\u0442\u0447\u0451\u0442 \u0437\u0430 {period_text}:</b>\n\n"
        f"\u0412\u0441\u0435\u0433\u043e \u0437\u0430\u043f\u0438\u0441\u0435\u0439: {total_count}\n"
        f"\u041d\u043e\u0432\u044b\u0435 \u0437\u0430\u044f\u0432\u043a\u0438: {pending_count}\n"
        f"\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043d\u043d\u044b\u0435: {approved_count}\n"
        f"\u0417\u0430\u0432\u0435\u0440\u0448\u0451\u043d\u043d\u044b\u0435: {completed_count}\n"
        f"\u0414\u043e\u0445\u043e\u0434: {revenue:,.0f} so'm",
        parse_mode="HTML",
    )
    await cb.answer()
