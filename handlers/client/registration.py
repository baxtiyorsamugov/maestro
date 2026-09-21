"""
Первый вход, выбор языка и регистрация.
"""
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
    ReplyKeyboardRemove,
)
from sqlalchemy import select

import database as db
import texts
from guards import (
    ensure_registered_callback,
    ensure_registered_message,
    forget_user,
)
from handlers.client.stylist_card import send_stylist_card
from keyboards import (
    get_contact_request_keyboard,
    get_language_keyboard,
    get_language_switch_kb,
    get_main_keyboard,
)
from logutil import mask_user
from presenters import get_registration_text
from services.access import (
    is_registration_complete,
)
from states import RegistrationForm

router = Router(name="client_registration")


def normalize_phone_number(raw_phone: str | None) -> str | None:
    if not raw_phone:
        return None
    cleaned = re.sub(r"[^\d+]", "", raw_phone.strip())
    if cleaned.startswith("+"):
        digits = "+" + re.sub(r"\D", "", cleaned)
    else:
        digits = re.sub(r"\D", "", cleaned)
        if digits.startswith("998"):
            digits = "+" + digits
        elif len(digits) == 9:
            digits = "+998" + digits
        elif len(digits) == 12:
            digits = "+" + digits
        else:
            return None
    if re.fullmatch(r"\+\d{9,15}", digits):
        return digits
    return None

async def finish_registration(
    message: Message, user: db.User, pending_stylist_id: int | None = None
):
    """
    Завершение регистрации. Если пользователь пришёл по ссылке на мастера,
    сразу показываем его карточку — иначе переход из рассылки теряется
    и человек оказывается в общем меню, не понимая, зачем нажимал.
    """
    keyboard = await get_main_keyboard(message.from_user.id)
    lang = user.language_code or "ru"
    await message.answer(
        get_registration_text("registration_done", lang),
        reply_markup=keyboard,
    )

    if pending_stylist_id:
        logging.info(
            "deeplink.resumed user=%s stylist_id=%s",
            mask_user(message.from_user.id), pending_stylist_id,
        )
        await send_stylist_card(message, pending_stylist_id, lang)

async def prompt_registration_step(message: Message, user: db.User | None, state: FSMContext):
    lang = (user.language_code if user and user.language_code else "ru")

    if user and (user.role == "stylist" or is_registration_complete(user)):
        keyboard = await get_main_keyboard(message.from_user.id)
        welcome_name = (
            user.first_name or message.from_user.first_name
            or texts.get_text("welcome_fallback_name", lang)
        )
        welcome_text = texts.get_text('welcome_back', lang).format(welcome_name)
        await state.clear()
        await message.answer(welcome_text, reply_markup=keyboard)
        return

    if not user or not user.language_code:
        await state.clear()
        await message.answer(
            get_registration_text("choose_language", "ru"),
            reply_markup=get_language_keyboard(),
        )
        return

    if not user.first_name:
        await state.set_state(RegistrationForm.full_name)
        await message.answer(
            get_registration_text("ask_name", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await state.set_state(RegistrationForm.phone_number)
    await message.answer(
        get_registration_text("ask_contact", lang),
        reply_markup=get_contact_request_keyboard(lang),
    )

# --- Start / Registration ---
def parse_start_payload(raw: str | None) -> int | None:
    """
    Параметр диплинка https://t.me/<bot>?start=<payload>.

    Поддерживаются "12" и "stylist_12": второй вид оставляет место
    для других типов ссылок в будущем. Мусор игнорируется молча —
    пользователь просто попадёт в обычное меню.
    """
    if not raw:
        return None
    value = raw.strip()
    if value.startswith("stylist_"):
        value = value[len("stylist_"):]
    if not value.isdigit():
        return None
    stylist_id = int(value)
    return stylist_id if stylist_id > 0 else None

@router.message(Command("start"))
async def start(message: Message, state: FSMContext, command: CommandObject | None = None):
    await state.clear()
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))

    stylist_id = parse_start_payload(command.args if command else None)

    # Незарегистрированного сначала проводим через регистрацию, но мастера
    # запоминаем: иначе переход по ссылке из рассылки теряется.
    if stylist_id and not (user and (user.role == "stylist" or is_registration_complete(user))):
        await state.update_data(pending_stylist_id=stylist_id)
        await prompt_registration_step(message, user, state)
        return

    if stylist_id:
        lang = user.language_code if user and user.language_code else "ru"
        logging.info("deeplink.stylist user=%s stylist_id=%s", mask_user(message.from_user.id), stylist_id)
        await message.answer(
            texts.get_text("deeplink_opening_card", lang),
            reply_markup=await get_main_keyboard(message.from_user.id),
        )
        if await send_stylist_card(message, stylist_id, lang):
            return

    await prompt_registration_step(message, user, state)

