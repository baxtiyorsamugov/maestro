"""
Исключения по датам: выходные и особые часы работы.
"""
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from sqlalchemy import select

import database as db
import texts
import timeutils
from guards import (
    ensure_active_stylist_callback,
    get_user_lang,
)
from keyboards import (
    get_special_date_actions_kb,
    get_special_dates_calendar_kb,
    get_special_schedule_time_kb,
)
from presenters import (
    build_special_date_detail_text,
    build_special_dates_text,
)
from services.booking import load_special_dates
from states import SpecialDateForm

router = Router(name="stylist_special_dates")


async def render_special_dates_calendar(
    target, stylist: db.Stylist, year: int, month: int, lang: str = "ru"
):
    async with db.async_session() as session:
        special_dates = await load_special_dates(session, stylist.id)
    await target.edit_text(
        build_special_dates_text(stylist.name, year, month, special_dates, lang),
        reply_markup=get_special_dates_calendar_kb(year, month, stylist.id, lang),
        parse_mode="HTML",
    )

def parse_special_callback_parts(data: str, prefix: str):
    payload = data[len(prefix):]
    target_date, remainder = payload.split("_", 1)
    return target_date, remainder

@router.callback_query(F.data == "schedule_special_dates")
async def open_special_dates(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    lang = await get_user_lang(cb.from_user.id)
    await state.clear()
    today = timeutils.today()
    await render_special_dates_calendar(cb.message, stylist, today.year, today.month, lang)
    await cb.answer()

@router.callback_query(F.data.startswith("spec_cal_"))
async def switch_special_dates_month(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    lang = await get_user_lang(cb.from_user.id)
    payload = cb.data[len("spec_cal_"):]
    ym_part, _ = payload.rsplit("_", 1)
    year_str, month_str = ym_part.split("-", 1)
    await render_special_dates_calendar(
        cb.message, stylist, int(year_str), int(month_str), lang
    )
    await cb.answer()

@router.callback_query(F.data.startswith("specdate_"))
async def open_special_date_details(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    lang = await get_user_lang(cb.from_user.id)
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
        build_special_date_detail_text(target_date, weekly_schedule, special_schedule, lang),
        reply_markup=get_special_date_actions_kb(target_date, stylist.id, bool(special_schedule), lang),
        parse_mode="HTML",
    )
    await cb.answer()

@router.callback_query(F.data.startswith("special_day_off_"))
async def set_special_day_off(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    lang = await get_user_lang(cb.from_user.id)
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
        build_special_date_detail_text(
            target_date,
            weekly_schedule,
            db.SpecialSchedule(work_date=work_date, is_day_off=True),
            lang,
        ),
        reply_markup=get_special_date_actions_kb(target_date, stylist.id, True, lang),
        parse_mode="HTML",
    )
    await cb.answer(texts.get_text("special_day_off_set", lang))

@router.callback_query(F.data.startswith("special_delete_"))
async def delete_special_schedule(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    lang = await get_user_lang(cb.from_user.id)
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
        texts.get_text("special_removed", lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=texts.get_text("back_to_calendar", lang),
                callback_data=f"spec_cal_{target_date[:7]}_{stylist_id}",
            ),
        ]]),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("special_set_hours_"))
async def start_special_hours_setup(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    lang = await get_user_lang(cb.from_user.id)
    payload = cb.data[len("special_set_hours_"):]
    target_date, _ = payload.rsplit("_", 1)
    await state.update_data(target_date=target_date)
    await state.set_state(SpecialDateForm.start_time)
    await cb.message.edit_text(
        texts.get_text("schedule_pick_start", lang).format(day=target_date),
        reply_markup=get_special_schedule_time_kb(target_date, "start", lang=lang),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("special_back_start_"))
async def special_back_to_start(cb: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(cb.from_user.id)
    target_date = cb.data[len("special_back_start_"):]
    await state.update_data(target_date=target_date)
    await state.set_state(SpecialDateForm.start_time)
    await cb.message.edit_text(
        texts.get_text("schedule_pick_start", lang).format(day=target_date),
        reply_markup=get_special_schedule_time_kb(target_date, "start", lang=lang),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("special_start_"))
async def process_special_start_time_choice(cb: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(cb.from_user.id)
    target_date, start_t = parse_special_callback_parts(cb.data, "special_start_")
    await state.update_data(target_date=target_date, start_time=start_t)
    await state.set_state(SpecialDateForm.end_time)
    await cb.message.edit_text(
        texts.get_text("schedule_pick_end", lang).format(day=target_date),
        reply_markup=get_special_schedule_time_kb(target_date, "end", start_t, lang),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("special_end_"))
async def process_special_end_time_choice(cb: CallbackQuery, state: FSMContext):
    user, stylist = await ensure_active_stylist_callback(cb)
    if not (user and stylist):
        await state.clear()
        return
    lang = await get_user_lang(cb.from_user.id)

    target_date, end_t = parse_special_callback_parts(cb.data, "special_end_")
    data = await state.get_data()
    start_t = data.get("start_time")

    if not start_t or target_date != data.get("target_date"):
        await state.clear()
        await cb.answer(texts.get_text("schedule_session_expired", lang), show_alert=True)
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
        build_special_date_detail_text(target_date, weekly_schedule, saved_special, lang),
        reply_markup=get_special_date_actions_kb(target_date, stylist.id, True, lang),
        parse_mode="HTML",
    )
    await cb.answer(
        texts.get_text("special_hours_saved", lang).format(
            date=target_date, start=start_t, end=end_t
        )
    )
