"""
Поиск мастера: по району, по имени, по ID, карточка мастера.
"""
from html import escape

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
import texts
from guards import (
    ensure_registered_callback,
    ensure_registered_message,
    get_user_lang,
)
from presenters import build_stylist_button_label
from services.access import (
    is_stylist_subscription_active,
)
from services.booking import get_last_booking_for_repeat
from services.search import (
    DEFAULT_SORT,
    SORT_MODES,
    load_stylist_cards,
    sort_cards,
)
from states import SearchForm

router = Router(name="client_search")


def is_client_main_menu_button(text_value: str | None) -> bool:
    """
    Нажата ли кнопка главного меню, а не введён текст запроса.

    Список берётся из texts.BUTTONS целиком, а не перечисляется здесь руками.
    Раньше перечислялся — и новая кнопка «Мои данные», нажатая посреди
    поиска, ушла бы поисковым запросом по имени мастера. Ручной список
    устаревает ровно в тот момент, когда меню пополняется.
    """
    if not text_value:
        return False
    return text_value in {
        variant for key in texts.BUTTONS for variant in texts.all_variants(key)
    }

async def clear_search_context(state: FSMContext, user_id: int):
    current_state = await state.get_state()
    if current_state == SearchForm.waiting_for_name.state:
        await state.clear()
    await state.update_data(search_type=None)

async def show_stylist_buttons(
    message: Message,
    stylists: list,
    title: str,
    lang: str,
    shop_id_for_back_button: int | None = None,
):
    """
    Результаты поиска по имени или ID.

    Подписи те же, что в списке салона: рейтинг, цена «от» и ближайшее
    свободное время. Два разных вида одного и того же списка заставляли бы
    человека заново разбираться, что перед ним, — и один из них неизбежно
    отстал бы от другого.
    """
    if not stylists:
        await message.answer(texts.get_text("search_nobody_found", lang))
        return

    async with db.async_session() as session:
        cards = sort_cards(await load_stylist_cards(session, stylists), DEFAULT_SORT)

    btns = [
        [InlineKeyboardButton(
            text=build_stylist_button_label(card, lang), callback_data=f"maestro_{card.id}"
        )]
        for card in cards
    ]

    if shop_id_for_back_button:
        btns.append([InlineKeyboardButton(
            text=texts.get_text("kb_back", lang),
            callback_data=f"shop_{shop_id_for_back_button}",
        )])

    await message.answer(title, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

async def run_search_input_flow(message: Message, search_type: str) -> bool:
    lang = await get_user_lang(message.from_user.id)

    async with db.async_session() as session:
        if search_type == "name":
            stylists = (await session.execute(
                select(db.Stylist)
                .where(db.Stylist.name.ilike(f"%{message.text}%"))
                .options(joinedload(db.Stylist.user_account))
            )).scalars().all()
            title = {"ru": "Результаты поиска по имени:", "uz": "Ism bo'yicha qidiruv natijalari:"}[lang]
        elif search_type == "id":
            if not (message.text or "").isdigit():
                await message.answer({
                    "ru": "ID должен состоять только из цифр. Попробуйте ещё раз.",
                    "uz": "ID faqat raqamlardan iborat bo'lishi kerak. Qayta urinib ko'ring.",
                }[lang])
                return False

            requested_id = int(message.text)

            # ИСПРАВЛЕНИЕ: Ищем ТОЛЬКО по основному ID стилиста (тот, что в твоей таблице)
            stylist = await session.scalar(
                select(db.Stylist)
                .where(db.Stylist.id == requested_id)
                .options(joinedload(db.Stylist.user_account))
            )

            if stylist and not is_stylist_subscription_active(stylist.user_account):
                expiry_text = stylist.user_account.subscription_until.strftime("%Y-%m-%d") if stylist.user_account and stylist.user_account.subscription_until else None
                await message.answer({
                    "ru": f"Мастер найден, но сейчас недоступен для записи. Срок тарифа истёк: {expiry_text or 'не указан'}.",
                    "uz": f"Maestro topildi, lekin hozir yozilish uchun mavjud emas. Tarif muddati tugagan: {expiry_text or 'koʻrsatilmagan'}.",
                }[lang])
                return False

            stylists = [stylist] if stylist else []
            title = {"ru": "Результат поиска по ID:", "uz": "ID bo'yicha qidiruv natijasi:"}[lang]
        else:
            await message.answer({"ru": "Не удалось выполнить поиск. Попробуйте ещё раз.", "uz": "Qidiruvda xatolik yuz berdi."}[lang])
            return False

    stylists = [stylist for stylist in stylists if stylist and is_stylist_subscription_active(stylist.user_account)]

    if not stylists:
        retry_prompt = {
            "id": {
                "ru": "Мастер не найден. Отправьте другой ID или вернитесь в меню поиска.",
                "uz": "Maestro topilmadi. Boshqa ID yuboring yoki qidiruv menyusiga qayting.",
            },
            "name": {
                "ru": "По вашему запросу никого не нашли. Попробуйте другое имя.",
                "uz": "So'rovingiz bo'yicha hech kim topilmadi. Boshqa ism bilan urinib ko'ring.",
            },
        }
        await message.answer(retry_prompt.get(search_type, retry_prompt["name"])[lang])
        return False

    await show_stylist_buttons(message, stylists, title, lang)
    return True



@router.callback_query(F.data == "search_district")
async def search_by_district_menu(cb: CallbackQuery):
    if not await ensure_registered_callback(cb):
        return

    async with db.async_session() as session:
        districts = (await session.execute(
            select(db.Barbershop.district).distinct().order_by(db.Barbershop.district)
        )).scalars().all()

    if not districts:
        await cb.answer("Пока нет доступных районов для поиска.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        *[[InlineKeyboardButton(text=d, callback_data=f"dist_{d}")] for d in districts],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_home")],
    ])
    await cb.message.edit_text(
        "Выберите район. Потом можно открыть список подходящих барбершопов.",
        reply_markup=kb,
    )
    await cb.answer()

