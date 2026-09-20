"""
Запись офлайн-клиента.

Клиент, пришедший с улицы или позвонивший, существовал только в голове мастера:
занять его время в боте было нечем, и бот продолжал предлагать этот слот другим.

Шаги те же, что у клиента: услуга, дата, время. Разница в том, что подтверждать
нечего — мастер и есть тот, кто подтверждает, поэтому запись сразу approved
и сразу занимает слот в частичном индексе uq_active_booking_slot.

Префикс offbk_ уводит нажатия мимо клиентских хендлеров: «offbk_date_...»
не подходит под фильтр startswith("date_"), хотя календарь тот же самый.
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

import database as db
import texts
import timeutils
import utils
from guards import (
    ensure_active_stylist_callback,
    ensure_active_stylist_message,
    get_user_lang,
)
from services.booking import (
    build_offline_booking,
    get_available_dates_for_month,
    get_available_slots_for_date,
    normalize_guest_name,
)
from states import OfflineBookingForm

router = Router(name="stylist_offline_booking")

CALENDAR_PREFIX = "offbk_"


def _skip_name_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=texts.get_text("kb_offline_skip_name", lang), callback_data="offbk_skip_name"
        )
    ]])


async def _show_calendar(cb: CallbackQuery, stylist_id: int, service_id: int, lang: str,
                         year: int, month: int) -> None:
    async with db.async_session() as session:
        available = await get_available_dates_for_month(
            session, stylist_id, service_id, year, month
        )

    if not available:
        await cb.answer(texts.get_text("offline_no_free_dates", lang), show_alert=True)
        return

    await cb.message.edit_text(
        texts.get_text("offline_pick_date", lang),
        reply_markup=utils.generate_calendar(
            year, month, stylist_id, available,
            prefix=CALENDAR_PREFIX, back_callback="offbk_new", lang=lang,
        ),
    )
    await cb.answer()


@router.callback_query(F.data == "offbk_new")
async def offline_pick_service(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    await state.clear()

    async with db.async_session() as session:
        services = (await session.execute(
            select(db.Service)
            .where(db.Service.stylist_id == stylist.id)
            .options(joinedload(db.Service.catalog_service))
        )).scalars().all()

    if not services:
        # Длительность записи берётся из услуги: без неё непонятно, сколько
        # времени занимать, и отправлять мастера гадать не нужно.
        await cb.answer(texts.get_text("offline_no_services", lang), show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(
            text=f"{service.catalog_service.name} · "
                 f"{texts.get_text('buffer_minutes', lang).format(minutes=service.duration_min)}",
            callback_data=f"offbk_srv_{service.id}",
        )]
        for service in services
    ]
    await cb.message.edit_text(
        texts.get_text("offline_pick_service", lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("offbk_srv_"))
async def offline_pick_date(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    service_id = int(cb.data.split("_")[-1])

    async with db.async_session() as session:
        # service_id приходит из callback_data: сверяем, что услуга своя.
        service = await session.scalar(
            select(db.Service).where(
                db.Service.id == service_id, db.Service.stylist_id == stylist.id
            )
        )
    if not service:
        await cb.answer(texts.get_text("fallback_button_outdated", lang), show_alert=True)
        return

    await state.update_data(offline_service_id=service_id)
    now = timeutils.now()
    await _show_calendar(cb, stylist.id, service_id, lang, now.year, now.month)


@router.callback_query(F.data.startswith("offbk_cal_"))
async def offline_switch_month(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    service_id = (await state.get_data()).get("offline_service_id")
    if not service_id:
        await cb.answer(texts.get_text("schedule_session_expired", lang), show_alert=True)
        return

    period = cb.data.split("_")[2]
    year, month = (int(part) for part in period.split("-"))
    await _show_calendar(cb, stylist.id, service_id, lang, year, month)


@router.callback_query(F.data.startswith("offbk_dayoff_"))
async def offline_dayoff_notice(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    await cb.answer(texts.get_text("offline_no_free_slots", lang), show_alert=True)


@router.callback_query(F.data.startswith("offbk_date_"))
async def offline_pick_time(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    date_str = cb.data.split("_")[-1]
    service_id = (await state.get_data()).get("offline_service_id")
    if not service_id:
        await cb.answer(texts.get_text("schedule_session_expired", lang), show_alert=True)
        return

    selected_date = timeutils.parse_slot(f"{date_str} 00:00").date()
    async with db.async_session() as session:
        _, slots = await get_available_slots_for_date(
            session, stylist.id, service_id, selected_date
        )

    if not slots:
        await cb.answer(texts.get_text("offline_no_free_slots", lang), show_alert=True)
        return

    await state.update_data(offline_date=date_str)
    buttons, row = [], []
    for slot in slots:
        row.append(InlineKeyboardButton(text=slot, callback_data=f"offbk_time_{slot}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(
        text=texts.get_text("kb_back", lang), callback_data=f"offbk_srv_{service_id}"
    )])

    await cb.message.edit_text(
        texts.get_text("offline_pick_time", lang).format(date=date_str),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("offbk_time_"))
async def offline_ask_name(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    _, _, slot = cb.data.split("_", 2)
    data = await state.get_data()
    if not data.get("offline_service_id") or not data.get("offline_date"):
        await cb.answer(texts.get_text("schedule_session_expired", lang), show_alert=True)
        return

    await state.update_data(offline_time=slot)
    await state.set_state(OfflineBookingForm.guest_name)
    await cb.message.edit_text(
        texts.get_text("offline_ask_name", lang).format(
            slot=f"{data['offline_date']} {slot}"
        ),
        reply_markup=_skip_name_kb(lang),
    )
    await cb.answer()


async def _save(target, stylist_id: int, state: FSMContext, lang: str,
                guest_name: str | None) -> None:
    """
    Общий финал для обоих путей: с именем и без.

    Свободен ли слот, проверяется ещё раз — между показом списка и нажатием
    клиент мог занять это время сам. Гонку добивает частичный уникальный
    индекс: на него и рассчитан except IntegrityError.
    """
    data = await state.get_data()
    service_id = data.get("offline_service_id")
    date_str = data.get("offline_date")
    slot = data.get("offline_time")
    if not (service_id and date_str and slot):
        await state.clear()
        await target.answer(texts.get_text("schedule_session_expired", lang))
        return

    selected_date = timeutils.parse_slot(f"{date_str} 00:00").date()
    async with db.async_session() as session:
        service = await session.scalar(
            select(db.Service).where(
                db.Service.id == service_id, db.Service.stylist_id == stylist_id
            )
        )
        if not service:
            await state.clear()
            await target.answer(texts.get_text("fallback_button_outdated", lang))
            return

        _, slots = await get_available_slots_for_date(
            session, stylist_id, service_id, selected_date
        )
        if slot not in slots:
            await state.clear()
            await target.answer(texts.get_text("offline_slot_taken", lang))
            return

        booking = build_offline_booking(
            stylist_id, service, timeutils.parse_slot(f"{date_str} {slot}"), guest_name
        )
        session.add(booking)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logging.info(
                "offline_booking.slot_race stylist_id=%s datetime=%s",
                stylist_id, f"{date_str} {slot}",
            )
            await state.clear()
            await target.answer(texts.get_text("offline_slot_taken", lang))
            return
        booking_id = booking.id
        saved_name = booking.guest_name

    await state.clear()
    logging.info("offline_booking.created booking_id=%s stylist_id=%s", booking_id, stylist_id)
    await target.answer(
        texts.get_text("offline_saved", lang).format(
            slot=f"{date_str} {slot}",
            name=saved_name or texts.get_text("offline_guest_unnamed", lang),
        )
    )


@router.callback_query(OfflineBookingForm.guest_name, F.data == "offbk_skip_name")
async def offline_save_without_name(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    await _save(cb.message, stylist.id, state, lang, None)
    await cb.answer()


@router.message(OfflineBookingForm.guest_name)
async def offline_save_with_name(message: Message, state: FSMContext):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(message.from_user.id)
    await _save(message, stylist.id, state, lang, normalize_guest_name(message.text))
