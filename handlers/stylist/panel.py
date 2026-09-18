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


# В
# од в админ-панель
@router.message(Command("admin"))
async def admin_panel(message: Message):
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))

    keyboard = await get_main_keyboard(message.from_user.id)
    if user and user.role == "stylist" and not is_stylist_subscription_active(user):
        await message.answer(get_subscription_menu_text(user), parse_mode="HTML", reply_markup=keyboard)
        return

    await message.answer(
        " Boshqaruv paneliga xush kelibsiz! Ishlaringizga rivoj!\n\n"
        "Добро пожаловать в панель управления! Успехов в работе!",
        reply_markup=keyboard,
    )

@router.message(F.text == "↩️ Выйти из админ-панели")
async def exit_admin_panel(message: Message):
    await message.answer("Вы вернулись в главное меню.", reply_markup=await get_main_keyboard(message.from_user.id))

@router.message(F.text == "💳 Срок тарифа")
async def show_tariff_status(message: Message):
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))
    await message.answer(get_subscription_menu_text(user), parse_mode="HTML", reply_markup=await get_main_keyboard(message.from_user.id))
