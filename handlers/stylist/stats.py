"""
Статистика мастера за период.

Хендлер только показывает: считает services.stats, текст собирает
presenters.build_stats_report. Под отчётом — переключатель периодов
и возврат в меню статистики: раньше экран отчёта был тупиком.
"""
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, select

import database as db
import texts
from guards import (
    ensure_active_stylist_callback,
    ensure_active_stylist_message,
)
from presenters import build_stats_report
from services import stats as stats_service

router = Router(name="stylist_stats")

#: Период → (подпись кнопки, подпись в заголовке отчёта).
PERIOD_LABELS = {
    "today": ("stats_period_today", "stats_label_today"),
    "yesterday": ("stats_period_yesterday", "stats_label_yesterday"),
    "7": ("stats_period_week", "stats_label_week"),
    "30": ("stats_period_month", "stats_label_month"),
}


def _periods_keyboard(lang: str, current: str | None = None, with_back: bool = False):
    rows = []
    for period, (button_key, _) in PERIOD_LABELS.items():
        label = texts.get_text(button_key, lang)
        if period == current:
            label = f"✅ {label}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"stats_{period}")])
    if with_back:
        rows.append([InlineKeyboardButton(
            text=texts.get_text("kb_back", lang), callback_data="stats_menu"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _menu_text(stylist_id: int, lang: str) -> str:
    async with db.async_session() as session:
        fav_count = await session.scalar(
            select(func.count(db.Favorite.id)).where(db.Favorite.stylist_id == stylist_id)
        )
    return (
        f"<b>{texts.get_text('stats_favorites_count', lang).format(count=fav_count)}</b>\n\n"
        f"{texts.get_text('stats_choose_period', lang)}"
    )


@router.message(F.text.in_(texts.all_variants("my_stats")))
async def show_stats_menu(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

    lang = user.language_code or "ru"
    await message.answer(
        await _menu_text(stylist.id, lang),
        reply_markup=_periods_keyboard(lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("stats_"))
async def get_statistics(cb: CallbackQuery):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        return

    lang = user.language_code or "ru"
    # split("_")[1]: старые сообщения с кнопкой «stats_7_days» продолжают работать.
    period = cb.data.split("_")[1]

    if period == "menu":
        await cb.message.edit_text(
            await _menu_text(stylist.id, lang),
            reply_markup=_periods_keyboard(lang),
            parse_mode="HTML",
        )
        await cb.answer()
        return

    if period not in PERIOD_LABELS:
        await cb.answer(texts.get_text("stats_unknown_period", lang))
        return

    async with db.async_session() as session:
        report = await stats_service.collect(session, stylist.id, period)

    period_label = texts.get_text(PERIOD_LABELS[period][1], lang)
    try:
        await cb.message.edit_text(
            build_stats_report(report, period_label, lang),
            reply_markup=_periods_keyboard(lang, current=period, with_back=True),
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        # Повторное нажатие на уже выбранный период: Telegram отвечает
        # «message is not modified». Это не ошибка, и пугать человека
        # общим «что-то пошло не так» незачем.
        if "not modified" not in str(e):
            raise
    await cb.answer()
