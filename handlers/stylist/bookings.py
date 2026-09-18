"""
Заявки клиентов: просмотр, подтверждение, отклонение, завершение визита.
"""
import logging
from datetime import datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select
from sqlalchemy.orm import joinedload

import database as db
import texts
import timeutils
from database import (
    ACTIVE_BOOKING_STATUSES,
    BOOKING_APPROVED,
    BOOKING_COMPLETED,
    BOOKING_DECLINED,
    BOOKING_PENDING,
)
from guards import (
    deny_access,
    ensure_active_stylist_callback,
    ensure_active_stylist_message,
    get_user_lang,
)
from loader import bot
from presenters import (
    build_booking_card,
)
from services.access import (
    load_booking_for_stylist,
)

router = Router(name="stylist_bookings")


@router.message(F.text.in_(texts.all_variants("my_bookings")))
async def show_bookings_menu(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☀️ На сегодня", callback_data="view_bookings_today")],
        [InlineKeyboardButton(text="📅 На неделю", callback_data="view_bookings_week")],
        [InlineKeyboardButton(text="📚 Все записи", callback_data="view_bookings_all")]
    ])
    
    await message.answer("Выберите период для просмотра записей:", reply_markup=kb)

@router.callback_query(F.data.startswith("view_bookings_"))
async def process_view_bookings(cb: CallbackQuery):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        return

    period = cb.data.split("_")[-1]
    today_dt = datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")
    
    async with db.async_session() as session:
        # Базовый запрос: только активные и завершенные будущие записи
        query = select(db.Booking).where(
            db.Booking.stylist_id == stylist.id,
            db.Booking.status.in_(ACTIVE_BOOKING_STATUSES)  # не показываем отклонённые и старые
        ).options(
            joinedload(db.Booking.user), 
            joinedload(db.Booking.service).joinedload(db.Service.catalog_service)
        )

        if period == "today":
            day_start, day_end = timeutils.day_bounds(today_dt.date())
            query = query.where(db.Booking.starts_at >= day_start, db.Booking.starts_at < day_end)
            title = f"☀️ Записи на сегодня ({today_str})"
        
        elif period == "week":
            week_start, week_end = timeutils.range_bounds(
                today_dt.date(), today_dt.date() + timedelta(days=6)
            )
            end_week = week_end.strftime("%Y-%m-%d")
            query = query.where(db.Booking.starts_at >= week_start, db.Booking.starts_at < week_end)
            title = f"📅 Записи на неделю (до {end_week})"
        
        else: # "all" — теперь это "Все будущие записи"
            query = query.where(db.Booking.starts_at >= timeutils.now())
            title = "📚 Все предстоящие записи"

        query = query.order_by(db.Booking.starts_at)
        result = await session.execute(query)
        bookings = result.scalars().all()

    if not bookings:
        await cb.message.edit_text(f"<b>{title}</b>\n\n📭 Актуальных записей нет.", parse_mode="HTML")
        await cb.answer()
        return

    await cb.message.edit_text(f"<b>{title}</b>\nНайдено: {len(bookings)}", parse_mode="HTML")
    
    for b in bookings:
        try:
            client_name = b.user.first_name if b.user else "Клиент"
            service_name = b.service.catalog_service.name if (b.service and b.service.catalog_service) else "Услуга"
            display_date = timeutils.format_human(b.starts_at)
            
            status_emoji = "⏳" if b.status == BOOKING_PENDING else "✅"
            
            text = (
                f"{status_emoji} <b>{display_date}</b>\n"
                f"👤 {client_name}\n"
                f"✂️ {service_name}\n"
                f"📞 <code>{b.user.phone_number if b.user else 'не указан'}</code>"
            )
            
            kb = None
            if b.status == BOOKING_APPROVED:
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🏁 Завершить визит", callback_data=f"complete_{b.id}")
                ]])
            
            await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Error rendering booking {b.id}: {e}")
            continue
    
    await cb.answer()

