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
from constants import day_name
from guards import (
    ensure_active_stylist_callback,
    ensure_active_stylist_message,
    get_user_lang,
)
from keyboards import (
    get_schedule_management_kb,
    get_schedule_time_kb,
)
from presenters import (
    build_schedule_overview_text,
)
from states import ScheduleForm

router = Router(name="stylist_schedule")


async def render_schedule_overview(target, stylist: db.Stylist, lang: str = "ru"):
    async with db.async_session() as session:
        schedules = (await session.execute(
            select(db.Schedule)
            .where(db.Schedule.stylist_id == stylist.id)
            .order_by(db.Schedule.day_of_week)
        )).scalars().all()
        special_dates = (await session.execute(
            select(db.SpecialSchedule)
            .where(db.SpecialSchedule.stylist_id == stylist.id, db.SpecialSchedule.work_date >= timeutils.today())
            .order_by(db.SpecialSchedule.work_date)
        )).scalars().all()
        schedule_map = {item.day_of_week: item for item in schedules}
    await target.edit_text(
        build_schedule_overview_text(stylist.name, schedule_map, special_dates, lang),
        reply_markup=get_schedule_management_kb(schedule_map, lang),
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
        schedules = (await session.execute(
            select(db.Schedule)
            .where(db.Schedule.stylist_id == stylist.id)
            .order_by(db.Schedule.day_of_week)
        )).scalars().all()
        special_dates = (await session.execute(
            select(db.SpecialSchedule)
            .where(db.SpecialSchedule.stylist_id == stylist.id, db.SpecialSchedule.work_date >= timeutils.today())
            .order_by(db.SpecialSchedule.work_date)
        )).scalars().all()
        schedule_map = {item.day_of_week: item for item in schedules}

    await message.answer(
        build_schedule_overview_text(stylist.name, schedule_map, special_dates, lang),
        reply_markup=get_schedule_management_kb(schedule_map, lang),
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
