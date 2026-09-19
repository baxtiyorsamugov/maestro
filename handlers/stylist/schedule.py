"""
Расписание мастера: недельный график и исключения по датам.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
)
from sqlalchemy import select

import database as db
import texts
import timeutils
from constants import TIME_OPTIONS, day_name
from guards import (
    ensure_active_stylist_callback,
    ensure_active_stylist_message,
    get_user_lang,
)
from keyboards import (
    get_break_days_kb,
    get_break_time_kb,
    get_buffer_kb,
    get_schedule_management_kb,
    get_schedule_time_kb,
)
from presenters import (
    build_schedule_overview_text,
    format_buffer,
)
from services.booking import BUFFER_CHOICES, get_stylist_buffer
from states import BreakForm, ScheduleForm

router = Router(name="stylist_schedule")


def _next_option(time_value: str) -> str:
    """
    Следующее значение в сетке времени.

    Нужно, чтобы конец перерыва нельзя было поставить равным началу.
    Если значение почему-то последнее в сетке — возвращаем его же:
    клавиатура тогда окажется пустой, и это лучше, чем IndexError.
    """
    try:
        return TIME_OPTIONS[TIME_OPTIONS.index(time_value) + 1]
    except (ValueError, IndexError):
        return time_value


async def load_schedule_map(session, stylist_id: int) -> dict[int, db.Schedule]:
    schedules = (await session.execute(
        select(db.Schedule)
        .where(db.Schedule.stylist_id == stylist_id)
        .order_by(db.Schedule.day_of_week)
    )).scalars().all()
    return {item.day_of_week: item for item in schedules}


async def render_schedule_overview(target, stylist: db.Stylist, lang: str = "ru"):
    async with db.async_session() as session:
        schedule_map = await load_schedule_map(session, stylist.id)
        special_dates = (await session.execute(
            select(db.SpecialSchedule)
            .where(db.SpecialSchedule.stylist_id == stylist.id, db.SpecialSchedule.work_date >= timeutils.today())
            .order_by(db.SpecialSchedule.work_date)
        )).scalars().all()
        buffer_min = await get_stylist_buffer(session, stylist.id)
    await target.edit_text(
        build_schedule_overview_text(stylist.name, schedule_map, special_dates, lang),
        reply_markup=get_schedule_management_kb(schedule_map, lang, buffer_min),
        parse_mode="HTML",
    )



@router.callback_query(F.data == "schedule_close")
async def schedule_close(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(cb.from_user.id)
    await cb.message.edit_text(texts.get_text("schedule_closed", lang))
    await cb.answer()

@router.callback_query(F.data == "cancel_fsm")
async def cancel_fsm_handler(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(cb.from_user.id)
    await cb.message.edit_text(texts.get_text("action_cancelled", lang), reply_markup=None)
    await cb.answer()

@router.message(F.text.in_(texts.all_variants("manage_schedule")))
async def manage_schedule(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return
    lang = await get_user_lang(message.from_user.id)

    async with db.async_session() as session:
        schedule_map = await load_schedule_map(session, stylist.id)
        special_dates = (await session.execute(
            select(db.SpecialSchedule)
            .where(db.SpecialSchedule.stylist_id == stylist.id, db.SpecialSchedule.work_date >= timeutils.today())
            .order_by(db.SpecialSchedule.work_date)
        )).scalars().all()
        buffer_min = await get_stylist_buffer(session, stylist.id)

    await message.answer(
        build_schedule_overview_text(stylist.name, schedule_map, special_dates, lang),
        reply_markup=get_schedule_management_kb(schedule_map, lang, buffer_min),
        parse_mode="HTML",
    )

@router.callback_query(F.data == "schedule_weekly")
async def back_to_weekly_schedule(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    lang = await get_user_lang(cb.from_user.id)
    await state.clear()
    await render_schedule_overview(cb.message, stylist, lang)
    await cb.answer()










@router.callback_query(F.data == "buffer_menu")
async def buffer_menu(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    await state.clear()
    async with db.async_session() as session:
        current = await get_stylist_buffer(session, stylist.id)

    await cb.message.edit_text(
        texts.get_text("buffer_title", lang),
        reply_markup=get_buffer_kb(current, lang),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("buffer_set_"))
async def buffer_set(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    minutes = int(cb.data.split("_")[-1])
    if minutes not in BUFFER_CHOICES:
        # Значение пришло из callback_data, то есть от клиента Telegram.
        # Свой список вариантов надёжнее, чем доверие к присланному числу.
        await cb.answer(texts.get_text("fallback_button_outdated", lang), show_alert=True)
        return

    async with db.async_session() as session:
        target = await session.get(db.Stylist, stylist.id)
        target.buffer_min = minutes
        await session.commit()

    await render_schedule_overview(cb.message, stylist, lang)
    await cb.answer(
        texts.get_text("buffer_saved", lang).format(value=format_buffer(minutes, lang))
    )


@router.callback_query(F.data == "brk_menu")
async def break_menu(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    await state.clear()
    async with db.async_session() as session:
        schedule_map = await load_schedule_map(session, stylist.id)

    await cb.message.edit_text(
        texts.get_text("break_title", lang),
        reply_markup=get_break_days_kb(schedule_map, lang),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("brk_day_"))
async def break_pick_start(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    day = int(cb.data.split("_")[-1])
    async with db.async_session() as session:
        schedule = await session.scalar(
            select(db.Schedule).where(
                db.Schedule.stylist_id == stylist.id, db.Schedule.day_of_week == day
            )
        )

    if not schedule:
        # Перерыв внутри выходного не имеет смысла, и молча ничего не делать
        # тоже нельзя: мастер решит, что кнопка сломана.
        await cb.answer(
            texts.get_text("break_day_off_hint", lang).format(day=day_name(day, lang)),
            show_alert=True,
        )
        return

    await state.set_state(BreakForm.start_time)
    await state.update_data(day_of_week=day)
    await cb.message.edit_text(
        texts.get_text("break_pick_start", lang).format(
            day=day_name(day, lang), start=schedule.start_time, end=schedule.end_time
        ),
        reply_markup=get_break_time_kb(
            day, "start", schedule.start_time, schedule.end_time, lang
        ),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("brk_clear_"))
async def break_clear(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    day = int(cb.data.split("_")[-1])
    async with db.async_session() as session:
        schedule = await session.scalar(
            select(db.Schedule).where(
                db.Schedule.stylist_id == stylist.id, db.Schedule.day_of_week == day
            )
        )
        if schedule:
            schedule.break_start = None
            schedule.break_end = None
            await session.commit()

    await state.clear()
    await render_schedule_overview(cb.message, stylist, lang)
    await cb.answer(texts.get_text("break_cleared", lang).format(day=day_name(day, lang)))


@router.callback_query(F.data.startswith("brk_start_"))
async def break_pick_end(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    _, _, day_str, start_t = cb.data.split("_", 3)
    day = int(day_str)
    lang = await get_user_lang(cb.from_user.id)

    async with db.async_session() as session:
        schedule = await session.scalar(
            select(db.Schedule).where(
                db.Schedule.stylist_id == stylist.id, db.Schedule.day_of_week == day
            )
        )
    if not schedule:
        await state.clear()
        await cb.answer(texts.get_text("schedule_session_expired", lang), show_alert=True)
        return

    await state.set_state(BreakForm.end_time)
    await state.update_data(day_of_week=day, break_start=start_t)
    await cb.message.edit_text(
        texts.get_text("break_pick_end", lang).format(day=day_name(day, lang), start=start_t),
        # Нижняя граница — следующие полчаса после начала: перерыв нулевой
        # длины выбрать нельзя, и объяснять потом ошибку не придётся.
        reply_markup=get_break_time_kb(
            day, "end", _next_option(start_t), schedule.end_time, lang
        ),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("brk_end_"))
async def break_save(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    _, _, day_str, end_t = cb.data.split("_", 3)
    day = int(day_str)
    data = await state.get_data()
    start_t = data.get("break_start")
    lang = await get_user_lang(cb.from_user.id)

    if not start_t or day != data.get("day_of_week") or end_t <= start_t:
        await state.clear()
        await cb.answer(texts.get_text("schedule_session_expired", lang), show_alert=True)
        return

    async with db.async_session() as session:
        schedule = await session.scalar(
            select(db.Schedule).where(
                db.Schedule.stylist_id == stylist.id, db.Schedule.day_of_week == day
            )
        )
        if not schedule:
            await state.clear()
            await cb.answer(texts.get_text("schedule_session_expired", lang), show_alert=True)
            return
        schedule.break_start = start_t
        schedule.break_end = end_t
        await session.commit()

    await state.clear()
    await render_schedule_overview(cb.message, stylist, lang)
    await cb.answer(
        texts.get_text("break_saved", lang).format(
            day=day_name(day, lang), start=start_t, end=end_t
        )
    )


@router.callback_query(F.data.startswith("set_day_off_"))
async def set_day_off(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    lang = await get_user_lang(cb.from_user.id)
    day_of_week = int(cb.data.split("_")[-1])
    async with db.async_session() as session:
        existing_schedule = await session.scalar(select(db.Schedule).where(db.Schedule.stylist_id == stylist.id, db.Schedule.day_of_week == day_of_week))
        if existing_schedule:
            await session.delete(existing_schedule)
            await session.commit()
    await state.clear()
    await render_schedule_overview(cb.message, stylist, lang)
    await cb.answer(
        texts.get_text("schedule_day_off_set", lang).format(day=day_name(day_of_week, lang))
    )

@router.callback_query(F.data.startswith("set_day_"))
async def process_day_of_week(cb: CallbackQuery, state: FSMContext):
    day_of_week = int(cb.data.split("_")[-1])
    lang = await get_user_lang(cb.from_user.id)
    await state.update_data(day_of_week=day_of_week)
    await state.set_state(ScheduleForm.start_time)
    await cb.message.edit_text(
        texts.get_text("schedule_pick_start", lang).format(day=day_name(day_of_week, lang)),
        reply_markup=get_schedule_time_kb(day_of_week, "start", lang=lang),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("schedule_back_start_"))
async def schedule_back_to_start(cb: CallbackQuery, state: FSMContext):
    day_of_week = int(cb.data.split("_")[-1])
    lang = await get_user_lang(cb.from_user.id)
    await state.update_data(day_of_week=day_of_week)
    await state.set_state(ScheduleForm.start_time)
    await cb.message.edit_text(
        texts.get_text("schedule_pick_start", lang).format(day=day_name(day_of_week, lang)),
        reply_markup=get_schedule_time_kb(day_of_week, "start", lang=lang),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("schedule_start_"))
async def process_start_time_choice(cb: CallbackQuery, state: FSMContext):
    _, _, day_str, start_t = cb.data.split("_", 3)
    day_of_week = int(day_str)
    lang = await get_user_lang(cb.from_user.id)
    await state.update_data(day_of_week=day_of_week, start_time=start_t)
    await state.set_state(ScheduleForm.end_time)
    await cb.message.edit_text(
        texts.get_text("schedule_pick_end", lang).format(day=day_name(day_of_week, lang)),
        reply_markup=get_schedule_time_kb(day_of_week, "end", start_t, lang),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("schedule_end_"))
async def process_end_time_choice(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    _, _, day_str, end_t = cb.data.split("_", 3)
    data = await state.get_data()
    day = int(day_str)
    start_t = data.get("start_time")

    lang = await get_user_lang(cb.from_user.id)
    if not start_t or day != data.get("day_of_week"):
        await state.clear()
        await cb.answer(texts.get_text("schedule_session_expired", lang), show_alert=True)
        return

    async with db.async_session() as session:
        existing_schedule = await session.scalar(select(db.Schedule).where(db.Schedule.stylist_id == stylist.id, db.Schedule.day_of_week == day))
        if existing_schedule:
            existing_schedule.start_time = start_t
            existing_schedule.end_time = end_t
        else:
            session.add(db.Schedule(stylist_id=stylist.id, day_of_week=day, start_time=start_t, end_time=end_t))
        await session.commit()

    await state.clear()
    await render_schedule_overview(cb.message, stylist, lang)
    await cb.answer(
        texts.get_text("schedule_saved", lang).format(
            day=day_name(day, lang), start=start_t, end=end_t
        )
    )

@router.message(ScheduleForm.start_time)
async def process_start_time(message: Message, state: FSMContext):
    data = await state.get_data()
    day = data.get("day_of_week")
    lang = await get_user_lang(message.from_user.id)
    if not day:
        await state.clear()
        await message.answer(texts.get_text("schedule_session_expired", lang))
        return
    await message.answer(
        texts.get_text("schedule_pick_start_buttons", lang).format(day=day_name(day, lang)),
        reply_markup=get_schedule_time_kb(day, "start", lang=lang),
    )

@router.message(ScheduleForm.end_time)
async def process_end_time(message: Message, state: FSMContext):
    data = await state.get_data()
    day = data.get("day_of_week")
    start_t = data.get("start_time")
    lang = await get_user_lang(message.from_user.id)
    if not day or not start_t:
        await state.clear()
        await message.answer(texts.get_text("schedule_session_expired", lang))
        return
    await message.answer(
        texts.get_text("schedule_pick_end_buttons", lang).format(day=day_name(day, lang)),
        reply_markup=get_schedule_time_kb(day, "end", start_t, lang),
    )
