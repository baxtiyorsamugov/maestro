"""
Запись к мастеру: услуга, дата, время, подтверждение.
"""
import logging
from datetime import datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

import database as db
import texts
import timeutils
import utils
from database import (
    BOOKING_PENDING,
)
from guards import (
    deny_access,
    ensure_registered_callback,
    get_user_lang,
)
from loader import bot
from services.access import (
    is_registration_complete,
    is_stylist_subscription_active,
    load_booking_for_client,
)
from services.booking import get_available_dates_for_month, get_available_slots_for_date

router = Router(name="client_booking")


BOOKING_KEYS = ("stylist_id", "service_id", "date")

async def get_booking_draft(state: FSMContext) -> dict:
    """Черновик записи из FSM: stylist_id, service_id, date."""
    data = await state.get_data()
    return {key: data[key] for key in BOOKING_KEYS if data.get(key) is not None}

async def update_booking_draft(state: FSMContext, **values) -> dict:
    await state.update_data(**values)
    return await get_booking_draft(state)

async def clear_booking_draft(state: FSMContext) -> None:
    data = await state.get_data()
    for key in BOOKING_KEYS:
        data.pop(key, None)
    await state.set_data(data)

# Префикс stylist_ здесь был недостижим: карточка мастера подключена раньше
# и забирает эти нажатия себе. Оставлять его — значит делать вид, что хендлер
# ловит больше, чем ловит на самом деле.
@router.callback_query(F.data.startswith(("book_", "maestro_")))
async def show_services(cb: CallbackQuery, state: FSMContext):
    if not await ensure_registered_callback(cb):
        return

    lang = await get_user_lang(cb.from_user.id)
    maestro_id = int(cb.data.split("_")[-1])
    await update_booking_draft(state, stylist_id=maestro_id)

    async with db.async_session() as session:
        services_query = select(db.Service).where(db.Service.stylist_id == maestro_id).options(joinedload(db.Service.catalog_service))
        services = (await session.execute(services_query)).scalars().all()
        stylist_query = select(db.Stylist).where(db.Stylist.id == maestro_id).options(joinedload(db.Stylist.barbershop), joinedload(db.Stylist.user_account))
        stylist = await session.scalar(stylist_query)
        if not stylist:
            await cb.answer({"ru": "Мастер не найден.", "uz": "Maestro topilmadi."}[lang], show_alert=True)
            return
        if not is_stylist_subscription_active(stylist.user_account):
            await cb.answer({"ru": "У этого мастера истёк срок тарифа. Выберите другого мастера.", "uz": "Bu maestroning tarifi tugagan. Boshqa maestroni tanlang."}[lang], show_alert=True)
            return
        user = await session.scalar(select(db.User).where(db.User.telegram_id == cb.from_user.id))
        is_favorite = await session.scalar(
            select(db.Favorite).where(db.Favorite.user_id == user.id, db.Favorite.stylist_id == maestro_id)
        )

    btns = []
    for srv in services:
        price = f"{srv.price:,.0f}".replace(",", " ")
        duration_label = {"ru": "мин", "uz": "daq"}[lang]
        btns.append([
            InlineKeyboardButton(
                text=f"{srv.catalog_service.name} - {price} so'm - {srv.duration_min} {duration_label}",
                callback_data=f"srv_{srv.id}",
            )
        ])

    if not services:
        btns.append([
            InlineKeyboardButton(
                text={"ru": "Назад к мастеру", "uz": "Maestroga qaytish"}[lang],
                callback_data=f"back_to_stylist_{stylist.id}",
            )
        ])
        await cb.message.edit_text(
            {
                "ru": f"У <b>{escape(stylist.name)}</b> пока нет добавленных услуг.\nВыберите другого мастера или загляните позже.",
                "uz": f"<b>{escape(stylist.name)}</b> uchun hozircha xizmatlar mavjud emas.\nBoshqa maestroni tanlang yoki keyinroq qayting.",
            }[lang],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
            parse_mode="HTML",
        )
        await cb.answer()
        return

    if not is_favorite:
        btns.append([
            InlineKeyboardButton(
                text={"ru": "Добавить в избранное", "uz": "Sevimlilarga qo'shish"}[lang],
                callback_data=f"fav_add_{stylist.id}",
            )
        ])
    btns.append([
        InlineKeyboardButton(text={"ru": "Назад к мастеру", "uz": "Maestroga qaytish"}[lang], callback_data=f"back_to_stylist_{stylist.id}")
    ])
    await cb.message.edit_text(
        {
            "ru": f"<b>{escape(stylist.name)}</b>\nВыберите услугу для записи.",
            "uz": f"<b>{escape(stylist.name)}</b>\nYozilish uchun xizmatni tanlang.",
        }[lang],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
        parse_mode="HTML",
    )
    await cb.answer()

