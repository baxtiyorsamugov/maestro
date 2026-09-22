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
    ensure_registered_callback,
    ensure_registered_message,
    get_user_lang,
)
from loader import bot
from services import audit
from services.access import (
    load_booking_for_client,
)
from services.booking import booking_price, can_change_booking
from services.rating import recalculate_stylist_rating
from services.reviews import REVIEW_MAX_LEN, can_leave_review, normalize_review
from states import ReviewForm

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
            f"{texts.get_text('booking_barbershop', lang)}: {escape(booking.stylist.barbershop.name)}\n"
            f"{texts.get_text('master_label', lang)}: {escape(booking.stylist.name)}\n"
            f"{texts.get_text('booking_service', lang)}: "
            f"{escape(booking.service.catalog_service.name)} ({booking_price(booking):,.0f} so'm)\n"
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
            await cb.answer(texts.get_text("booking_cannot_cancel", lang), show_alert=True)
            return

        stylist_account = booking.stylist.user_account if booking.stylist else None
        stylist_telegram_id = stylist_account.telegram_id if stylist_account else None
        # Уведомление читает мастер — значит, и язык его, а не клиента.
        stylist_lang = (stylist_account.language_code if stylist_account else None) or "ru"
        client_name = booking.user.first_name or texts.get_text("booking_client", stylist_lang)
        booking_datetime = timeutils.format_slot(booking.starts_at)

        # Статус вместо удаления: история визитов нужна для статистики и follow-up.
        booking.status = BOOKING_CANCELLED
        # Тем же commit'ом, что и смена статуса: иначе при сбое между ними
        # отмена есть, а следа нет — ровно тот случай, ради которого журнал
        # и читают («кто отменил эту запись и когда»).
        audit.record_client(
            session, audit.BOOKING_CANCELLED, booking,
            details=booking_datetime,
        )
        await session.commit()

    if stylist_telegram_id:
        notification_text = texts.get_text("booking_cancelled_notice_stylist", stylist_lang).format(
            client_label=texts.get_text("booking_client", stylist_lang),
            client=escape(client_name),
            datetime_label=texts.get_text("booking_datetime", stylist_lang),
            slot=escape(booking_datetime),
        )
        try:
            await bot.send_message(chat_id=stylist_telegram_id, text=notification_text, parse_mode="HTML")
        except Exception as e:
            logging.warning("notify.cancel_failed booking_id=%s error=%s", booking_id, e)

    await cb.answer(texts.get_text("booking_cancelled_toast", lang), show_alert=True)
    await cb.message.delete()
    await cb.message.answer(texts.get_text("booking_cancelled_client", lang))

# Хэндлер для кнопки "⭐ Мои мастера"
@router.message(F.text.in_([texts.get_buttons("ru")["my_masters"], texts.get_buttons("uz")["my_masters"]]))
async def show_favorites(message: Message, state: FSMContext):
    # ПЕРВЫМ ДЕЛОМ ЧИСТИМ ВСЁ
    await state.clear()
    
    user = await ensure_registered_message(message)
    if not user:
        return

    lang = user.language_code or "ru"
    text, keyboard = await _favorites_view(message.from_user.id, lang)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


