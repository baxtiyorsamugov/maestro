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
from logutil import mask_user
from services import audit
from services.access import (
    is_registration_complete,
    is_stylist_subscription_active,
    load_booking_for_client,
)
from services.booking import (
    CHANGE_WINDOW_HOURS,
    can_change_booking,
    get_available_dates_for_month,
    get_available_slots_for_date,
)

router = Router(name="client_booking")


# reschedule_id заполняется только при переносе: это id записи, которую клиент
# двигает. Ключ лежит в том же черновике, потому что дальше идут ровно те же
# шаги — календарь и выбор слота, — и очищаться он должен вместе с ними.
BOOKING_KEYS = ("stylist_id", "service_id", "date", "reschedule_id")

async def get_booking_draft(state: FSMContext) -> dict:
    """Черновик записи из FSM: stylist_id, service_id, date, reschedule_id."""
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
    # reschedule_id гасим явно: клиент мог начать перенос, передумать и зайти
    # в обычную запись. Забытый ключ сдвинул бы старую бронь вместо новой.
    await update_booking_draft(state, stylist_id=maestro_id, reschedule_id=None)

    async with db.async_session() as session:
        services_query = select(db.Service).where(db.Service.stylist_id == maestro_id).options(joinedload(db.Service.catalog_service))
        services = (await session.execute(services_query)).scalars().all()
        stylist_query = select(db.Stylist).where(db.Stylist.id == maestro_id).options(joinedload(db.Stylist.barbershop), joinedload(db.Stylist.user_account))
        stylist = await session.scalar(stylist_query)
        if not stylist:
            await cb.answer(texts.get_text("stylist_not_found", lang), show_alert=True)
            return
        if not is_stylist_subscription_active(stylist.user_account):
            await cb.answer(texts.get_text("booking_stylist_expired", lang), show_alert=True)
            return
        user = await session.scalar(select(db.User).where(db.User.telegram_id == cb.from_user.id))
        is_favorite = await session.scalar(
            select(db.Favorite).where(db.Favorite.user_id == user.id, db.Favorite.stylist_id == maestro_id)
        )

    btns = []
    for srv in services:
        price = f"{srv.price:,.0f}".replace(",", " ")
        duration_label = texts.get_text("services_minutes_short", lang)
        btns.append([
            InlineKeyboardButton(
                text=f"{srv.catalog_service.name} - {price} so'm - {srv.duration_min} {duration_label}",
                callback_data=f"srv_{srv.id}",
            )
        ])

    if not services:
        btns.append([
            InlineKeyboardButton(
                text=texts.get_text("kb_back_to_stylist", lang),
                callback_data=f"back_to_stylist_{stylist.id}",
            )
        ])
        await cb.message.edit_text(
            texts.get_text("booking_no_services", lang).format(name=escape(stylist.name)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
            parse_mode="HTML",
        )
        await cb.answer()
        return

    if not is_favorite:
        btns.append([
            InlineKeyboardButton(
                text=texts.get_text("kb_add_favorite", lang),
                callback_data=f"fav_add_{stylist.id}",
            )
        ])
    btns.append([
        InlineKeyboardButton(text=texts.get_text("kb_back_to_stylist", lang), callback_data=f"back_to_stylist_{stylist.id}")
    ])
    await cb.message.edit_text(
        texts.get_text("booking_pick_service", lang).format(name=escape(stylist.name)),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
        parse_mode="HTML",
    )
    await cb.answer()

async def show_calendar_for_service(
    cb: CallbackQuery,
    stylist_id: int,
    service_id: int,
    lang: str,
    reschedule_id: int | None = None,
) -> None:
    """
    Календарь свободных дат для пары мастер + услуга.

    Общий шаг для выбора услуги, повтора прошлой записи и переноса: все три
    дороги приводят сюда, и расходиться им незачем.

    При переносе переносимая запись исключается из занятости — иначе клиент
    не увидел бы время, которое сам же вот-вот освободит.
    """
    current_dt = timeutils.now()

    async with db.async_session() as session:
        available_dates = await get_available_dates_for_month(
            session,
            stylist_id,
            service_id,
            current_dt.year,
            current_dt.month,
            exclude_booking_id=reschedule_id,
        )

    if not available_dates:
        await cb.answer(texts.get_text("booking_no_free_dates", lang), show_alert=True)
        return

    kb = utils.generate_calendar(
        current_dt.year, current_dt.month, maestro_id=stylist_id,
        available_dates=available_dates, lang=lang,
    )
    prompt = "reschedule_pick_date" if reschedule_id else "booking_pick_date"
    await cb.message.edit_text(texts.get_text(prompt, lang), reply_markup=kb)
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

    await update_booking_draft(
        state, stylist_id=stylist_id, service_id=service_id, reschedule_id=None
    )
    logging.info(
        "booking.repeat user=%s stylist_id=%s service_id=%s",
        mask_user(cb.from_user.id), stylist_id, service_id,
    )
    await show_calendar_for_service(cb, stylist_id, service_id, lang)


@router.callback_query(F.data.startswith("reschedule_"))
async def reschedule_booking(cb: CallbackQuery, state: FSMContext):
    """
    Перенос записи: тот же мастер, та же услуга, новый календарь.

    Раньше клиенту приходилось отменять визит и записываться заново — и в этот
    промежуток слот мог уйти другому. Здесь старая бронь держится до тех пор,
    пока не выбрано новое время (finalize_booking).
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

        allowed, reason = can_change_booking(booking)
        if not allowed:
            await cb.answer(
                texts.get_text(reason, lang).format(hours=CHANGE_WINDOW_HOURS),
                show_alert=True,
            )
            return

        if not await _active_stylist_or_none(session, booking.stylist_id):
            await cb.answer(texts.get_text("booking_stylist_closed", lang), show_alert=True)
            return

        service = await session.get(db.Service, booking.service_id)
        if not service:
            await cb.answer(texts.get_text("reschedule_service_gone", lang), show_alert=True)
            return

        stylist_id, service_id = booking.stylist_id, service.id

    await update_booking_draft(
        state, stylist_id=stylist_id, service_id=service_id, reschedule_id=booking_id
    )
    logging.info(
        "booking.reschedule_started user=%s booking_id=%s",
        mask_user(cb.from_user.id), booking_id,
    )
    await show_calendar_for_service(cb, stylist_id, service_id, lang, reschedule_id=booking_id)

@router.callback_query(F.data == "ignore")
async def ignore_calendar_button(cb: CallbackQuery):
    await cb.answer()

@router.callback_query(F.data.startswith("dayoff_"))
async def show_dayoff_notice(cb: CallbackQuery):
    lang = await get_user_lang(cb.from_user.id)
    selected_date = cb.data.split("_", 1)[1]
    await cb.answer(
        texts.get_text("booking_dayoff_notice", lang).format(date=selected_date), show_alert=True
    )

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
        await cb.answer(texts.get_text("calendar_open_failed", lang), show_alert=True)
        return

    draft = await get_booking_draft(state)
    service_id = draft.get("service_id")
    if not service_id:
        await cb.answer(texts.get_text("booking_session_expired", lang), show_alert=True)
        return

    reschedule_id = draft.get("reschedule_id")
    async with db.async_session() as session:
        # При переносе переносимая запись не должна занимать собственный слот —
        # так же, как в show_calendar_for_service. Без этого в соседнем месяце
        # клиент видел своё же время занятым.
        available_dates = await get_available_dates_for_month(
            session, stylist_id, service_id, year, month,
            exclude_booking_id=reschedule_id,
        )

    kb = utils.generate_calendar(
        year, month, maestro_id=stylist_id, available_dates=available_dates, lang=lang
    )
    prompt = "reschedule_pick_date" if reschedule_id else "booking_pick_date"
    await cb.message.edit_text(texts.get_text(prompt, lang), reply_markup=kb)
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
        await cb.answer(texts.get_text("booking_session_expired", lang), show_alert=True)
        return

    stylist_id = draft["stylist_id"]
    service_id = draft["service_id"]
    await update_booking_draft(state, date=selected_date_str)
    async with db.async_session() as session:
        schedule, available_slots = await get_available_slots_for_date(
            session, stylist_id, service_id, selected_date,
            exclude_booking_id=draft.get("reschedule_id"),
        )

    if not schedule:
        await cb.answer(texts.get_text("booking_day_not_working", lang), show_alert=True)
        return

    if not available_slots:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=texts.get_text("back_to_calendar", lang), callback_data=f"back_to_calendar_{stylist_id}")
        ]])
        await cb.message.edit_text(
            texts.get_text("booking_no_slots_on", lang).format(date=selected_date_str),
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
        InlineKeyboardButton(text=texts.get_text("back_to_calendar", lang), callback_data=f"back_to_calendar_{stylist_id}")
    ])
    await cb.message.edit_text(
        texts.get_text("booking_pick_time", lang).format(date=selected_date_str),
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
        await cb.answer(texts.get_text("booking_session_expired", lang), show_alert=True)
        return

    current_dt = datetime.strptime(draft.get("date") or timeutils.today().strftime("%Y-%m-%d"), "%Y-%m-%d")
    async with db.async_session() as session:
        available_dates = await get_available_dates_for_month(
            session, stylist_id, service_id, current_dt.year, current_dt.month,
            exclude_booking_id=draft.get("reschedule_id"),
        )

    kb = utils.generate_calendar(
        current_dt.year, current_dt.month, maestro_id=stylist_id,
        available_dates=available_dates, lang=lang,
    )
    prompt = "reschedule_pick_date" if draft.get("reschedule_id") else "booking_pick_date"
    await cb.message.edit_text(texts.get_text(prompt, lang), reply_markup=kb)
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
        await cb.answer(texts.get_text("booking_session_expired", lang), show_alert=True)
        return

    full_datetime = f"{data['date']} {selected_time}"
    selected_date = datetime.strptime(data['date'], "%Y-%m-%d").date()
    async with db.async_session() as session:
        user_db = await session.scalar(select(db.User).where(db.User.telegram_id == user_id))
        if not user_db or not is_registration_complete(user_db):
            await cb.answer(texts.get_text("registration_required", lang), show_alert=True)
            return
        stylist_profile = await session.scalar(
            select(db.Stylist)
            .where(db.Stylist.id == data['stylist_id'])
            .options(joinedload(db.Stylist.user_account))
        )
        if not stylist_profile or not is_stylist_subscription_active(stylist_profile.user_account):
            await cb.answer(texts.get_text("booking_closed_pick_other", lang), show_alert=True)
            return
        reschedule_id = data.get("reschedule_id")
        moved_booking = None
        if reschedule_id:
            # Право на запись и окно переноса проверяются ещё раз: между показом
            # календаря и выбором слота визит мог начаться или быть отменён.
            moved_booking = await load_booking_for_client(session, reschedule_id, user_id)
            if not moved_booking:
                await deny_access(cb)
                return
            allowed, reason = can_change_booking(moved_booking)
            if not allowed:
                await cb.answer(
                    texts.get_text(reason, lang).format(hours=CHANGE_WINDOW_HOURS),
                    show_alert=True,
                )
                return

        _, available_slots = await get_available_slots_for_date(
            session, data['stylist_id'], data['service_id'], selected_date,
            exclude_booking_id=reschedule_id,
        )
        if selected_time not in available_slots:
            await cb.answer(texts.get_text("booking_slot_taken", lang), show_alert=True)
            return
        service = await session.scalar(select(db.Service).where(db.Service.id == data['service_id']).options(joinedload(db.Service.catalog_service)))
        starts_at = timeutils.parse_slot(full_datetime)
        ends_at = starts_at + timedelta(minutes=service.duration_min)

        if moved_booking:
            # Двигаем существующую бронь, а не создаём вторую: иначе на время
            # между отменой и новой записью слот оставался бы свободным для других.
            # Старое время запоминаем как datetime, а не как готовую строку:
            # клиенту и мастеру его показывать каждому на своём языке.
            old_starts_at = moved_booking.starts_at
            moved_booking.starts_at = starts_at
            moved_booking.ends_at = ends_at
            # Новое время мастер не согласовывал — возвращаем заявку в ожидание.
            moved_booking.status = BOOKING_PENDING
            target_booking = moved_booking
        else:
            old_starts_at = None
            target_booking = db.Booking(
                user_id=user_db.id,
                stylist_id=data['stylist_id'],
                service_id=data['service_id'],
                starts_at=starts_at,
                ends_at=ends_at,
                status=BOOKING_PENDING,
            )
            session.add(target_booking)

        try:
            # flush до записи в журнал: у новой брони id присваивается здесь,
            # а журнал ссылается именно на него. Транзакция остаётся одна,
            # и гонку по слоту IntegrityError ловит так же — просто раньше.
            await session.flush()
            if moved_booking:
                audit.record_client(
                    session, audit.BOOKING_RESCHEDULED, target_booking,
                    details=f"{timeutils.format_slot(old_starts_at)} -> {full_datetime}",
                )
            else:
                audit.record_client(
                    session, audit.BOOKING_CREATED, target_booking, details=full_datetime
                )
            await session.commit()
        except IntegrityError:
            # Частичный уникальный индекс uq_active_booking_slot: слот заняли
            # между проверкой свободных слотов и записью.
            await session.rollback()
            logging.info(
                "booking.slot_race stylist_id=%s datetime=%s user=%s reschedule_id=%s",
                data["stylist_id"], full_datetime, mask_user(user_id), reschedule_id,
            )
            await cb.answer(texts.get_text("booking_slot_just_taken", lang), show_alert=True)
            return
        booking_db_id = target_booking.id
        stylist_contact_query = (
            select(db.User.telegram_id, db.User.language_code)
            .join(db.Stylist, db.Stylist.user_id == db.User.id)
            .where(db.Stylist.id == data['stylist_id'])
        )
        stylist_contact = (await session.execute(stylist_contact_query)).first()
        stylist_telegram_id = stylist_contact[0] if stylist_contact else None
        stylist_lang = (stylist_contact[1] if stylist_contact else None) or "ru"
        # Подстановки читает мастер — поэтому на его языке.
        client_name = (
            user_db.first_name or cb.from_user.first_name
            or texts.get_text("booking_client", stylist_lang)
        )
        client_telegram_id = user_db.telegram_id
        client_phone = user_db.phone_number or texts.get_text("booking_phone_unknown", stylist_lang)
        service_name = (
            service.catalog_service.name if service and service.catalog_service
            else texts.get_text("booking_service_unknown", stylist_lang)
        )

    await clear_booking_draft(state)
    if old_starts_at:
        logging.info(
            "booking.rescheduled booking_id=%s user=%s new_slot=%s",
            booking_db_id, mask_user(user_id), full_datetime,
        )
        await cb.message.edit_text(
            texts.get_text("reschedule_done", lang).format(
                slot=timeutils.format_human(starts_at, lang)
            )
        )
    else:
        await cb.message.edit_text(
            texts.get_text("booking_request_sent", lang).format(
                slot=timeutils.format_human(starts_at, lang)
            )
        )

    if stylist_telegram_id:
        if old_starts_at:
            admin_text = texts.get_text("reschedule_notice_stylist", stylist_lang).format(
                client=escape(client_name),
                service=escape(service_name),
                old_slot=escape(timeutils.format_human(old_starts_at, stylist_lang)),
                new_slot=escape(timeutils.format_human(starts_at, stylist_lang)),
            )
        else:
            # Раньше это уведомление всегда уходило по-русски, хотя кнопки
            # под ним уже были на языке мастера.
            t = lambda key: texts.get_text(key, stylist_lang)  # noqa: E731
            admin_text = (
                f"<b>{t('booking_card_title')}</b>\n\n"
                f"{t('booking_client')}: {escape(client_name)}\n"
                f"{t('booking_contact')}: {escape(client_phone)}\n"
                f'<a href="tg://user?id={client_telegram_id}">{t("booking_write_telegram")}</a>\n'
                f"{t('booking_service')}: {escape(service_name)}\n"
                f"{t('booking_datetime')}: {escape(full_datetime)}"
            )
        # Кнопки на языке мастера: уведомление читает он, а не клиент.
        admin_kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text=texts.get_text("btn_approve_booking", stylist_lang),
                    callback_data=f"approve_{booking_db_id}",
                ),
                InlineKeyboardButton(
                    text=texts.get_text("btn_decline_booking", stylist_lang),
                    callback_data=f"decline_{booking_db_id}",
                ),
            ]]
        )
        try:
            await bot.send_message(chat_id=stylist_telegram_id, text=admin_text, reply_markup=admin_kb, parse_mode="HTML")
        except Exception as e:
            event = "reschedule" if old_starts_at else "new_booking"
            logging.warning("notify.%s_failed booking_id=%s error=%s", event, booking_db_id, e)

    await cb.answer()