async def show_calendar_for_service(
    cb: CallbackQuery, stylist_id: int, service_id: int, lang: str
) -> None:
    """
    Календарь свободных дат для пары мастер + услуга.

    Общий шаг для выбора услуги и для повтора прошлой записи: обе дороги
    приводят сюда, и расходиться им незачем.
    """
    current_dt = timeutils.now()

    async with db.async_session() as session:
        available_dates = await get_available_dates_for_month(
            session, stylist_id, service_id, current_dt.year, current_dt.month
        )

    if not available_dates:
        await cb.answer(texts.get_text("booking_no_free_dates", lang), show_alert=True)
        return

    kb = utils.generate_calendar(
        current_dt.year, current_dt.month, maestro_id=stylist_id, available_dates=available_dates
    )
    await cb.message.edit_text(texts.get_text("booking_pick_date", lang), reply_markup=kb)
    await cb.answer()


async def _active_stylist_or_none(session, stylist_id: int):
    """Мастер, к которому сейчас можно записаться."""
    stylist = await session.scalar(
        select(db.Stylist)
        .where(db.Stylist.id == stylist_id)
        .options(joinedload(db.Stylist.user_account))
    )
    if not stylist or not is_stylist_subscription_active(stylist.user_account):
        return None
    return stylist


@router.callback_query(F.data.startswith("srv_"))
async def choose_service_and_show_calendar(cb: CallbackQuery, state: FSMContext):
    if not await ensure_registered_callback(cb):
        return

    lang = await get_user_lang(cb.from_user.id)
    service_id = int(cb.data.split("_")[1])
    draft = await get_booking_draft(state)
    stylist_id = draft.get("stylist_id")
    if not stylist_id:
        await cb.answer(texts.get_text("booking_session_expired", lang), show_alert=True)
        return

    await update_booking_draft(state, service_id=service_id)

    async with db.async_session() as session:
        if not await _active_stylist_or_none(session, stylist_id):
            await cb.answer(texts.get_text("booking_stylist_closed", lang), show_alert=True)
            return

    await show_calendar_for_service(cb, stylist_id, service_id, lang)


@router.callback_query(F.data.startswith("repeat_"))
async def repeat_last_booking(cb: CallbackQuery, state: FSMContext):
    """
    Повтор прошлой записи: тот же мастер, та же услуга, сразу календарь.

    Вернувшийся клиент проходил те же пять экранов, что и новый, хотя в большинстве
    случаев идёт к тому же мастеру на ту же услугу. Здесь пропускаются четыре из них.
    """
    if not await ensure_registered_callback(cb):
        return

    lang = await get_user_lang(cb.from_user.id)
    booking_id = int(cb.data.split("_")[-1])

    async with db.async_session() as session:
        # Идентификатор из callback_data — недоверенный ввод: сверяем владельца.
        booking = await load_booking_for_client(session, booking_id, cb.from_user.id)
        if not booking:
            await deny_access(cb)
            return

        if not await _active_stylist_or_none(session, booking.stylist_id):
            await cb.answer(texts.get_text("booking_stylist_closed", lang), show_alert=True)
            return

        service = await session.get(db.Service, booking.service_id)
        if not service:
            await cb.answer(texts.get_text("repeat_service_gone", lang), show_alert=True)
            return

        stylist_id, service_id = booking.stylist_id, service.id

    await update_booking_draft(state, stylist_id=stylist_id, service_id=service_id)
    logging.info(
        "booking.repeat user_id=%s stylist_id=%s service_id=%s",
        cb.from_user.id, stylist_id, service_id,
    )
    await show_calendar_for_service(cb, stylist_id, service_id, lang)

