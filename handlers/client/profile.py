"""
Профиль клиента: свои записи, отмена, избранные мастера, оценка визита.
"""
import logging
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
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
    BOOKING_CANCELLED,
    BOOKING_COMPLETED,
    BOOKING_DECLINED,
)
from guards import (
    deny_access,
    ensure_registered_message,
    get_user_lang,
)
from loader import bot
from services.access import (
    load_booking_for_client,
)
from services.booking import can_change_booking
from services.rating import recalculate_stylist_rating

router = Router(name="client_profile")


@router.message(F.text.in_([texts.get_buttons("ru")["my_profile"], texts.get_buttons("uz")["my_profile"]]))
async def show_profile(message: Message, state: FSMContext):
    # ПЕРВЫМ ДЕЛОМ ЧИСТИМ ВСЁ
    await state.clear()
    
    user = await ensure_registered_message(message)
    if not user:
        return

    user_id = message.from_user.id
    lang = user.language_code or "ru"

    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == user_id))
        query = (
            select(db.Booking)
                .where(db.Booking.user_id == user.id)
                .options(
                    joinedload(db.Booking.stylist).joinedload(db.Stylist.barbershop),
                    joinedload(db.Booking.service).joinedload(db.Service.catalog_service)
                )
                .order_by(db.Booking.starts_at.desc())
        )
        bookings = (await session.execute(query)).scalars().all()

    lang_label = texts.get_text("profile_lang_ru", lang) if user.language_code == "ru" else texts.get_text("profile_lang_uz", lang)
    profile_header = (
        f"👤 <b>{escape(user.first_name or '')}</b>\n"
        f"📞 <code>{user.phone_number}</code>\n"
        f"🌐 {lang_label}\n\n"
    )

    if not bookings:
        await message.answer(profile_header + f"📭 {texts.get_text('profile_empty', lang)}", parse_mode="HTML")
        return

    response_text = profile_header + f"{texts.get_text('profile_bookings_title', lang)}\n{'=' * 20}\n"
    kb_builder = []

    for booking in bookings:
        status_icon = texts.get_text("status_pending", lang)
        if booking.status == BOOKING_APPROVED:
            status_icon = texts.get_text("status_approved", lang)
        elif booking.status == BOOKING_DECLINED:
            status_icon = texts.get_text("status_declined", lang)
        elif booking.status == BOOKING_COMPLETED:
            status_icon = texts.get_text("status_completed", lang)
        elif booking.status == BOOKING_CANCELLED:
            status_icon = texts.get_text("status_cancelled", lang)

        response_text += (
            f"\n<b>{timeutils.format_human(booking.starts_at, lang)}</b>\n"
            f"Барбершоп: {escape(booking.stylist.barbershop.name)}\n"
            f"{texts.get_text('master_label', lang)}: {escape(booking.stylist.name)}\n"
            f"\u0423\u0441\u043b\u0443\u0433\u0430: {escape(booking.service.catalog_service.name)} ({booking.service.price:,.0f} so'm)\n"
            f"{texts.get_text('status_label', lang)}: <b>{status_icon}</b>\n"
            f"{'-' * 20}\n"
        )
        if booking.status in ACTIVE_BOOKING_STATUSES:
            slot_label = timeutils.format_human(booking.starts_at, lang)
            # Перенос закрывается за CHANGE_WINDOW_HOURS до визита: мастеру нужно
            # время, чтобы перестроить день. Отмена остаётся доступной до конца —
            # предупреждённый мастер всё же лучше, чем клиент, который просто не
            # пришёл и ничего не сказал.
            if can_change_booking(booking)[0]:
                kb_builder.append([InlineKeyboardButton(
                    text=f"{texts.get_text('reschedule_booking', lang)}: {slot_label}",
                    callback_data=f"reschedule_{booking.id}",
                )])
            kb_builder.append([InlineKeyboardButton(
                text=f"{texts.get_text('cancel_booking', lang)}: {slot_label}",
                callback_data=f"booking_cancel_{booking.id}",
            )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=kb_builder)
    await message.answer(response_text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.startswith("booking_cancel_"))
async def cancel_booking(cb: CallbackQuery):
    booking_id = int(cb.data.split("_")[-1])
    lang = await get_user_lang(cb.from_user.id)

    async with db.async_session() as session:
        # Отменить запись может только сам клиент — владельца сверяем в запросе.
        booking = await load_booking_for_client(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        if booking.status in (BOOKING_DECLINED, BOOKING_COMPLETED):
            await cb.answer(
                {"ru": "Эту запись уже нельзя отменить.", "uz": "Bu yozuvni endi bekor qilib bo'lmaydi."}[lang],
                show_alert=True,
            )
            return

        stylist_telegram_id = (
            booking.stylist.user_account.telegram_id
            if booking.stylist and booking.stylist.user_account
            else None
        )
        client_name = booking.user.first_name or "Клиент"
        booking_datetime = timeutils.format_slot(booking.starts_at)

        # Статус вместо удаления: история визитов нужна для статистики и follow-up.
        booking.status = BOOKING_CANCELLED
        await session.commit()

    if stylist_telegram_id:
        notification_text = (
            "<b>Запись отменена</b>\n\n"
            f"Клиент: {escape(client_name)}\n"
            f"Дата и время: {escape(booking_datetime)}\n\n"
            "Это окно снова свободно для записи."
        )
        try:
            await bot.send_message(chat_id=stylist_telegram_id, text=notification_text, parse_mode="HTML")
        except Exception as e:
            logging.warning("notify.cancel_failed booking_id=%s error=%s", booking_id, e)

    await cb.answer({"ru": "Запись отменена.", "uz": "Yozuv bekor qilindi."}[lang], show_alert=True)
    await cb.message.delete()
    await cb.message.answer(
        {"ru": "Ваша запись успешно отменена.", "uz": "Yozuvingiz muvaffaqiyatli bekor qilindi."}[lang]
    )

# Хэндлер для кнопки "⭐ Мои мастера"
@router.message(F.text.in_([texts.get_buttons("ru")["my_masters"], texts.get_buttons("uz")["my_masters"]]))
async def show_favorites(message: Message, state: FSMContext):
    # ПЕРВЫМ ДЕЛОМ ЧИСТИМ ВСЁ
    await state.clear()
    
    user = await ensure_registered_message(message)
    if not user:
        return

    lang = user.language_code or "ru"
    async with db.async_session() as session:
        user = await session.scalar(
            select(db.User)
                .where(db.User.telegram_id == message.from_user.id)
                .options(joinedload(db.User.favorite_stylists))
        )

    if not user or not user.favorite_stylists:
        await message.answer(texts.get_text("favorites_empty", lang))
        return

    btns = [[InlineKeyboardButton(text=f"💇‍♂️ {stylist.name}", callback_data=f"stylist_{stylist.id}"), 
             InlineKeyboardButton(text="❌", callback_data=f"fav_rem_{stylist.id}")] for stylist in user.favorite_stylists]
    
    await message.answer(
        f"<b>{texts.get_text('favorites_title', lang)}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
        parse_mode="HTML"
    )

# Хэндлер для добавления в избранное
@router.callback_query(F.data.startswith("fav_add_"))
async def add_favorite(cb: CallbackQuery):
    stylist_id = int(cb.data.split("_")[2])
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == cb.from_user.id))

        # Проверяем, нет ли уже в избранном
        existing = await session.scalar(
            select(db.Favorite).where(db.Favorite.user_id == user.id, db.Favorite.stylist_id == stylist_id))
        if not existing:
            session.add(db.Favorite(user_id=user.id, stylist_id=stylist_id))
            await session.commit()
            await cb.answer("\n Мастер добавлен в избранное!", show_alert=True)
        else:
            await cb.answer("Этот мастер уже в избранном.", show_alert=True)