@router.callback_query(F.data.startswith("lang_"))
async def lang_choice(cb: CallbackQuery, state: FSMContext):
    lang = cb.data.split("_")[1]

    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == cb.from_user.id))
        if not user:
            user = db.User(telegram_id=cb.from_user.id, language_code=lang)
            session.add(user)
        else:
            user.language_code = lang
        await session.commit()
    # Строка users изменилась — кеш апдейта обязан о ней забыть, иначе
    # остаток обработки пойдёт на старом языке (guards.forget_user).
    forget_user(cb.from_user.id)

    if user and (user.role == 'stylist' or is_registration_complete(user)):
        await state.clear()
        keyboard = await get_main_keyboard(cb.from_user.id)
        welcome_name = user.first_name or cb.from_user.first_name or ""
        await cb.message.edit_text(texts.get_text('welcome_back', lang).format(welcome_name))
        await cb.message.answer(texts.get_text('language_changed', lang), reply_markup=keyboard)
        await cb.answer()
        return

    await state.set_state(RegistrationForm.full_name)
    await cb.message.edit_text(get_registration_text("ask_name", lang))
    await cb.answer()

@router.message(F.text.in_([texts.get_buttons('ru')['change_language'], texts.get_buttons('uz')['change_language']]))
async def open_language_menu(message: Message, state: FSMContext):
    # ПЕРВЫМ ДЕЛОМ ЧИСТИМ ВСЁ
    await state.clear()
    
    user = await ensure_registered_message(message)
    if not user:
        return

    lang = user.language_code or 'ru'
    await message.answer(
        texts.get_text('language_menu_title', lang),
        reply_markup=get_language_switch_kb(lang),
    )

@router.callback_query(F.data.startswith("change_lang_"))
async def change_language(cb: CallbackQuery):
    user = await ensure_registered_callback(cb)
    if not user:
        return

    lang = cb.data.split("_")[-1]
    async with db.async_session() as session:
        db_user = await session.scalar(select(db.User).where(db.User.telegram_id == cb.from_user.id))
        if db_user:
            db_user.language_code = lang
            await session.commit()
    forget_user(cb.from_user.id)

    keyboard = await get_main_keyboard(cb.from_user.id)
    await cb.message.edit_text(texts.get_text('language_changed', lang), reply_markup=None)
    await cb.message.answer(texts.get_text('welcome_back', lang).format(user.first_name or cb.from_user.first_name or ""), reply_markup=keyboard)
    await cb.answer()

@router.message(RegistrationForm.full_name)
async def process_registration_name(message: Message, state: FSMContext):
    full_name = (message.text or "").strip()

    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))
        lang = user.language_code if user and user.language_code else "ru"

        if len(full_name) < 2:
            await message.answer(get_registration_text("invalid_name", lang))
            return

        if not user:
            user = db.User(telegram_id=message.from_user.id, language_code=lang)
            session.add(user)

        user.first_name = full_name
        await session.commit()
    forget_user(message.from_user.id)

    await state.set_state(RegistrationForm.phone_number)
    await message.answer(
        get_registration_text("ask_contact", lang),
        reply_markup=get_contact_request_keyboard(lang),
    )

@router.message(RegistrationForm.phone_number, F.contact)
async def process_registration_contact(message: Message, state: FSMContext):
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))
        lang = user.language_code if user and user.language_code else "ru"

        if not message.contact or message.contact.user_id != message.from_user.id:
            await message.answer(get_registration_text("contact_self_only", lang))
            return

        if not user:
            user = db.User(telegram_id=message.from_user.id, language_code=lang)
            session.add(user)

        user.phone_number = normalize_phone_number(message.contact.phone_number) or message.contact.phone_number
        await session.commit()
    forget_user(message.from_user.id)

    pending_stylist_id = (await state.get_data()).get("pending_stylist_id")
    await state.clear()
    await finish_registration(message, user, pending_stylist_id)

@router.message(RegistrationForm.phone_number, F.text)
async def process_registration_phone_text(message: Message, state: FSMContext):
    async with db.async_session() as session:
        user = await session.scalar(select(db.User).where(db.User.telegram_id == message.from_user.id))
        lang = user.language_code if user and user.language_code else "ru"

        # Те же ключи, что у клавиатуры (keyboards.get_contact_request_keyboard):
        # два отдельных словаря однажды разошлись бы, и кнопка перестала бы
        # узнаваться как кнопка.
        manual_button = texts.get_text("kb_enter_phone_manually", lang)
        share_button = texts.get_text("kb_share_contact", lang)

        if message.text == share_button:
            await message.answer(
                get_registration_text("ask_contact", lang),
                reply_markup=get_contact_request_keyboard(lang),
            )
            return

        if message.text == manual_button:
            await message.answer(
                get_registration_text("ask_phone_manual", lang),
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        normalized_phone = normalize_phone_number(message.text)
        if not normalized_phone:
            await message.answer(get_registration_text("invalid_phone", lang))
            return

        if not user:
            user = db.User(telegram_id=message.from_user.id, language_code=lang)
            session.add(user)

        user.phone_number = normalized_phone
        await session.commit()
    forget_user(message.from_user.id)

    pending_stylist_id = (await state.get_data()).get("pending_stylist_id")
    await state.clear()
    await finish_registration(message, user, pending_stylist_id)