@router.callback_query(F.data == "ignore")
async def ignore_calendar_button(cb: CallbackQuery):
    await cb.answer()

@router.callback_query(F.data.startswith("dayoff_"))
async def show_dayoff_notice(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    selected_date = cb.data.split("_", 1)[1]
    await cb.answer({
        "ru": f"\u041d\u0430 {selected_date} \u0443 \u043c\u0430\u0441\u0442\u0435\u0440\u0430 \u043d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e\u0433\u043e \u0432\u0440\u0435\u043c\u0435\u043d\u0438. \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0440\u0443\u0433\u043e\u0439 \u0434\u0435\u043d\u044c.",
        "uz": f"{selected_date} sanasida maestro bo'sh emas yoki ishlamaydi. Boshqa kunni tanlang.",
    }[lang], show_alert=True)

@router.callback_query(F.data.startswith("cal_"))
async def switch_calendar_month(cb: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(cb.from_user.id)
    payload = cb.data[len("cal_"):]
    try:
        ym_part, stylist_id_str = payload.rsplit("_", 1)
        year_str, month_str = ym_part.split("-", 1)
        year = int(year_str)
        month = int(month_str)
        stylist_id = int(stylist_id_str)
    except ValueError:
        await cb.answer({"ru": "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043a\u0440\u044b\u0442\u044c \u043a\u0430\u043b\u0435\u043d\u0434\u0430\u0440\u044c.", "uz": "Kalendarni ochib bo'lmadi."}[lang], show_alert=True)
        return

    draft = await get_booking_draft(state)
    service_id = draft.get("service_id")
    if not service_id:
        await cb.answer({"ru": "Время выбора истекло. Начните запись заново.", "uz": "Tanlov sessiyasi tugadi. Qaytadan boshlang."}[lang], show_alert=True)
        return

    async with db.async_session() as session:
        available_dates = await get_available_dates_for_month(session, stylist_id, service_id, year, month)

    kb = utils.generate_calendar(year, month, maestro_id=stylist_id, available_dates=available_dates)
    await cb.message.edit_text(
        {"ru": "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0430\u0442\u0443. \u0421\u0435\u0440\u044b\u0435 \u0434\u043d\u0438 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b \u0434\u043b\u044f \u0437\u0430\u043f\u0438\u0441\u0438.", "uz": "Sanani tanlang. Xira kunlar yozuv uchun yopiq."}[lang],
        reply_markup=kb,
    )
    await cb.answer()

@router.callback_query(F.data.startswith("date_"))
async def pick_time(cb: CallbackQuery, state: FSMContext):
    if not await ensure_registered_callback(cb):
        return

    lang = await get_user_lang(cb.from_user.id)
    selected_date_str = cb.data.split("_")[1]
    selected_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
    draft = await get_booking_draft(state)
    if not {"stylist_id", "service_id"} <= draft.keys():
        await cb.answer({"ru": "Время выбора истекло. Начните запись заново.", "uz": "Sessiya tugadi, qaytadan boshlang."}[lang], show_alert=True)
        return

    stylist_id = draft["stylist_id"]
    service_id = draft["service_id"]
    await update_booking_draft(state, date=selected_date_str)
    async with db.async_session() as session:
        schedule, available_slots = await get_available_slots_for_date(session, stylist_id, service_id, selected_date)

    if not schedule:
        await cb.answer({"ru": "\u041c\u0430\u0441\u0442\u0435\u0440 \u0432 \u044d\u0442\u043e\u0442 \u0434\u0435\u043d\u044c \u043d\u0435 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442.", "uz": "Maestro bu kuni ishlamaydi."}[lang], show_alert=True)
        return

    if not available_slots:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text={"ru": "\u041d\u0430\u0437\u0430\u0434 \u043a \u043a\u0430\u043b\u0435\u043d\u0434\u0430\u0440\u044e", "uz": "Kalendarga qaytish"}[lang], callback_data=f"back_to_calendar_{stylist_id}")
        ]])
        await cb.message.edit_text(
            {
                "ru": f"\u041d\u0430 {selected_date_str} \u0441\u0432\u043e\u0431\u043e\u0434\u043d\u044b\u0445 \u0441\u043b\u043e\u0442\u043e\u0432 \u043d\u0435\u0442.\n\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0440\u0443\u0433\u0443\u044e \u0434\u0430\u0442\u0443.",
                "uz": f"{selected_date_str} sanasida bo'sh slotlar yo'q.\nBoshqa sanani tanlang.",
            }[lang],
            reply_markup=back_kb,
        )
        await cb.answer()
        return

    btns, row = [], []
    for slot in available_slots:
        row.append(InlineKeyboardButton(text=slot, callback_data=f"time_{slot}"))
        if len(row) == 3:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    btns.append([
        InlineKeyboardButton(text={"ru": "\u041d\u0430\u0437\u0430\u0434 \u043a \u043a\u0430\u043b\u0435\u043d\u0434\u0430\u0440\u044e", "uz": "Kalendarga qaytish"}[lang], callback_data=f"back_to_calendar_{stylist_id}")
    ])
    await cb.message.edit_text(
        {"ru": f"\u0414\u0430\u0442\u0430: {selected_date_str}\n\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0432\u0440\u0435\u043c\u044f:", "uz": f"Sana: {selected_date_str}\nVaqtni tanlang:"}[lang],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("back_to_calendar_"))
