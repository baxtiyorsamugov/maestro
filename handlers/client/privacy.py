"""
Персональные данные: политика и удаление аккаунта.

Удалить аккаунт по просьбе человека было нельзя вовсе. Сама логика удаления —
что стирается, а что остаётся обезличенным и почему — в services/privacy.py.
Здесь только разговор с человеком: показать, что хранится, переспросить
и сделать.

Переспрашиваем обязательно. Удаление необратимо, а кнопка в Telegram
нажимается случайно легче, чем кажется, — особенно на телефоне в транспорте.
"""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import database as db
import texts
import timeutils
from guards import forget_user, get_user_by_telegram_id, get_user_lang
from loader import bot
from logutil import mask_user
from services import privacy

router = Router(name="client_privacy")


def _privacy_menu_kb(lang: str, can_delete: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=texts.get_text("kb_privacy_policy", lang), callback_data="privacy_policy"
    )]]
    if can_delete:
        rows.append([InlineKeyboardButton(
            text=texts.get_text("kb_delete_account", lang), callback_data="privacy_delete_ask"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_summary(target: Message, telegram_id: int, lang: str) -> None:
    user = await get_user_by_telegram_id(telegram_id)
    if user is None:
        # Незарегистрированному показываем только политику: хранить о нём нечего.
        await target.answer(texts.get_text("privacy_policy", lang), parse_mode="HTML")
        return

    async with db.async_session() as session:
        summary = await privacy.summarize(session, user)

    text = texts.get_text("privacy_summary", lang).format(
        phone=texts.get_text(
            "privacy_phone_yes" if summary.has_phone else "privacy_phone_no", lang
        ),
        bookings=summary.bookings,
        upcoming=summary.upcoming,
        reviews=summary.reviews,
        favorites=summary.favorites,
    )
    # Мастеру кнопку удаления не показываем вовсе: кнопка, отвечающая отказом,
    # хуже отсутствующей. Объяснение он получит, если попросит через /privacy.
    await target.answer(
        text,
        reply_markup=_privacy_menu_kb(lang, can_delete=user.role != "stylist"),
        parse_mode="HTML",
    )


@router.message(Command("privacy"))
async def privacy_command(message: Message, state: FSMContext):
    """
    /privacy доступна любому, в том числе незарегистрированному: узнать,
    что с тобой будут делать, нужно до того, как отдашь телефон, а не после.
    """
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    await _send_summary(message, message.from_user.id, lang)


@router.message(F.text.in_(texts.all_variants("my_data")))
async def privacy_button(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    await _send_summary(message, message.from_user.id, lang)


@router.callback_query(F.data == "privacy_policy")
async def show_policy(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    await cb.message.answer(texts.get_text("privacy_policy", lang), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "privacy_delete_ask")
async def ask_deletion(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    user = await get_user_by_telegram_id(cb.from_user.id)
    if user is None:
        await cb.answer(texts.get_text("privacy_deleted", lang), show_alert=True)
        return
    if user.role == "stylist":
        await cb.answer(texts.get_text("privacy_stylist_refused", lang), show_alert=True)
        return

    async with db.async_session() as session:
        summary = await privacy.summarize(session, user)

    # Предупреждаем о будущих визитах отдельно: это единственное последствие,
    # которое касается не только самого человека, но и мастера.
    upcoming_line = (
        texts.get_text("privacy_upcoming_warning", lang).format(count=summary.upcoming)
        if summary.upcoming
        else ""
    )
    await cb.message.edit_text(
        texts.get_text("privacy_delete_confirm", lang).format(upcoming_line=upcoming_line),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=texts.get_text("kb_delete_confirm", lang),
                callback_data="privacy_delete_confirm",
            )],
            [InlineKeyboardButton(
                text=texts.get_text("kb_delete_cancel", lang),
                callback_data="privacy_delete_cancel",
            )],
        ]),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "privacy_delete_cancel")
async def cancel_deletion(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    await cb.message.edit_text(texts.get_text("privacy_delete_cancelled", lang))
    await cb.answer()


@router.callback_query(F.data == "privacy_delete_confirm")
async def confirm_deletion(cb: CallbackQuery, state: FSMContext):
    # Язык запоминаем ДО удаления: после него строки users уже нет,
    # и финальное сообщение ушло бы на языке по умолчанию.
    lang = await get_user_lang(cb.from_user.id)
    user = await get_user_by_telegram_id(cb.from_user.id)
    if user is None:
        # Повторное нажатие на уже устаревшей кнопке: удалять нечего.
        await cb.answer(texts.get_text("privacy_deleted", lang), show_alert=True)
        return

    try:
        async with db.async_session() as session:
            report = await privacy.delete_client_account(session, user.id)
    except privacy.DeletionRefused as refused:
        await cb.answer(texts.get_text(refused.reason_key, lang), show_alert=True)
        return

    # Кеш апдейта ещё держит удалённую строку — забываем её сразу.
    forget_user(cb.from_user.id)
    await state.clear()

    logging.info(
        "privacy.account_deleted user=%s unlinked=%s cancelled=%s",
        mask_user(cb.from_user.id), report.bookings_unlinked, len(report.cancelled),
    )

    await cb.message.edit_text(texts.get_text("privacy_deleted", lang))
    await cb.answer()

    # Мастеров предупреждаем после commit и вне сессии (CLAUDE.md, 4.3):
    # сетевой вызов внутри транзакции держал бы соединение с базой.
    for visit in report.cancelled:
        if not visit.stylist_telegram_id:
            continue
        try:
            await bot.send_message(
                visit.stylist_telegram_id,
                texts.get_text("privacy_stylist_notice", visit.stylist_lang).format(
                    slot=timeutils.format_human(visit.starts_at, visit.stylist_lang)
                ),
            )
        except Exception as exc:
            logging.warning(
                "privacy.stylist_notice_failed booking_id=%s error=%s",
                visit.booking_id, exc,
            )