@router.callback_query(F.data.startswith("search_"))
async def search_start(cb: CallbackQuery, state: FSMContext):
    if not await ensure_registered_callback(cb):
        return

    search_type = cb.data.split("_")[1]
    await state.update_data(search_type=search_type)
    await state.set_state(SearchForm.waiting_for_name)

    lang = await get_user_lang(cb.from_user.id)
    prompt = (
        {"ru": "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0438\u043c\u044f \u0438\u043b\u0438 \u0447\u0430\u0441\u0442\u044c \u0438\u043c\u0435\u043d\u0438 \u043c\u0430\u0441\u0442\u0435\u0440\u0430:", "uz": "Maestroning ismini yoki bir qismini kiriting:"}[lang]
        if search_type == "name"
        else {"ru": "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 ID \u043c\u0430\u0441\u0442\u0435\u0440\u0430 (\u0442\u043e\u043b\u044c\u043a\u043e \u0446\u0438\u0444\u0440\u044b):", "uz": "Maestro ID sini kiriting (faqat raqam):"}[lang]
    )
    await cb.message.edit_text(prompt)
    await cb.answer()

@router.message(SearchForm.waiting_for_name)
async def process_search_input(message: Message, state: FSMContext):
    # Проверка: если нажата кнопка главного меню - просто сбрасываем состояние и выходим
    if is_client_main_menu_button(message.text):
        await state.clear()
        await state.update_data(search_type=None)
        return # Бот увидит нажатие кнопки меню следующим хендлером

    data = await state.get_data()
    search_type = data.get("search_type")

    if not search_type:
        await state.clear()
        return

    success = await run_search_input_flow(message, search_type)
    if success:
        await state.clear()
        await state.update_data(search_type=None)

