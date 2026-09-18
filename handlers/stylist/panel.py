"""
Панель мастера: вход, выход, срок тарифа.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    Message,
)
from sqlalchemy import select

import database as db
import texts
from guards import get_user_lang
from keyboards import (
    get_main_keyboard,
)
from presenters import (
    get_subscription_menu_text,
)
from services.access import (
    is_stylist_subscription_active,
)

router = Router(name="stylist_panel")


# Вход в панель мастера
@router.message(Command("admin"))
async def admin_panel(message: Message):
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))

    lang = user.language_code if user and user.language_code else "ru"
    keyboard = await get_main_keyboard(message.from_user.id)
    if user and user.role == "stylist" and not is_stylist_subscription_active(user):
        await message.answer(
            get_subscription_menu_text(user, lang), parse_mode="HTML", reply_markup=keyboard
        )
        return

    # Раньше здесь печатались оба языка сразу — мастер видел приветствие дважды.
    await message.answer(texts.get_text("panel_welcome", lang), reply_markup=keyboard)

@router.message(F.text.in_(texts.all_variants("exit_panel")))
async def exit_admin_panel(message: Message):
    lang = await get_user_lang(message.from_user.id)
    await message.answer(
        texts.get_text("panel_exited", lang),
        reply_markup=await get_main_keyboard(message.from_user.id),
    )

@router.message(F.text.in_(texts.all_variants("subscription")))
async def show_tariff_status(message: Message):
    lang = await get_user_lang(message.from_user.id)
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))
    await message.answer(get_subscription_menu_text(user, lang), parse_mode="HTML", reply_markup=await get_main_keyboard(message.from_user.id))