@router.callback_query(F.data.startswith("approve_"))
async def approve_booking(cb: CallbackQuery):
    booking_id = int(cb.data.split("_")[-1])
    lang = await get_user_lang(cb.from_user.id)

    async with db.async_session() as session:
        booking = await load_booking_for_stylist(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        if booking.status != BOOKING_PENDING:
            await cb.answer(texts.get_text("booking_already_handled", lang), show_alert=True)
            return

        booking.status = BOOKING_APPROVED
        await session.commit()
        client_lang = booking.user.language_code or "ru"
        client_telegram_id = booking.user.telegram_id
        booking_datetime = timeutils.format_human(booking.starts_at, client_lang)
        card = build_booking_card(booking, texts.get_text("booking_approved", lang), lang)

    try:
        await bot.send_message(
            chat_id=client_telegram_id,
            text={
                "ru": (
                    "✨ <b>Прекрасный выбор!</b>\n\n"
                    "Ваша запись подтверждена. Мастер уже готовится к вашему визиту.\n\n"
                    f"📅 Ждём вас: <b>{escape(booking_datetime)}</b>\n\n"
                    "До встречи в Maestro! ✂️"
                ),
                "uz": (
                    "✨ <b>Ajoyib tanlov!</b>\n\n"
                    "Sizning yozuvingiz tasdiqlandi. Maestro tashrifingizga tayyorgarlik ko'rmoqda.\n\n"
                    f"📅 Sizni kutamiz: <b>{escape(booking_datetime)}</b>\n\n"
                    "Maestro'da ko'rishguncha! ✂️"
                ),
            }[client_lang],
            parse_mode="HTML",
        )
    except Exception as e:
        logging.warning("notify.approve_failed booking_id=%s error=%s", booking_id, e)

    await cb.message.edit_text(card, reply_markup=None, parse_mode="HTML")
    await cb.answer("Готово")

@router.callback_query(F.data.startswith("decline_"))
async def decline_booking(cb: CallbackQuery):
    booking_id = int(cb.data.split("_")[-1])
    lang = await get_user_lang(cb.from_user.id)

    async with db.async_session() as session:
        booking = await load_booking_for_stylist(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        if booking.status != BOOKING_PENDING:
            await cb.answer(texts.get_text("booking_already_handled", lang), show_alert=True)
            return

        booking.status = BOOKING_DECLINED
        await session.commit()
        client_lang = booking.user.language_code or "ru"
        client_telegram_id = booking.user.telegram_id
        booking_datetime = timeutils.format_human(booking.starts_at, client_lang)
        card = build_booking_card(booking, texts.get_text("booking_declined", lang), lang)

    try:
        await bot.send_message(
            chat_id=client_telegram_id,
            text={
                "ru": (
                    "<b>Запись отклонена.</b>\n\n"
                    f"Время {escape(booking_datetime)} уже недоступно. Пожалуйста, выберите другое."
                ),
                "uz": (
                    "<b>Yozuv rad etildi.</b>\n\n"
                    f"{escape(booking_datetime)} vaqti endi mavjud emas. Iltimos, boshqa vaqtni tanlang."
                ),
            }[client_lang],
            parse_mode="HTML",
        )
    except Exception as e:
        logging.warning("notify.decline_failed booking_id=%s error=%s", booking_id, e)

    await cb.message.edit_text(card, reply_markup=None, parse_mode="HTML")
    await cb.answer("Готово")

@router.callback_query(F.data.startswith("complete_"))
async def complete_booking(cb: CallbackQuery):
    booking_id = int(cb.data.split("_")[1])
    lang = await get_user_lang(cb.from_user.id)

    async with db.async_session() as session:
        booking = await load_booking_for_stylist(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        if booking.status == BOOKING_COMPLETED:
            await cb.answer(texts.get_text("booking_already_completed", lang), show_alert=True)
            return

        booking.status = BOOKING_COMPLETED
        await session.commit()
        client_lang = booking.user.language_code or "ru"
        client_telegram_id = booking.user.telegram_id
        card = build_booking_card(booking, texts.get_text("booking_completed", lang), lang)

    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="★", callback_data=f"rate_{booking_id}_1"),
            InlineKeyboardButton(text="★★", callback_data=f"rate_{booking_id}_2"),
            InlineKeyboardButton(text="★★★", callback_data=f"rate_{booking_id}_3"),
            InlineKeyboardButton(text="★★★★", callback_data=f"rate_{booking_id}_4"),
            InlineKeyboardButton(text="★★★★★", callback_data=f"rate_{booking_id}_5"),
        ]])
        await bot.send_message(
            chat_id=client_telegram_id,
            text={
                "ru": "Как вам сервис? Пожалуйста, оцените визит.",
                "uz": "Xizmat sizga yoqdimi? Iltimos, baho bering.",
            }[client_lang],
            reply_markup=kb,
        )
    except Exception as e:
        logging.warning("notify.rating_request_failed booking_id=%s error=%s", booking_id, e)

    await cb.message.edit_text(card, reply_markup=None, parse_mode="HTML")
    await cb.answer("Готово")