async def send_booking_menu(target: Message, user: db.User, state: FSMContext) -> None:
    """
    Стартовый экран записи.

    Пользователь передаётся аргументом, а не берётся из target.from_user:
    сюда приходят и сообщения клиента, и сообщения, отправленные самим ботом
    (возврат по кнопке «Назад»), а у вторых from_user — это бот.
    """
    await state.set_state(SearchForm.waiting_for_name)
    await state.update_data(search_type="id")  # ждём именно ID мастера

    lang = user.language_code or "ru"

    text = {
        "ru": (
            "✨ <b>Добро пожаловать в мир Maestro!</b>\n\n"
            "Чтобы мгновенно найти своего мастера и забронировать время, "
            "просто <b>введите его ID номер</b> ниже:\n\n"
            "🆔 <i>Номер указан на табличке с QR-кодом или визитке мастера.</i>"
        ),
        "uz": (
            "✨ <b>Maestro olamiga xush kelibsiz!</b>\n\n"
            "O'z maestroingizni bir zumda topish va vaqtni band qilish uchun "
            "uning <b>ID raqamini</b> pastga yuboring:\n\n"
            "🆔 <i>ID raqami Maestro peshlavhasidagi QR-kod ostida yoki instagram biosida ko'rsatilgan.</i>"
        )
    }[lang]

    # Отправляем сообщение. Мы не убираем Reply-кнопки, чтобы клиент мог передумать 
    # и нажать "Мой профиль", но фокус теперь на вводе цифр.
    # Вернувшемуся клиенту предлагаем повтор: в большинстве случаев он идёт
    # к тому же мастеру на ту же услугу, и вводить ID ему незачем.
    keyboard = None
    async with db.async_session() as session:
        last = await get_last_booking_for_repeat(session, user.id)
        if last:
            service_name = (
                last.service.catalog_service.name
                if last.service.catalog_service
                else texts.get_text("booking_service", lang)
            )
            text += "\n\n" + texts.get_text("repeat_hint", lang)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=texts.get_text("repeat_button", lang).format(
                        service=service_name, stylist=last.stylist.name
                    ),
                    callback_data=f"repeat_{last.id}",
                )
            ]])

    # Reply-кнопки не убираем: клиент может передумать и нажать «Мой профиль».
    await target.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(F.text.in_(texts.all_variants("search_menu")))
async def booking_start_menu(message: Message, state: FSMContext):
    await state.clear()
    user = await ensure_registered_message(message)
    if not user:
        return
    await send_booking_menu(message, user, state)


@router.callback_query(F.data == "back_home")
async def back_home(cb: CallbackQuery, state: FSMContext):
    """
    Возврат к началу записи.

    Раньше здесь вызывался booking_start_menu(cb.message) — без обязательного
    аргумента state, то есть с TypeError. Даже с аргументом это не сработало бы:
    у сообщения, отправленного ботом, from_user — сам бот, и проверка регистрации
    отвечала бы «сначала завершите регистрацию».
    """
    user = await ensure_registered_callback(cb)
    if not user:
        return

    await state.clear()
    await cb.message.delete()
    await send_booking_menu(cb.message, user, state)
    await cb.answer()

