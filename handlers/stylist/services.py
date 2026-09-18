"""
Услуги мастера: список, добавление, удаление.
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
from guards import (
    ensure_active_stylist_callback,
    ensure_active_stylist_message,
    get_user_lang,
)
from keyboards import (
    get_main_keyboard,
)
from states import ServiceForm

router = Router(name="stylist_services")


@router.message(F.text.in_(texts.all_variants("my_services")))
async def manage_services(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    lang = user.language_code or "ru"
    async with db.async_session() as session:
        query = select(db.Service).where(db.Service.stylist_id == stylist.id).options(joinedload(db.Service.catalog_service))
        services = (await session.execute(query)).scalars().all()
    if services:
        response_text = (
            f"<b>{texts.get_text('services_title', lang)}</b>\n"
            f"{texts.get_text('services_subtitle', lang)}\n\n"
        )
    else:
        response_text = texts.get_text("services_empty", lang) + "\n\n"

    minutes = texts.get_text("services_minutes_short", lang)
    for s in services:
        response_text += (
            f"• {escape(s.catalog_service.name)} - {s.price:,.0f} so'm "
            f"({s.duration_min} {minutes})\n"
        )
    kb_builder = []
    for s in services:
        kb_builder.append([InlineKeyboardButton(
            text=texts.get_text("services_delete", lang).format(name=s.catalog_service.name),
            callback_data=f"del_srv_{s.id}",
        )])
    kb_builder.append([InlineKeyboardButton(
        text=texts.get_text("services_add_new", lang), callback_data="add_service"
    )])
    keyboard = InlineKeyboardMarkup(inline_keyboard=kb_builder)
    await message.answer(response_text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.startswith("del_srv_"))
async def delete_service(cb: CallbackQuery):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        return

    service_id = int(cb.data.split("_")[2])
    lang = user.language_code or "ru"
    async with db.async_session() as session:
        try:
            service = await session.get(db.Service, service_id)
            if service and service.stylist_id == stylist.id:
                await session.delete(service)
                await session.commit()
                await cb.answer(texts.get_text("services_deleted", lang), show_alert=True)
                # Обновляем список услуг
                await manage_services(cb.message) 
            else:
                await cb.answer(texts.get_text("services_not_found", lang), show_alert=True)
        except Exception as e:
            await session.rollback()
            # Если есть связанные записи, выскочит ошибка
            await cb.answer(texts.get_text("services_delete_blocked", lang), show_alert=True)
            logging.warning("service.delete_failed service_id=%s error=%s", service_id, e)

@router.callback_query(F.data == "add_service")
async def add_service_start(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = user.language_code or "ru"
    async with db.async_session() as session:
        catalog_services = (await session.execute(select(db.CatalogService))).scalars().all()
    btns = [[InlineKeyboardButton(text=s.name, callback_data=f"cat_srv_{s.id}")] for s in catalog_services]
    btns.append([InlineKeyboardButton(
        text=texts.get_text("kb_cancel", lang), callback_data="cancel_fsm"
    )])
    await state.set_state(ServiceForm.name)
    await cb.message.edit_text(
        texts.get_text("services_choose_catalog", lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
    )
    await cb.answer()

@router.callback_query(ServiceForm.name, F.data.startswith("cat_srv_"))
async def process_service_catalog_choice(cb: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(cb.from_user.id)
    catalog_id = int(cb.data.split("_")[2])
    await state.update_data(catalog_id=catalog_id)
    await state.set_state(ServiceForm.price)
    await cb.message.edit_text(texts.get_text("services_ask_price", lang))
    await cb.answer()

@router.message(ServiceForm.price)
async def process_service_price(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    if not message.text.isdigit():
        await message.answer(texts.get_text("services_price_invalid", lang))
        return
    await state.update_data(price=int(message.text))
    await state.set_state(ServiceForm.duration)

    def duration_button(minutes: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=texts.get_text("services_duration_option", lang).format(minutes=minutes),
            callback_data=f"dur_{minutes}",
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [duration_button(30), duration_button(45)],
        [duration_button(60), duration_button(90)],
    ])
    await message.answer(texts.get_text("services_ask_duration", lang), reply_markup=kb)

@router.callback_query(ServiceForm.duration, F.data.startswith("dur_"))
async def process_service_duration_choice(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = user.language_code or "ru"
    duration = int(cb.data.split("_")[1])
    data = await state.get_data()
    async with db.async_session() as session:
        catalog_service = await session.get(db.CatalogService, data["catalog_id"])
        new_service = db.Service(catalog_service_id=data["catalog_id"], price=data["price"], duration_min=duration, stylist_id=stylist.id)
        session.add(new_service)
        await session.commit()
    await cb.message.delete()
    keyboard = await get_main_keyboard(cb.from_user.id)
    await cb.message.answer(
        texts.get_text("services_added", lang).format(name=catalog_service.name),
        reply_markup=keyboard,
    )
    await state.clear()
    await cb.answer()
