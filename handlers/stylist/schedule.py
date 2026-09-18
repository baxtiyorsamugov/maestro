"""
Расписание мастера: недельный график и исключения по датам.
"""
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

import database as db
import timeutils
from constants import DAY_LABELS
from guards import (
    ensure_active_stylist_callback,
    ensure_active_stylist_message,
)
from keyboards import (
    get_schedule_management_kb,
    get_schedule_time_kb,
    get_special_date_actions_kb,
    get_special_dates_calendar_kb,
    get_special_schedule_time_kb,
)
from presenters import (
    build_schedule_overview_text,
    build_special_date_detail_text,
    build_special_dates_text,
)
from services.booking import load_special_dates
from states import ScheduleForm, SpecialDateForm

router = Router(name="stylist_schedule")


async def render_schedule_overview(target, stylist: db.Stylist):
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
        build_schedule_overview_text(stylist.name, schedule_map, special_dates),
        reply_markup=get_schedule_management_kb(schedule_map),
        parse_mode="HTML",
    )

async def render_special_dates_calendar(target, stylist: db.Stylist, year: int, month: int):
    async with db.async_session() as session:
        special_dates = await load_special_dates(session, stylist.id)
    await target.edit_text(
        build_special_dates_text(stylist.name, year, month, special_dates),
        reply_markup=get_special_dates_calendar_kb(year, month, stylist.id),
        parse_mode="HTML",
    )

def parse_special_callback_parts(data: str, prefix: str):
    payload = data[len(prefix):]
    target_date, remainder = payload.split("_", 1)
    return target_date, remainder