async def _favorites_view(telegram_id: int, lang: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """
    Экран «Мои мастера»: текст и клавиатура.

    Отдельно от хендлера, потому что экран собирают двое: кнопка меню
    и удаление мастера из списка. Раньше удаление звало show_favorites()
    с сообщением бота и без state — то есть падало с TypeError, а даже
    с state проверка регистрации смотрела бы на from_user бота.
    """
    async with db.async_session() as session:
        user = await session.scalar(
            select(db.User)
            .where(db.User.telegram_id == telegram_id)
            .options(joinedload(db.User.favorite_stylists))
        )

    if not user or not user.favorite_stylists:
        return texts.get_text("favorites_empty", lang), None

    btns = [
        [
            InlineKeyboardButton(text=f"💇‍♂️ {stylist.name}", callback_data=f"stylist_{stylist.id}"),
            InlineKeyboardButton(text="❌", callback_data=f"fav_rem_{stylist.id}"),
        ]
        for stylist in user.favorite_stylists
    ]
    return (
        f"<b>{texts.get_text('favorites_title', lang)}</b>",
        InlineKeyboardMarkup(inline_keyboard=btns),
    )


@router.callback_query(F.data.startswith("fav_add_"))
async def add_favorite(cb: CallbackQuery):
    stylist_id = int(cb.data.split("_")[2])
    # Незарегистрированный человек мог нажать кнопку из пересланной карточки:
    # раньше это было AttributeError на user.id и «часики» без ответа.
    user = await ensure_registered_callback(cb)
    if not user:
        return
    lang = user.language_code or "ru"

    async with db.async_session() as session:
        stylist = await session.get(db.Stylist, stylist_id)
        if not stylist:
            await cb.answer(texts.get_text("stylist_not_found", lang), show_alert=True)
            return
        existing = await session.scalar(
            select(db.Favorite).where(db.Favorite.user_id == user.id, db.Favorite.stylist_id == stylist_id)
        )
        if existing:
            await cb.answer(texts.get_text("favorite_already", lang), show_alert=True)
            return
        session.add(db.Favorite(user_id=user.id, stylist_id=stylist_id))
        await session.commit()

    await cb.answer(texts.get_text("favorite_added", lang), show_alert=True)


@router.callback_query(F.data.startswith("fav_rem_"))
async def remove_favorite(cb: CallbackQuery):
    stylist_id = int(cb.data.split("_")[2])
    user = await ensure_registered_callback(cb)
    if not user:
        return
    lang = user.language_code or "ru"

    async with db.async_session() as session:
        # Удаляем только из своего списка: user_id берётся из базы по
        # отправителю, а не из callback_data.
        favorite = await session.scalar(
            select(db.Favorite).where(db.Favorite.user_id == user.id, db.Favorite.stylist_id == stylist_id)
        )
        if favorite:
            await session.delete(favorite)
            await session.commit()

    # Список перерисовывается на месте, даже если мастера там уже не было
    # (двойное нажатие): человек видит актуальное состояние, а не ошибку.
    text, keyboard = await _favorites_view(cb.from_user.id, lang)
    await cb.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await cb.answer(texts.get_text("favorite_removed", lang))

@router.callback_query(F.data.startswith("rate_"))
async def handle_rating(cb: CallbackQuery, state: FSMContext):
    booking_id, rating = map(int, cb.data.split("_")[1:])
    lang = await get_user_lang(cb.from_user.id)
    if not 1 <= rating <= 5:
        await cb.answer(texts.get_text("rating_invalid", lang), show_alert=True)
        return

    async with db.async_session() as session:
        # Оценить визит может только клиент этой записи.
        booking = await load_booking_for_client(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        if booking.status != BOOKING_COMPLETED:
            await cb.answer(
                texts.get_text("review_denied_not_completed", lang), show_alert=True
            )
            return
        if booking.rating is not None:
            await cb.message.edit_text(texts.get_text("rating_already_left", lang))
            await cb.answer()
            return

        booking.rating = rating
        await session.commit()
        await recalculate_stylist_rating(session, booking.stylist_id)

    # Звёзды сразу после оценки: человек видит, что именно он поставил.
    stars = "★" * rating
    await state.set_state(ReviewForm.text)
    await state.update_data(review_booking_id=booking_id)
    await cb.message.edit_text(
        texts.get_text("rating_thanks", lang).format(stars=stars),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=texts.get_text("kb_write_review", lang),
                callback_data=f"review_write_{booking_id}",
            ),
            InlineKeyboardButton(
                text=texts.get_text("kb_skip_review", lang),
                callback_data="review_skip",
            ),
        ]]),
    )
    await cb.answer()


@router.callback_query(F.data == "review_skip")
async def skip_review(cb: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(cb.from_user.id)
    await state.clear()
    await cb.message.edit_text(texts.get_text("review_skipped", lang))
    await cb.answer()


@router.callback_query(F.data.startswith("review_write_"))
async def ask_for_review(cb: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(cb.from_user.id)
    booking_id = int(cb.data.split("_")[-1])

    async with db.async_session() as session:
        # Идентификатор из callback_data — недоверенный ввод.
        booking = await load_booking_for_client(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return
        allowed, reason = can_leave_review(booking)

    if not allowed:
        await state.clear()
        await cb.answer(texts.get_text(reason, lang), show_alert=True)
        return

    await state.set_state(ReviewForm.text)
    await state.update_data(review_booking_id=booking_id)
    await cb.message.edit_text(
        texts.get_text("review_prompt", lang).format(limit=REVIEW_MAX_LEN)
    )
    await cb.answer()


@router.message(ReviewForm.text)
async def save_review(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    booking_id = (await state.get_data()).get("review_booking_id")
    if not booking_id:
        await state.clear()
        await message.answer(texts.get_text("booking_session_expired", lang))
        return

    text = normalize_review(message.text)
    if not text:
        # Состояние не сбрасываем: человек просто отправил пустое сообщение
        # или стикер, и выкидывать его из формы за это незачем.
        await message.answer(texts.get_text("review_empty", lang))
        return

    async with db.async_session() as session:
        booking = await load_booking_for_client(session, booking_id, message.from_user.id)
        if not booking:
            await state.clear()
            await message.answer(texts.get_text("booking_session_expired", lang))
            return
        allowed, reason = can_leave_review(booking)
        if not allowed:
            await state.clear()
            await message.answer(texts.get_text(reason, lang))
            return

        booking.review_text = text
        await session.commit()

    await state.clear()
    logging.info("review.saved booking_id=%s length=%s", booking_id, len(text))
    await message.answer(texts.get_text("review_saved", lang))
