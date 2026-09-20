"""
Карточка мастера глазами самого мастера.

До этого в карточке были только имя, рейтинг и адрес салона: все мастера
выглядели одинаково, и выбирать клиенту было не по чему. Здесь мастер
заполняет то, что его отличает, — пару строк о себе и фото.

Фото хранится как file_id Telegram, а не как файл: перезаливать своё же
изображение на каждый показ карточки незачем, а file_id живёт, пока жив бот.
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

import database as db
import texts
from guards import (
    ensure_active_stylist_callback,
    ensure_active_stylist_message,
    get_user_lang,
)
from services.stylist_profile import ABOUT_MAX_LEN, normalize_about
from states import StylistProfileForm

router = Router(name="stylist_profile_card")


def _card_keyboard(lang: str, has_about: bool, has_photo: bool) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(
            text=texts.get_text("kb_edit_about", lang), callback_data="scard_about"
        ),
        InlineKeyboardButton(
            text=texts.get_text("kb_edit_photo", lang), callback_data="scard_photo"
        ),
    ]]
    # Кнопки очистки показываем только когда есть что очищать: иначе они
    # висят без дела и путают.
    clear_row = []
    if has_about:
        clear_row.append(InlineKeyboardButton(
            text=texts.get_text("kb_clear_about", lang), callback_data="scard_about_clear"
        ))
    if has_photo:
        clear_row.append(InlineKeyboardButton(
            text=texts.get_text("kb_clear_photo", lang), callback_data="scard_photo_clear"
        ))
    if clear_row:
        rows.append(clear_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_card_text(stylist: db.Stylist, lang: str) -> str:
    from html import escape

    about_line = (
        texts.get_text("profile_card_about", lang).format(about=escape(stylist.about))
        if stylist.about
        else texts.get_text("profile_card_no_about", lang)
    )
    photo_line = texts.get_text(
        "profile_card_has_photo" if stylist.photo_file_id else "profile_card_no_photo", lang
    )
    return (
        f"{texts.get_text('profile_card_title', lang)}\n\n{about_line}\n{photo_line}"
    )


async def _show_card(target, stylist_id: int, lang: str, edit: bool = False) -> None:
    async with db.async_session() as session:
        stylist = await session.get(db.Stylist, stylist_id)
        text = build_card_text(stylist, lang)
        keyboard = _card_keyboard(lang, bool(stylist.about), bool(stylist.photo_file_id))

    send = target.edit_text if edit else target.answer
    await send(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(F.text.in_(texts.all_variants("my_profile_card")))
async def open_profile_card(message: Message, state: FSMContext):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    await state.clear()
    await _show_card(message, stylist.id, user.language_code or "ru")


@router.callback_query(F.data == "scard_back")
async def back_to_card(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    await state.clear()
    await _show_card(cb.message, stylist.id, await get_user_lang(cb.from_user.id), edit=True)
    await cb.answer()


@router.callback_query(F.data == "scard_about")
async def ask_about(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    await state.set_state(StylistProfileForm.about)
    await cb.message.edit_text(
        texts.get_text("profile_ask_about", lang).format(limit=ABOUT_MAX_LEN),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=texts.get_text("kb_back", lang), callback_data="scard_back"
            )
        ]]),
    )
    await cb.answer()


@router.callback_query(F.data == "scard_about_clear")
async def clear_about(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    async with db.async_session() as session:
        target = await session.get(db.Stylist, stylist.id)
        target.about = None
        await session.commit()

    await state.clear()
    await _show_card(cb.message, stylist.id, lang, edit=True)
    await cb.answer(texts.get_text("profile_about_cleared", lang))


@router.message(StylistProfileForm.about)
async def save_about(message: Message, state: FSMContext):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        await state.clear()
        return

    lang = user.language_code or "ru"
    about = normalize_about(message.text)
    if not about:
        # Состояние не сбрасываем: мастер мог прислать стикер или пустую
        # строку, и выгонять его из формы за это незачем.
        await message.answer(texts.get_text("profile_about_empty", lang))
        return

    async with db.async_session() as session:
        target = await session.get(db.Stylist, stylist.id)
        target.about = about
        await session.commit()

    await state.clear()
    logging.info("stylist.about_updated stylist_id=%s length=%s", stylist.id, len(about))
    await message.answer(texts.get_text("profile_about_saved", lang))
    await _show_card(message, stylist.id, lang)


@router.callback_query(F.data == "scard_photo")
async def ask_photo(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    await state.set_state(StylistProfileForm.photo)
    await cb.message.edit_text(
        texts.get_text("profile_ask_photo", lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=texts.get_text("kb_back", lang), callback_data="scard_back"
            )
        ]]),
    )
    await cb.answer()


@router.callback_query(F.data == "scard_photo_clear")
async def clear_photo(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    async with db.async_session() as session:
        target = await session.get(db.Stylist, stylist.id)
        target.photo_file_id = None
        await session.commit()

    await state.clear()
    await _show_card(cb.message, stylist.id, lang, edit=True)
    await cb.answer(texts.get_text("profile_photo_cleared", lang))


@router.message(StylistProfileForm.photo, F.photo)
async def save_photo(message: Message, state: FSMContext):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        await state.clear()
        return

    lang = user.language_code or "ru"
    # Последний размер — самый качественный из предложенных Telegram.
    file_id = message.photo[-1].file_id

    async with db.async_session() as session:
        target = await session.get(db.Stylist, stylist.id)
        target.photo_file_id = file_id
        await session.commit()

    await state.clear()
    logging.info("stylist.photo_updated stylist_id=%s", stylist.id)
    await message.answer(texts.get_text("profile_photo_saved", lang))
    await _show_card(message, stylist.id, lang)


@router.message(StylistProfileForm.photo)
async def photo_expected(message: Message):
    """Всё, что не фото, в этом состоянии объясняется, а не игнорируется."""
    lang = await get_user_lang(message.from_user.id)
    await message.answer(texts.get_text("profile_photo_expected", lang))