# Хэндлер для удаления из избранного
@router.callback_query(F.data.startswith("fav_rem_"))
async def remove_favorite(cb: CallbackQuery):
    stylist_id = int(cb.data.split("_")[2])
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == cb.from_user.id))
        fav_to_delete = await session.scalar(
            select(db.Favorite).where(db.Favorite.user_id == user.id, db.Favorite.stylist_id == stylist_id))
        if fav_to_delete:
            await session.delete(fav_to_delete)
            await session.commit()
            await cb.answer("Мастер удален из избранного.", show_alert=True)
            # Обновляем сообщение со списком
            await show_favorites(cb.message)
            await cb.message.delete()

@router.callback_query(F.data.startswith("rate_"))
async def handle_rating(cb: CallbackQuery):
    booking_id, rating = map(int, cb.data.split("_")[1:])
    if not 1 <= rating <= 5:
        await cb.answer("Некорректная оценка.", show_alert=True)
        return

    async with db.async_session() as session:
        # Оценить визит может только клиент этой записи.
        booking = await load_booking_for_client(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        if booking.status != BOOKING_COMPLETED:
            await cb.answer("Оценить можно только завершённый визит.", show_alert=True)
            return
        if booking.rating is not None:
            await cb.message.edit_text("Вы уже оставили оценку.")
            await cb.answer()
            return

        booking.rating = rating
        await session.commit()
        await recalculate_stylist_rating(session, booking.stylist_id)

        await cb.message.edit_text(f"Спасибо за вашу оценку: {rating} ★")

    await cb.answer()
