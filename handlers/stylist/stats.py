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
import texts
import timeutils
from database import BOOKING_APPROVED, BOOKING_COMPLETED, BOOKING_PENDING
from guards import (
    ensure_active_stylist_callback,
    ensure_active_stylist_message,
)

router = Router(name="stylist_stats")


@router.message(F.text.in_(texts.all_variants("my_stats")))
async def show_stats_menu(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    lang = user.language_code or "ru"
    async with db.async_session() as session:
        fav_count = await session.scalar(select(func.count(db.Favorite.id)).where(db.Favorite.stylist_id == stylist.id))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=texts.get_text("stats_period_today", lang), callback_data="stats_today"
        )],
        [InlineKeyboardButton(
            text=texts.get_text("stats_period_yesterday", lang), callback_data="stats_yesterday"
        )],
        [InlineKeyboardButton(
            text=texts.get_text("stats_period_week", lang), callback_data="stats_7_days"
        )],
    ])
    await message.answer(
        f"<b>{texts.get_text('stats_favorites_count', lang).format(count=fav_count)}</b>\n\n"
        f"{texts.get_text('stats_choose_period', lang)}",
        reply_markup=kb,
        parse_mode="HTML",
    )

@router.callback_query(F.data.startswith("stats_"))
async def get_statistics(cb: CallbackQuery):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        return

    period = cb.data.split("_")[1]
    lang = user.language_code or "ru"
    today = timeutils.today()
    if period == "today":
        start_date = today
        end_date = today + timedelta(days=1)
        period_text = texts.get_text("stats_label_today", lang)
    elif period == "yesterday":
        start_date = today - timedelta(days=1)
        end_date = today
        period_text = texts.get_text("stats_label_yesterday", lang)
    elif period == "7":
        start_date = today - timedelta(days=7)
        end_date = today + timedelta(days=1)
        period_text = texts.get_text("stats_label_week", lang)
    else:
        await cb.answer(texts.get_text("stats_unknown_period", lang))
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
        f"<b>{texts.get_text('stats_report_title', lang).format(period=period_text)}</b>\n\n"
        f"{texts.get_text('stats_total', lang)}: {total_count}\n"
        f"{texts.get_text('stats_pending', lang)}: {pending_count}\n"
        f"{texts.get_text('stats_approved', lang)}: {approved_count}\n"
        f"{texts.get_text('stats_completed', lang)}: {completed_count}\n"
        f"{texts.get_text('stats_revenue', lang)}: {revenue:,.0f} so'm",
        parse_mode="HTML",
    )
    await cb.answer()