async def back_to_calendar(cb: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(cb.from_user.id)
    stylist_id = int(cb.data.split("_")[-1])
    draft = await get_booking_draft(state)
    service_id = draft.get("service_id")
    if not service_id:
        await cb.answer({"ru": "\u0421\u0435\u0441\u0441\u0438\u044f \u0432\u044b\u0431\u043e\u0440\u0430 \u0438\u0441\u0442\u0435\u043a\u043b\u0430. \u041d\u0430\u0447\u043d\u0438\u0442\u0435 \u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043d\u043e\u0432\u043e.", "uz": "Tanlov sessiyasi tugadi. Qaytadan boshlang."}[lang], show_alert=True)
        return

    current_dt = datetime.strptime(draft.get("date") or datetime.now().strftime("%Y-%m-%d"), "%Y-%m-%d")
    async with db.async_session() as session:
        available_dates = await get_available_dates_for_month(session, stylist_id, service_id, current_dt.year, current_dt.month)

    kb = utils.generate_calendar(current_dt.year, current_dt.month, maestro_id=stylist_id, available_dates=available_dates)
    await cb.message.edit_text(
        {"ru": "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0430\u0442\u0443. \u0410\u043a\u0442\u0438\u0432\u043d\u044b \u0442\u043e\u043b\u044c\u043a\u043e \u0434\u043d\u0438, \u0433\u0434\u0435 \u0435\u0441\u0442\u044c \u0441\u0432\u043e\u0431\u043e\u0434\u043d\u043e\u0435 \u0432\u0440\u0435\u043c\u044f.", "uz": "Sanani tanlang. Faqat bo'sh vaqti bor ish kunlari faol."}[lang],
        reply_markup=kb,
    )
    await cb.answer()

@router.callback_query(F.data.startswith("time_"))
async def finalize_booking(cb: CallbackQuery, state: FSMContext):
    if not await ensure_registered_callback(cb):
        return

    lang = await get_user_lang(cb.from_user.id)
    selected_time = cb.data.split("_")[1]
    user_id = cb.from_user.id
    data = await get_booking_draft(state)
    if not {"stylist_id", "service_id", "date"} <= data.keys():
        await cb.answer({"ru": "Время выбора истекло. Начните запись заново.", "uz": "Sessiya xatosi. Qaytadan boshlang."}[lang], show_alert=True)
        return

    full_datetime = f"{data['date']} {selected_time}"
    selected_date = datetime.strptime(data['date'], "%Y-%m-%d").date()
    async with db.async_session() as session:
        user_db = await session.scalar(select(db.User).where(db.User.telegram_id == user_id))
        if not user_db or not is_registration_complete(user_db):
            await cb.answer({"ru": "Сначала завершите регистрацию через /start.", "uz": "Avval /start orqali ro'yxatdan o'tishni tugating."}[lang], show_alert=True)
            return
        stylist_profile = await session.scalar(
            select(db.Stylist)
            .where(db.Stylist.id == data['stylist_id'])
            .options(joinedload(db.Stylist.user_account))
        )
        if not stylist_profile or not is_stylist_subscription_active(stylist_profile.user_account):
            await cb.answer({"ru": "Запись к этому мастеру временно закрыта. Выберите другого мастера.", "uz": "Bu maestroga yozilish vaqtincha yopiq. Boshqa maestroni tanlang."}[lang], show_alert=True)
            return
        _, available_slots = await get_available_slots_for_date(session, data['stylist_id'], data['service_id'], selected_date)
        if selected_time not in available_slots:
            await cb.answer({"ru": "Это время уже заняли. Выберите другое.", "uz": "Bu slot endi mavjud emas. Boshqa vaqtni tanlang."}[lang], show_alert=True)
            return
        service = await session.scalar(select(db.Service).where(db.Service.id == data['service_id']).options(joinedload(db.Service.catalog_service)))
        starts_at = timeutils.parse_slot(full_datetime)
        new_booking = db.Booking(
            user_id=user_db.id,
            stylist_id=data['stylist_id'],
            service_id=data['service_id'],
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=service.duration_min),
            status=BOOKING_PENDING,
        )
        session.add(new_booking)
        try:
            await session.commit()
        except IntegrityError:
            # Частичный уникальный индекс uq_active_booking_slot: слот заняли
            # между проверкой свободных слотов и вставкой.
            await session.rollback()
            logging.info(
                "booking.slot_race stylist_id=%s datetime=%s user_id=%s",
                data["stylist_id"], full_datetime, user_id,
            )
            await cb.answer(
                {
                    "ru": "Это время только что заняли. Выберите другое.",
                    "uz": "Bu vaqtni hozirgina band qilishdi. Boshqa vaqtni tanlang.",
                }[lang],
                show_alert=True,
            )
            return
        booking_db_id = new_booking.id
        stylist_user_query = select(db.User.telegram_id).join(db.Stylist, db.Stylist.user_id == db.User.id).where(db.Stylist.id == data['stylist_id'])
        stylist_telegram_id = await session.scalar(stylist_user_query)
        client_name = user_db.first_name or cb.from_user.first_name or "Клиент"
        client_telegram_id = user_db.telegram_id
        client_phone = user_db.phone_number or "не указан"
        service_name = service.catalog_service.name if service and service.catalog_service else "Услуга не указана"

    await clear_booking_draft(state)
    await cb.message.edit_text(
        {
            "ru": f"Заявка отправлена.\n{full_datetime}\n\nМастер посмотрит заявку и ответит в ближайшее время.",
            "uz": f"So'rovingiz yuborildi.\n{full_datetime}\n\nMaestro so'rovni ko'rib chiqadi va tez orada javob beradi.",
        }[lang]
    )

    if stylist_telegram_id:
        admin_text = (
            "<b>Новая заявка</b>\n\n"
            f"Клиент: {escape(client_name)}\n"
            f"Контакт: {escape(client_phone)}\n"
            f'<a href="tg://user?id={client_telegram_id}">Написать в Telegram</a>\n'
            f"Услуга: {escape(service_name)}\n"
            f"Дата и время: {escape(full_datetime)}"
        )
        admin_kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="Подтвердить", callback_data=f"approve_{booking_db_id}"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"decline_{booking_db_id}"),
            ]]
        )
        try:
            await bot.send_message(chat_id=stylist_telegram_id, text=admin_text, reply_markup=admin_kb, parse_mode="HTML")
        except Exception as e:
            logging.warning("notify.new_booking_failed booking_id=%s error=%s", booking_db_id, e)

    await cb.answer()
