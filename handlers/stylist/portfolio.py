"""
Портфолио мастера.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import select

import database as db
import texts
from guards import (
    ensure_active_stylist_message,
    get_user_lang,
)
from keyboards import (
    get_main_keyboard,
)
from states import PortfolioForm

router = Router(name="stylist_portfolio")


@router.message(F.text.in_(texts.all_variants("my_portfolio")))
async def manage_portfolio(message: Message, state: FSMContext):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    async with db.async_session() as session:
        photos = (await session.execute(
            select(db.Portfolio)
            .where(db.Portfolio.stylist_id == stylist.id)
            .order_by(db.Portfolio.id.desc())
            .limit(3)
        )).scalars().all()

    if photos:
        media_group = [InputMediaPhoto(media=photo.telegram_photo_file_id) for photo in photos]
        await message.answer_media_group(media=media_group)

    lang = user.language_code or "ru"
    await state.set_state(PortfolioForm.waiting_for_photo)
    await message.answer(
        texts.get_text("portfolio_prompt", lang).format(count=len(photos)),
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=texts.get_stylist_buttons(lang)["done"])]],
            resize_keyboard=True,
        ),
        parse_mode="HTML",
    )

@router.message(PortfolioForm.waiting_for_photo, F.photo)
async def process_portfolio_photo(message: Message, state: FSMContext):
    # Берём самое качественное фото из предложенных

    file_id = message.photo[-1].file_id

    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))
        stylist = await session.scalar(select(db.Stylist).where(db.Stylist.user_id == user.id))

        # Сохраняем file_id в базу
        new_photo = db.Portfolio(stylist_id=stylist.id, telegram_photo_file_id=file_id)
        session.add(new_photo)
        await session.commit()

    lang = await get_user_lang(message.from_user.id)
    await message.answer(texts.get_text("portfolio_photo_added", lang))

# Выход из режима добавления фото
@router.message(PortfolioForm.waiting_for_photo, F.text.in_(texts.all_variants("done")))
async def done_adding_photos(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    await message.answer(
        texts.get_text("portfolio_done", lang),
        reply_markup=await get_main_keyboard(message.from_user.id),
    )