@router.callback_query(F.data.startswith("dist_"))
async def show_shops(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    dist = cb.data.split("_", 1)[1]
    async with db.async_session() as session:
        shops = (await session.execute(
            select(db.Barbershop).where(db.Barbershop.district == dist).order_by(db.Barbershop.name)
        )).scalars().all()
        shop_ids = [shop.id for shop in shops]
        stylist_counts = {}
        if shop_ids:
            stylists = (await session.execute(
                select(db.Stylist)
                .where(db.Stylist.barbershop_id.in_(shop_ids))
                .options(joinedload(db.Stylist.user_account))
            )).scalars().all()
            for stylist in stylists:
                if is_stylist_subscription_active(stylist.user_account):
                    stylist_counts[stylist.barbershop_id] = stylist_counts.get(stylist.barbershop_id, 0) + 1

    if not shops:
        await cb.answer({"ru": "В этом районе пока нет барбершопов.", "uz": "Bu tumanda hozircha barbershoplarimiz yo'q."}[lang], show_alert=True)
        return

    visible_shops = [shop for shop in shops if stylist_counts.get(shop.id, 0) > 0]
    if not visible_shops:
        await cb.answer({"ru": "В этом районе пока нет активных мастеров.", "uz": "Bu tumanda hozircha faol maestrolar yo'q."}[lang], show_alert=True)
        return

    btns = [[InlineKeyboardButton(text=f"{shop.name} - {stylist_counts.get(shop.id, 0)}", callback_data=f"shop_{shop.id}")] for shop in visible_shops]
    btns.append([InlineKeyboardButton(text={"ru": "Назад", "uz": "Ortga"}[lang], callback_data="search_district")])

    await cb.message.edit_text(
        {
            "ru": f"Выберите барбершоп в районе <b>{dist}</b>.\nКарту можно открыть в карточке мастера.",
            "uz": f"<b>{dist}</b> tumanidagi barbershopni tanlang.\nXaritani usta kartasidan ochishingiz mumkin.",
        }[lang],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
        parse_mode="HTML",
    )
    await cb.answer()

async def render_stylist_list(cb: CallbackQuery, shop_id: int, sort_mode: str) -> None:
    """
    Список мастеров салона с фактами и сортировкой.

    Раньше здесь были одни имена: чтобы понять, кто дороже, у кого рейтинг
    выше и кто освободится раньше, приходилось открывать карточки по одной
    и возвращаться. Обычно так не делают — жмут первого или уходят.
    """
    lang = await get_user_lang(cb.from_user.id)

    async with db.async_session() as session:
        stylists = (await session.execute(
            select(db.Stylist)
            .where(db.Stylist.barbershop_id == shop_id)
            .options(joinedload(db.Stylist.user_account))
        )).scalars().all()
        stylists = [s for s in stylists if is_stylist_subscription_active(s.user_account)]
        shop = await session.get(db.Barbershop, shop_id)
        cards = await load_stylist_cards(session, stylists)

    if not cards:
        await cb.answer(
            {
                "ru": "В этом салоне пока нет активных мастеров.",
                "uz": "Bu salonda hozircha faol maestrolar yo'q.",
            }[lang],
            show_alert=True,
        )
        return

    cards = sort_cards(cards, sort_mode)

    btns = [
        [InlineKeyboardButton(
            text=build_stylist_button_label(card, lang), callback_data=f"maestro_{card.id}"
        )]
        for card in cards
    ]

    # Режимы сортировки одной строкой. Текущий помечен галочкой: иначе
    # непонятно, по чему список отсортирован сейчас.
    sort_row = []
    for mode in SORT_MODES:
        label = texts.get_text(f"sort_{mode}", lang)
        if mode == sort_mode:
            label = f"✅ {label}"
        sort_row.append(InlineKeyboardButton(
            text=label, callback_data=f"sort_{mode}_{shop_id}"
        ))
    btns.append(sort_row)
    btns.append([InlineKeyboardButton(
        text={"ru": "Назад", "uz": "Ortga"}[lang], callback_data=f"dist_{shop.district}"
    )])

    await cb.message.edit_text(
        texts.get_text("search_pick_stylist", lang).format(
            shop=escape(shop.name),
            sort=texts.get_text("search_sorted_by", lang).format(
                mode=texts.get_text(f"sort_{sort_mode}", lang)
            ),
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sort_"))
async def change_sort(cb: CallbackQuery):
    # Режим приходит из callback_data, то есть от клиента Telegram:
    # сверяем со своим списком, а не доверяем присланному.
    _, mode, shop_id = cb.data.split("_", 2)
    if mode not in SORT_MODES:
        lang = await get_user_lang(cb.from_user.id)
        await cb.answer(texts.get_text("fallback_button_outdated", lang), show_alert=True)
        return
    await render_stylist_list(cb, int(shop_id), mode)


@router.callback_query(F.data.startswith("shop_"))
async def show_stylists(cb: CallbackQuery):
    await render_stylist_list(cb, int(cb.data.split("_")[1]), DEFAULT_SORT)