@router.callback_query(F.data == "schedule_close")
async def schedule_close(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Управление расписанием закрыто.")
    await cb.answer()

@router.callback_query(F.data == "cancel_fsm")
async def cancel_fsm_handler(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Действие отменено.", reply_markup=None)
    await cb.answer()

@router.message(F.text == "🕒 Управление расписанием")
async def manage_schedule(message: Message):
    user, stylist = await ensure_active_stylist_message(message)
    if not (user and stylist):
        return

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
        build_schedule_overview_text(stylist.name, schedule_map, special_dates),
        reply_markup=get_schedule_management_kb(schedule_map),
        parse_mode="HTML",
    )

@router.callback_query(F.data == "schedule_weekly")
async def back_to_weekly_schedule(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    await state.clear()
    await render_schedule_overview(cb.message, stylist)
    await cb.answer()

@router.callback_query(F.data == "schedule_special_dates")
async def open_special_dates(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    await state.clear()
    today = timeutils.today()
    await render_special_dates_calendar(cb.message, stylist, today.year, today.month)
    await cb.answer()

@router.callback_query(F.data.startswith("spec_cal_"))
async def switch_special_dates_month(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    payload = cb.data[len("spec_cal_"):]
    ym_part, _ = payload.rsplit("_", 1)
    year_str, month_str = ym_part.split("-", 1)
    await render_special_dates_calendar(cb.message, stylist, int(year_str), int(month_str))
    await cb.answer()

@router.callback_query(F.data.startswith("specdate_"))
async def open_special_date_details(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    payload = cb.data[len("specdate_"):]
    target_date, _ = payload.rsplit("_", 1)
    work_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    async with db.async_session() as session:
        weekly_schedule = await session.scalar(
            select(db.Schedule).where(
                db.Schedule.stylist_id == stylist.id,
                db.Schedule.day_of_week == work_date.isoweekday(),
            )
        )
        special_schedule = await session.scalar(
            select(db.SpecialSchedule).where(
                db.SpecialSchedule.stylist_id == stylist.id,
                db.SpecialSchedule.work_date == work_date,
            )
        )

    await state.clear()
    await cb.message.edit_text(
        build_special_date_detail_text(target_date, weekly_schedule, special_schedule),
        reply_markup=get_special_date_actions_kb(target_date, stylist.id, bool(special_schedule)),
        parse_mode="HTML",
    )
    await cb.answer()

@router.callback_query(F.data.startswith("special_day_off_"))
async def set_special_day_off(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    payload = cb.data[len("special_day_off_"):]
    target_date, _ = payload.rsplit("_", 1)
    work_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    async with db.async_session() as session:
        special_schedule = await session.scalar(
            select(db.SpecialSchedule).where(
                db.SpecialSchedule.stylist_id == stylist.id,
                db.SpecialSchedule.work_date == work_date,
            )
        )
        if special_schedule:
            special_schedule.is_day_off = True
            special_schedule.start_time = None
            special_schedule.end_time = None
        else:
            session.add(db.SpecialSchedule(stylist_id=stylist.id, work_date=work_date, is_day_off=True))
        await session.commit()
        weekly_schedule = await session.scalar(
            select(db.Schedule).where(
                db.Schedule.stylist_id == stylist.id,
                db.Schedule.day_of_week == work_date.isoweekday(),
            )
        )

    await state.clear()
    await cb.message.edit_text(
        build_special_date_detail_text(target_date, weekly_schedule, db.SpecialSchedule(work_date=work_date, is_day_off=True)),
        reply_markup=get_special_date_actions_kb(target_date, stylist.id, True),
        parse_mode="HTML",
    )
    await cb.answer("День отмечен как выходной.")

@router.callback_query(F.data.startswith("special_delete_"))
async def delete_special_schedule(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    payload = cb.data[len("special_delete_"):]
    target_date, stylist_id = payload.rsplit("_", 1)
    work_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    async with db.async_session() as session:
        special_schedule = await session.scalar(
            select(db.SpecialSchedule).where(
                db.SpecialSchedule.stylist_id == stylist.id,
                db.SpecialSchedule.work_date == work_date,
            )
        )
        if special_schedule:
            await session.delete(special_schedule)
            await session.commit()

    await state.clear()
    await cb.message.edit_text(
        "Исключение удалено. Для этой даты снова работает недельный шаблон.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⬅️ К календарю", callback_data=f"spec_cal_{target_date[:7]}_{stylist_id}"),
        ]]),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("special_set_hours_"))
async def start_special_hours_setup(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    payload = cb.data[len("special_set_hours_"):]
    target_date, _ = payload.rsplit("_", 1)
    await state.update_data(target_date=target_date)
    await state.set_state(SpecialDateForm.start_time)
    await cb.message.edit_text(
        f"{target_date}: выберите время начала работы.",
        reply_markup=get_special_schedule_time_kb(target_date, "start"),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("special_back_start_"))
async def special_back_to_start(cb: CallbackQuery, state: FSMContext):
    target_date = cb.data[len("special_back_start_"):]
    await state.update_data(target_date=target_date)
    await state.set_state(SpecialDateForm.start_time)
    await cb.message.edit_text(
        f"{target_date}: выберите время начала работы.",
        reply_markup=get_special_schedule_time_kb(target_date, "start"),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("special_start_"))
async def process_special_start_time_choice(cb: CallbackQuery, state: FSMContext):
    target_date, start_t = parse_special_callback_parts(cb.data, "special_start_")
    await state.update_data(target_date=target_date, start_time=start_t)
    await state.set_state(SpecialDateForm.end_time)
    await cb.message.edit_text(
        f"{target_date}: выберите время окончания работы.",
        reply_markup=get_special_schedule_time_kb(target_date, "end", start_t),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("special_end_"))
async def process_special_end_time_choice(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    target_date, end_t = parse_special_callback_parts(cb.data, "special_end_")
    data = await state.get_data()
    start_t = data.get("start_time")

    if not start_t or target_date != data.get("target_date"):
        await state.clear()
        await cb.answer("Сессия выбора времени истекла. Начните заново.", show_alert=True)
        return

    work_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    async with db.async_session() as session:
        special_schedule = await session.scalar(
            select(db.SpecialSchedule).where(
                db.SpecialSchedule.stylist_id == stylist.id,
                db.SpecialSchedule.work_date == work_date,
            )
        )
        if special_schedule:
            special_schedule.is_day_off = False
            special_schedule.start_time = start_t
            special_schedule.end_time = end_t
        else:
            session.add(db.SpecialSchedule(
                stylist_id=stylist.id,
                work_date=work_date,
                start_time=start_t,
                end_time=end_t,
                is_day_off=False,
            ))
        await session.commit()

        weekly_schedule = await session.scalar(
            select(db.Schedule).where(
                db.Schedule.stylist_id == stylist.id,
                db.Schedule.day_of_week == work_date.isoweekday(),
            )
        )
        saved_special = await session.scalar(
            select(db.SpecialSchedule).where(
                db.SpecialSchedule.stylist_id == stylist.id,
                db.SpecialSchedule.work_date == work_date,
            )
        )

    await state.clear()
    await cb.message.edit_text(
        build_special_date_detail_text(target_date, weekly_schedule, saved_special),
        reply_markup=get_special_date_actions_kb(target_date, stylist.id, True),
        parse_mode="HTML",
    )
    await cb.answer(f"На {target_date} сохранены часы: {start_t}-{end_t}")

@router.callback_query(F.data.startswith("set_day_off_"))
async def set_day_off(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return

    day_of_week = int(cb.data.split("_")[-1])
    async with db.async_session() as session:
        existing_schedule = await session.scalar(select(db.Schedule).where(db.Schedule.stylist_id == stylist.id, db.Schedule.day_of_week == day_of_week))
        if existing_schedule:
            await session.delete(existing_schedule)
            await session.commit()
    await state.clear()
    await render_schedule_overview(cb.message, stylist)
    await cb.answer(f"{DAY_LABELS[day_of_week]} теперь выходной")

@router.callback_query(F.data.startswith("set_day_"))
async def process_day_of_week(cb: CallbackQuery, state: FSMContext):
    day_of_week = int(cb.data.split("_")[-1])
    await state.update_data(day_of_week=day_of_week)
    await state.set_state(ScheduleForm.start_time)
    await cb.message.edit_text(
        f"{DAY_LABELS[day_of_week]}: выберите время начала работы.",
        reply_markup=get_schedule_time_kb(day_of_week, "start"),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("schedule_back_start_"))
async def schedule_back_to_start(cb: CallbackQuery, state: FSMContext):
    day_of_week = int(cb.data.split("_")[-1])
    await state.update_data(day_of_week=day_of_week)
    await state.set_state(ScheduleForm.start_time)
    await cb.message.edit_text(
        f"{DAY_LABELS[day_of_week]}: выберите время начала работы.",
        reply_markup=get_schedule_time_kb(day_of_week, "start"),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("schedule_start_"))
async def process_start_time_choice(cb: CallbackQuery, state: FSMContext):
    _, _, day_str, start_t = cb.data.split("_", 3)
    day_of_week = int(day_str)
    await state.update_data(day_of_week=day_of_week, start_time=start_t)
    await state.set_state(ScheduleForm.end_time)
    await cb.message.edit_text(
        f"{DAY_LABELS[day_of_week]}: выберите время окончания работы.",
        reply_markup=get_schedule_time_kb(day_of_week, "end", start_t),
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

    if not start_t or day != data.get("day_of_week"):
        await state.clear()
        await cb.answer("Сессия выбора времени истекла. Начните заново.", show_alert=True)
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
    await render_schedule_overview(cb.message, stylist)
    await cb.answer(f"График на {DAY_LABELS[day]} сохранён: {start_t}-{end_t}")

@router.message(ScheduleForm.start_time)
async def process_start_time(message: Message, state: FSMContext):
    data = await state.get_data()
    day = data.get("day_of_week")
    if not day:
        await state.clear()
        await message.answer("\u0421\u0435\u0441\u0441\u0438\u044f \u0432\u044b\u0431\u043e\u0440\u0430 \u0432\u0440\u0435\u043c\u0435\u043d\u0438 \u0438\u0441\u0442\u0435\u043a\u043b\u0430. \u041d\u0430\u0447\u043d\u0438\u0442\u0435 \u0437\u0430\u043d\u043e\u0432\u043e.")
        return
    await message.answer(
        f"{DAY_LABELS[day]}: \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0432\u0440\u0435\u043c\u044f \u043d\u0430\u0447\u0430\u043b\u0430 \u0440\u0430\u0431\u043e\u0442\u044b \u043a\u043d\u043e\u043f\u043a\u0430\u043c\u0438 \u043d\u0438\u0436\u0435.",
        reply_markup=get_schedule_time_kb(day, "start"),
    )

@router.message(ScheduleForm.end_time)
async def process_end_time(message: Message, state: FSMContext):
    data = await state.get_data()
    day = data.get("day_of_week")
    start_t = data.get("start_time")
    if not day or not start_t:
        await state.clear()
        await message.answer("\u0421\u0435\u0441\u0441\u0438\u044f \u0432\u044b\u0431\u043e\u0440\u0430 \u0432\u0440\u0435\u043c\u0435\u043d\u0438 \u0438\u0441\u0442\u0435\u043a\u043b\u0430. \u041d\u0430\u0447\u043d\u0438\u0442\u0435 \u0437\u0430\u043d\u043e\u0432\u043e.")
        return
    await message.answer(
        f"{DAY_LABELS[day]}: \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0432\u0440\u0435\u043c\u044f \u043e\u043a\u043e\u043d\u0447\u0430\u043d\u0438\u044f \u0440\u0430\u0431\u043e\u0442\u044b \u043a\u043d\u043e\u043f\u043a\u0430\u043c\u0438 \u043d\u0438\u0436\u0435.",
        reply_markup=get_schedule_time_kb(day, "end", start_t),
    )
