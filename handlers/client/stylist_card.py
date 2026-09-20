"""
Карточка мастера: профиль, портфолио, карта.
"""
from html import escape

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from sqlalchemy import select
from sqlalchemy.orm import joinedload

import database as db
import texts
from guards import (
    get_user_lang,
)
from presenters import build_reviews_text
from services.access import (
    is_stylist_subscription_active,
)
from services.reviews import count_reviews_for_stylist, load_reviews_for_stylist

router = Router(name="client_stylist_card")


async def load_stylist_card(stylist_id: int, lang: str):
    """
    Данные карточки мастера: сама карточка, клавиатура и фото портфолио.
    Возвращает (None, причина) если мастера нет или он закрыт для записи.
    """
    async with db.async_session() as session:
        stylist = await session.scalar(
            select(db.Stylist)
            .where(db.Stylist.id == stylist_id)
            .options(joinedload(db.Stylist.barbershop), joinedload(db.Stylist.user_account))
        )
        if not stylist:
            return None, {'ru': 'Мастер не найден.', 'uz': 'Maestro topilmadi.'}[lang]
        if not is_stylist_subscription_active(stylist.user_account):
            return None, {
                'ru': 'Этот мастер временно недоступен для записи.',
                'uz': 'Bu maestro hozircha yozuv uchun yopiq.',
            }[lang]

        photos = (await session.execute(
            select(db.Portfolio)
            .where(db.Portfolio.stylist_id == stylist.id)
            .order_by(db.Portfolio.id.desc())
            .limit(3)
        )).scalars().all()

        rating_text = (
            ("★ " * int(round(stylist.avg_rating)))
            if stylist.avg_rating > 0
            else {'ru': 'Нет оценок', 'uz': "Baholar yo'q"}[lang]
        )
        if stylist.reviews_count:
            rating_text += f" ({stylist.reviews_count})"

        caption = (
            f"<b>{({'ru': 'Мастер', 'uz': 'Maestro'})[lang]}: {escape(stylist.name)}</b>\n"
            f"{({'ru': 'Рейтинг', 'uz': 'Reyting'})[lang]}: {rating_text}\n\n"
            f"<b>{({'ru': 'Салон', 'uz': 'Salon'})[lang]}:</b> {escape(stylist.barbershop.name)}\n"
            f"<b>{({'ru': 'Район', 'uz': 'Tuman'})[lang]}:</b> {escape(stylist.barbershop.district)}\n"
            f"<b>{({'ru': 'Адрес', 'uz': 'Manzil'})[lang]}:</b> {escape(stylist.barbershop.address)}"
        )
        reviews_total = await count_reviews_for_stylist(session, stylist.id)

        rows = [
            [InlineKeyboardButton(text={'ru': 'Записаться к мастеру', 'uz': 'Maestroga yozilish'}[lang], callback_data=f"book_{stylist.id}")],
        ]
        # Кнопку показываем только когда есть что читать: пустой экран
        # «отзывов пока нет» — тупик, за который человек зря нажал.
        if reviews_total:
            rows.append([InlineKeyboardButton(
                text=texts.get_text("kb_stylist_reviews", lang).format(count=reviews_total),
                callback_data=f"reviews_{stylist.id}",
            )])
        rows.append([InlineKeyboardButton(text={'ru': 'Показать на карте', 'uz': "Xaritada ko'rsatish"}[lang], callback_data=f"map_{stylist.barbershop.id}")])
        rows.append([InlineKeyboardButton(text={'ru': 'Назад к списку мастеров', 'uz': "Maestrolar ro'yxatiga qaytish"}[lang], callback_data=f"shop_{stylist.barbershop.id}")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)

    return {"caption": caption, "keyboard": kb, "photos": photos}, None

async def send_stylist_card(message: Message, stylist_id: int, lang: str) -> bool:
    """Отправляет карточку мастера новым сообщением. False — если показать нечего."""
    card, error = await load_stylist_card(stylist_id, lang)
    if not card:
        await message.answer(error)
        return False

    if card["photos"]:
        await message.answer_media_group(
            media=[InputMediaPhoto(media=p.telegram_photo_file_id) for p in card["photos"]]
        )
    await message.answer(card["caption"], reply_markup=card["keyboard"], parse_mode="HTML")
    return True

@router.callback_query(F.data.startswith("stylist_"))
async def show_maestro_card(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    stylist_id = int(cb.data.split("_")[1])

    card, error = await load_stylist_card(stylist_id, lang)
    if not card:
        await cb.answer(error, show_alert=True)
        return

    if card["photos"]:
        await cb.message.answer_media_group(
            media=[InputMediaPhoto(media=p.telegram_photo_file_id) for p in card["photos"]]
        )
    await cb.message.answer(card["caption"], reply_markup=card["keyboard"], parse_mode="HTML")

    await cb.message.delete()
    await cb.answer()

@router.callback_query(F.data.startswith("back_to_stylist_"))
async def back_to_stylist_card(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    stylist_id = int(cb.data.split("_")[-1])
    await cb.message.edit_text({'ru': '\u041f\u0440\u043e\u0444\u0438\u043b\u044c \u043c\u0430\u0441\u0442\u0435\u0440\u0430 \u0437\u0430\u0433\u0440\u0443\u0436\u0430\u0435\u0442\u0441\u044f...', 'uz': 'Maestro profili yuklanmoqda...'}[lang])

    async with db.async_session() as session:
        query = select(db.Stylist).where(db.Stylist.id == stylist_id).options(joinedload(db.Stylist.barbershop), joinedload(db.Stylist.user_account))
        stylist = await session.scalar(query)
        if not stylist:
            await cb.answer({'ru': '\u041c\u0430\u0441\u0442\u0435\u0440 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.', 'uz': 'Maestro topilmadi.'}[lang], show_alert=True)
            return
        if not is_stylist_subscription_active(stylist.user_account):
            await cb.answer({'ru': '\u042d\u0442\u043e\u0442 \u043c\u0430\u0441\u0442\u0435\u0440 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d \u0434\u043b\u044f \u0437\u0430\u043f\u0438\u0441\u0438.', 'uz': 'Bu maestro hozircha yozuv uchun yopiq.'}[lang], show_alert=True)
            return
        photos = (await session.execute(
            select(db.Portfolio).where(db.Portfolio.stylist_id == stylist.id).order_by(db.Portfolio.id.desc()).limit(3)
        )).scalars().all()

    rating_text = ("★ " * int(round(stylist.avg_rating))) if stylist.avg_rating > 0 else ({'ru': 'Нет оценок', 'uz': "Baholar yo'q"}[lang])
    labels = {
        "master": {"ru": "Мастер", "uz": "Maestro"}[lang],
        "rating": {"ru": "Рейтинг", "uz": "Reyting"}[lang],
        "salon": {"ru": "Салон", "uz": "Salon"}[lang],
        "district": {"ru": "Район", "uz": "Tuman"}[lang],
        "address": {"ru": "Адрес", "uz": "Manzil"}[lang],
    }
    caption = (
        f"<b>{labels['master']}: {escape(stylist.name)}</b>\n"
        f"{labels['rating']}: {rating_text}\n\n"
        f"<b>{labels['salon']}:</b> {stylist.barbershop.name}\n"
        f"<b>{labels['district']}:</b> {stylist.barbershop.district}\n"
        f"<b>{labels['address']}:</b> {stylist.barbershop.address}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text={'ru': '\u0417\u0430\u043f\u0438\u0441\u0430\u0442\u044c\u0441\u044f \u043a \u043c\u0430\u0441\u0442\u0435\u0440\u0443', 'uz': 'Maestroga yozilish'}[lang], callback_data=f"book_{stylist.id}")],
        [InlineKeyboardButton(text={'ru': '\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u043d\u0430 \u043a\u0430\u0440\u0442\u0435', 'uz': "Xaritada ko'rsatish"}[lang], callback_data=f"map_{stylist.barbershop.id}")],
        [InlineKeyboardButton(text={'ru': '\u041d\u0430\u0437\u0430\u0434 \u043a \u0441\u043f\u0438\u0441\u043a\u0443 \u043c\u0430\u0441\u0442\u0435\u0440\u043e\u0432', 'uz': "Maestrolar ro'yxatiga qaytish"}[lang], callback_data=f"shop_{stylist.barbershop.id}")],
    ])

    if photos:
        media_group = [InputMediaPhoto(media=p.telegram_photo_file_id) for p in photos]
        await cb.message.answer_media_group(media=media_group)
        await cb.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    else:
        await cb.message.answer(caption, reply_markup=kb, parse_mode="HTML")

    await cb.message.delete()
    await cb.answer()

@router.callback_query(F.data.startswith("reviews_"))
async def show_reviews(cb: CallbackQuery):
    """
    Отзывы о мастере: последние REVIEWS_PREVIEW_LIMIT и счётчик остальных.

    Скрытые модератором сюда не попадают — фильтр в самом запросе,
    а не после выборки: так отзыв нельзя случайно показать, забыв проверку.
    """
    lang = await get_user_lang(cb.from_user.id)
    stylist_id = int(cb.data.split("_")[-1])

    async with db.async_session() as session:
        stylist = await session.get(db.Stylist, stylist_id)
        if not stylist:
            await cb.answer(texts.get_text("booking_stylist_closed", lang), show_alert=True)
            return
        reviews = await load_reviews_for_stylist(session, stylist_id)
        total = await count_reviews_for_stylist(session, stylist_id)
        stylist_name = stylist.name

    await cb.message.edit_text(
        build_reviews_text(stylist_name, reviews, total, lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=texts.get_text("kb_back", lang),
                callback_data=f"back_to_stylist_{stylist_id}",
            )
        ]]),
        parse_mode="HTML",
    )
    await cb.answer()

@router.callback_query(F.data.startswith("map_"))
async def show_map(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    shop_id = int(cb.data.split("_")[1])
    async with db.async_session() as session:
        shop = await session.get(db.Barbershop, shop_id)
    if shop and shop.latitude and shop.longitude:
        await cb.message.answer_location(latitude=shop.latitude, longitude=shop.longitude)
        await cb.answer({'ru': 'Карта отправлена', 'uz': 'Xarita yuborildi'}[lang])
    else:
        await cb.answer({'ru': 'Для этого салона координаты не указаны.', 'uz': 'Bu salon uchun koordinatalar kiritilmagan.'}[lang], show_alert=True)
