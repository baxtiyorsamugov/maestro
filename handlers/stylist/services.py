"""
Услуги мастера: список, добавление, удаление.
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
from sqlalchemy.orm import joinedload

import database as db
from guards import (
    ensure_active_stylist_callback,
    ensure_active_stylist_message,
)
from keyboards import (
    get_main_keyboard,
)
from states import ServiceForm

router = Router(name="stylist_services")


@router.message(F.text == "✂️ Мои услуги")
async def manage_services(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    async with db.async_session() as session:
        query = select(db.Service).where(db.Service.stylist_id == stylist.id).options(joinedload(db.Service.catalog_service))
        services = (await session.execute(query)).scalars().all()
    if services:
        response_text = "<b>\u0412\u0430\u0448\u0438 \u0443\u0441\u043b\u0443\u0433\u0438:</b>\n\u041a\u043b\u0438\u0435\u043d\u0442\u044b \u0432\u0438\u0434\u044f\u0442 \u0446\u0435\u043d\u0443 \u0438 \u0434\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c.\n\n"
    else:
        response_text = "\u0423 \u0432\u0430\u0441 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442 \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u043d\u044b\u0445 \u0443\u0441\u043b\u0443\u0433. \u0414\u0430\u0432\u0430\u0439\u0442\u0435 \u0441\u043e\u0437\u0434\u0430\u0434\u0438\u043c \u043f\u0435\u0440\u0432\u0443\u044e.\n\n"
    for s in services:
        response_text += f"\u2022 {s.catalog_service.name} - {s.price:,.0f} so'm ({s.duration_min} \u043c\u0438\u043d)\n"
    kb_builder = []
    for s in services:
        kb_builder.append([InlineKeyboardButton(text=f"\u0423\u0434\u0430\u043b\u0438\u0442\u044c: {s.catalog_service.name}", callback_data=f"del_srv_{s.id}")])
    kb_builder.append([InlineKeyboardButton(text="\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u043d\u043e\u0432\u0443\u044e \u0443\u0441\u043b\u0443\u0433\u0443", callback_data="add_service")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=kb_builder)
    await message.answer(response_text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.startswith("del_srv_"))
async def delete_service(cb: CallbackQuery):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        return

    service_id = int(cb.data.split("_")[2])
    async with db.async_session() as session:
        try:
            service = await session.get(db.Service, service_id)
            if service and service.stylist_id == stylist.id:
                await session.delete(service)
                await session.commit()
                await cb.answer("✅ Услуга успешно удалена", show_alert=True)
                # Обновляем список услуг
                await manage_services(cb.message) 
            else:
                await cb.answer("❌ Ошибка: услуга не найдена", show_alert=True)
        except Exception as e:
            await session.rollback()
            # Если есть связанные записи, выскочит ошибка
            await cb.answer("⚠️ Нельзя удалить услугу, на которую уже есть записи! Сначала удалите записи в профиле.", show_alert=True)
            logging.error(f"Ошибка удаления услуги: {e}")

@router.callback_query(F.data == "add_service")
async def add_service_start(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    async with db.async_session() as session:
        catalog_services = (await session.execute(select(db.CatalogService))).scalars().all()
    btns = [[InlineKeyboardButton(text=s.name, callback_data=f"cat_srv_{s.id}")] for s in catalog_services]
    btns.append([InlineKeyboardButton(text="Отмена", callback_data="cancel_fsm")])
    await state.set_state(ServiceForm.name)
    await cb.message.edit_text("Выберите тип услуги из каталога:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
    await cb.answer()

@router.callback_query(ServiceForm.name, F.data.startswith("cat_srv_"))
async def process_service_catalog_choice(cb: CallbackQuery, state: FSMContext):
    catalog_id = int(cb.data.split("_")[2])
    await state.update_data(catalog_id=catalog_id)
    await state.set_state(ServiceForm.price)
    await cb.message.edit_text("\u0422\u0435\u043f\u0435\u0440\u044c \u0443\u043a\u0430\u0436\u0438\u0442\u0435 \u0432\u0430\u0448\u0443 \u0446\u0435\u043d\u0443 \u0434\u043b\u044f \u044d\u0442\u043e\u0439 \u0443\u0441\u043b\u0443\u0433\u0438. \u0422\u043e\u043b\u044c\u043a\u043e \u0446\u0438\u0444\u0440\u044b:")
    await cb.answer()

@router.message(ServiceForm.price)
async def process_service_price(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430. \u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0446\u0435\u043d\u0443 \u0442\u043e\u043b\u044c\u043a\u043e \u0446\u0438\u0444\u0440\u0430\u043c\u0438.")
        return
    await state.update_data(price=int(message.text))
    await state.set_state(ServiceForm.duration)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="30 \u043c\u0438\u043d\u0443\u0442", callback_data="dur_30"), InlineKeyboardButton(text="45 \u043c\u0438\u043d\u0443\u0442", callback_data="dur_45")],
        [InlineKeyboardButton(text="60 \u043c\u0438\u043d\u0443\u0442", callback_data="dur_60"), InlineKeyboardButton(text="90 \u043c\u0438\u043d\u0443\u0442", callback_data="dur_90")],
    ])
    await message.answer("\u0426\u0435\u043d\u0430 \u043f\u0440\u0438\u043d\u044f\u0442\u0430. \u0422\u0435\u043f\u0435\u0440\u044c \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c \u0443\u0441\u043b\u0443\u0433\u0438:", reply_markup=kb)

@router.callback_query(ServiceForm.duration, F.data.startswith("dur_"))
async def process_service_duration_choice(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    duration = int(cb.data.split("_")[1])
    data = await state.get_data()
    async with db.async_session() as session:
        catalog_service = await session.get(db.CatalogService, data["catalog_id"])
        new_service = db.Service(catalog_service_id=data["catalog_id"], price=data["price"], duration_min=duration, stylist_id=stylist.id)
        session.add(new_service)
        await session.commit()
    await cb.message.delete()
    keyboard = await get_main_keyboard(cb.from_user.id)
    await cb.message.answer(f"Новая услуга '{catalog_service.name}' успешно добавлена.", reply_markup=keyboard)
    await state.clear()
    await cb.answer()
