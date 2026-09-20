"""
Проверки доступа на уровне хендлеров.

От services.access отличаются тем, что не просто отвечают «да/нет», а ещё
и объясняют пользователю, почему отказ. Именно поэтому они здесь, а не в services:
сервис не должен знать про Telegram.

Идентификатор из callback_data — недоверенный ввод. Владельца сверяет
services.access прямо в SQL-запросе, здесь только реакция на отказ.
"""
import logging
from contextvars import ContextVar, Token

from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy import select

import database as db
from keyboards import get_main_keyboard
from logutil import mask_user
from presenters import get_registration_text, get_subscription_menu_text
from services.access import (
    get_stylist_profile_by_telegram,
    is_registration_complete,
    is_stylist_subscription_active,
)

ACCESS_DENIED_TEXT = {
    "ru": "Это действие доступно только участнику записи.",
    "uz": "Bu amal faqat yozuv ishtirokchisiga ochiq.",
}

#: Пользователи, уже прочитанные в рамках текущего апдейта.
#:
#: Один callback тянул одну и ту же строку из users по три-четыре раза:
#: ensure_registered_callback, затем get_user_lang, затем ещё раз внутри
#: deny_access. Запросы одинаковые, а соединений к базе четыре.
#:
#: ContextVar, а не глобальный словарь: апдейты обрабатываются конкурентно,
#: и общий кеш выдавал бы одному пользователю данные другого.
_user_cache: ContextVar[dict[int, db.User | None] | None] = ContextVar(
    "maestro_user_cache", default=None
)


def open_user_cache() -> Token:
    """Начало апдейта. Токен нужен, чтобы закрыть кеш ровно на своём уровне."""
    return _user_cache.set({})


def close_user_cache(token: Token) -> None:
    _user_cache.reset(token)


def forget_user(telegram_id: int) -> None:
    """
    Убрать пользователя из кеша апдейта.

    Обязательно после любой правки его строки: смена языка, завершение
    регистрации. Иначе остаток апдейта работает с данными «до изменения» —
    например, подтверждение о смене языка приходит на старом языке.
    """
    cache = _user_cache.get()
    if cache is not None:
        cache.pop(telegram_id, None)


async def _load_user_from_db(telegram_id: int) -> db.User | None:
    """Собственно запрос. Вынесен отдельно, чтобы кеш проверялся тестами."""
    async with db.async_session() as session:
        return await session.scalar(
            select(db.User).where(db.User.telegram_id == telegram_id)
        )


async def get_user_by_telegram_id(telegram_id: int) -> db.User | None:
    cache = _user_cache.get()
    if cache is not None and telegram_id in cache:
        return cache[telegram_id]

    user = await _load_user_from_db(telegram_id)

    if cache is not None:
        # Отсутствие пользователя кешируем тоже: незарегистрированный
        # человек не должен обходиться дороже зарегистрированного.
        cache[telegram_id] = user
    return user

async def get_user_lang(telegram_id: int, default: str = "ru") -> str:
    user = await get_user_by_telegram_id(telegram_id)
    return user.language_code if user and user.language_code else default

async def deny_access(cb: CallbackQuery) -> None:
    lang = await get_user_lang(cb.from_user.id)
    logging.warning(
        "access.denied user=%s callback=%s", mask_user(cb.from_user.id), cb.data
    )
    await cb.answer(ACCESS_DENIED_TEXT[lang], show_alert=True)

async def ensure_registered_message(message: Message) -> db.User | None:
    user = await get_user_by_telegram_id(message.from_user.id)
    if user and (user.role == "stylist" or is_registration_complete(user)):
        return user

    lang = user.language_code if user and user.language_code else "ru"
    await message.answer(
        get_registration_text("registration_required", lang),
        reply_markup=ReplyKeyboardRemove(),
    )
    return None

async def ensure_registered_callback(cb: CallbackQuery) -> db.User | None:
    user = await get_user_by_telegram_id(cb.from_user.id)
    if user and (user.role == "stylist" or is_registration_complete(user)):
        return user

    lang = user.language_code if user and user.language_code else "ru"
    await cb.answer(get_registration_text("registration_required", lang), show_alert=True)
    return None

async def ensure_active_stylist_message(message: Message):
    async with db.async_session() as session:
        user, stylist = await get_stylist_profile_by_telegram(session, message.from_user.id)
    if not (user and stylist):
        await message.answer("\u041f\u0440\u043e\u0444\u0438\u043b\u044c \u043c\u0430\u0441\u0442\u0435\u0440\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.")
        return None, None
    if not is_stylist_subscription_active(user):
        await message.answer(get_subscription_menu_text(user), parse_mode="HTML", reply_markup=await get_main_keyboard(message.from_user.id))
        return None, None
    return user, stylist

async def ensure_active_stylist_callback(cb: CallbackQuery):
    async with db.async_session() as session:
        user, stylist = await get_stylist_profile_by_telegram(session, cb.from_user.id)
    if not (user and stylist):
        await cb.answer("\u041f\u0440\u043e\u0444\u0438\u043b\u044c \u043c\u0430\u0441\u0442\u0435\u0440\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.", show_alert=True)
        return None, None
    if not is_stylist_subscription_active(user):
        await cb.answer("\u0421\u0440\u043e\u043a \u0442\u0430\u0440\u0438\u0444\u0430 \u0438\u0441\u0442\u0451\u043a. \u041f\u0440\u043e\u0434\u043b\u0438\u0442\u0435 \u0442\u0430\u0440\u0438\u0444 \u0443 \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u043e\u0432 \u0441\u0435\u0440\u0432\u0438\u0441\u0430.", show_alert=True)
        return None, None
    return user, stylist
