"""
Фоновые задачи: напоминания, «пора обновить образ», срок тарифа, сводка владельцу.

Общее правило для всех задач: сессия с базой не держится открытой, пока
идут запросы к Telegram (CLAUDE.md, 4.3). Сначала собираем, кому и что
отправить, закрываем сессию, отправляем, и отдельной короткой сессией
помечаем то, что действительно ушло. Флаг «отправлено» ставится только
после успешной отправки: иначе заблокировавший бота человек навсегда
числился бы напомненным, а временный сбой Telegram съедал бы напоминание.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

from aiogram import Bot
from sqlalchemy import select, update
from sqlalchemy.orm import joinedload

import database as db
import texts
import timeutils
from config import get_optional_env
from services import metrics

#: Как часто запускается check_reminders (bot.py). Окно часового напоминания
#: обязано быть не уже интервала, иначе часть визитов проскакивает между
#: запусками — ровно так и было при ежечасном запуске и окне в 30 минут.
REMINDER_INTERVAL_MIN = 15
DAY_WINDOW = (timedelta(hours=23), timedelta(hours=25))
HOUR_WINDOW = (timedelta(minutes=45), timedelta(minutes=75))

REMINDER_DAY = "day"
REMINDER_HOUR = "hour"


def reminder_due(time_left: timedelta, day_sent: bool, hour_sent: bool) -> str | None:
    """Какое напоминание пора отправить, если пора. Чистая функция — ради тестов."""
    if DAY_WINDOW[0] <= time_left <= DAY_WINDOW[1] and not day_sent:
        return REMINDER_DAY
    if HOUR_WINDOW[0] <= time_left <= HOUR_WINDOW[1] and not hour_sent:
        return REMINDER_HOUR
    return None


@dataclass
class _Outgoing:
    booking_id: int
    chat_id: int
    text: str
    kind: str
    parse_mode: str | None = None


def _reminder_text(booking: db.Booking, kind: str) -> _Outgoing:
    lang = booking.user.language_code or "ru"
    if kind == REMINDER_DAY:
        service = (
            booking.service.catalog_service.name
            if booking.service and booking.service.catalog_service
            else texts.get_text("booking_service_unknown", lang)
        )
        text = texts.get_text("reminder_day", lang).format(
            time=booking.starts_at.strftime("%H:%M"), service=service,
        )
        return _Outgoing(booking.id, booking.user.telegram_id, text, kind)

    # Часовое напоминание размечено <b>. Раньше оно уходило без parse_mode,
    # и клиент видел теги буквально, а имя мастера шло в разметку без escape.
    stylist = booking.stylist.name if booking.stylist else "Maestro"
    text = texts.get_text("reminder_hour", lang).format(stylist=escape(stylist))
    return _Outgoing(booking.id, booking.user.telegram_id, text, kind, parse_mode="HTML")


async def check_reminders(bot: Bot, now: datetime | None = None) -> int:
    """Напоминания за сутки и за час. Возвращает, сколько ушло."""
    now = now or timeutils.now()

    async with db.async_session() as session:
        # joinedload обязателен для каждой связи: без него обращение к
        # b.stylist.name бросает MissingGreenlet, и часовое напоминание
        # молча не отправлялось несколько месяцев (docs/AUDIT.md, A-5).
        bookings = (await session.execute(
            select(db.Booking).where(
                db.Booking.status == db.BOOKING_APPROVED,
                db.Booking.starts_at >= now,
                db.Booking.starts_at <= now + DAY_WINDOW[1] + timedelta(hours=1),
                # Офлайн-клиенту напоминать некуда: аккаунта в Telegram нет.
                db.Booking.user_id.is_not(None),
            ).options(
                joinedload(db.Booking.user),
                joinedload(db.Booking.stylist),
                joinedload(db.Booking.service).joinedload(db.Service.catalog_service),
            )
        )).scalars().all()

        outgoing = []
        for booking in bookings:
            kind = reminder_due(
                booking.starts_at - now, booking.reminder_day_sent, booking.reminder_hour_sent
            )
            if kind:
                outgoing.append(_reminder_text(booking, kind))

    sent = await _deliver(bot, outgoing, event="reminder")

    if sent:
        async with db.async_session() as session:
            for item in sent:
                flag = "reminder_day_sent" if item.kind == REMINDER_DAY else "reminder_hour_sent"
                await session.execute(
                    update(db.Booking).where(db.Booking.id == item.booking_id).values({flag: True})
                )
            await session.commit()

    logging.info("reminders.done due=%s sent=%s", len(outgoing), len(sent))
    return len(sent)


async def _deliver(bot: Bot, outgoing: list[_Outgoing], event: str) -> list[_Outgoing]:
    """Отправка по одному; неудача одного не мешает остальным."""
    sent = []
    for item in outgoing:
        try:
            await bot.send_message(
                item.chat_id, item.text, parse_mode=item.parse_mode,
                disable_web_page_preview=True,
            )
            sent.append(item)
        except Exception as e:
            # Не глушим: заблокированный бот — нормально, но видеть это нужно.
            logging.warning(
                "notify.%s_failed booking_id=%s kind=%s error=%s",
                event, item.booking_id, item.kind, e,
            )
    return sent


async def check_follow_ups(bot: Bot, now: datetime | None = None) -> int:
    """«Пора обновить образ» через 20 дней после визита. Возвращает, сколько ушло."""
    now = now or timeutils.now()
    target_day = (now - timedelta(days=20)).date()
    day_start, day_end = timeutils.day_bounds(target_day)
    # Имя бота берём у самого бота: захардкоженное молча ломается при переименовании.
    bot_username = (await bot.get_me()).username

    async with db.async_session() as session:
        bookings = (await session.execute(
            select(db.Booking).where(
                db.Booking.status == db.BOOKING_COMPLETED,
                db.Booking.starts_at >= day_start,
                db.Booking.starts_at < day_end,
                db.Booking.follow_up_sent.is_(False),
                db.Booking.user_id.is_not(None),
            ).options(joinedload(db.Booking.user), joinedload(db.Booking.stylist))
        )).scalars().all()

        outgoing = []
        for booking in bookings:
            # Уже записался снова — не напоминаем, чтобы не быть навязчивыми.
            again = await session.scalar(
                select(db.Booking.id).where(
                    db.Booking.user_id == booking.user_id,
                    db.Booking.starts_at > booking.starts_at,
                ).limit(1)
            )
            if again:
                continue

            lang = booking.user.language_code or "ru"
            link = f"https://t.me/{bot_username}?start=stylist_{booking.stylist_id}"
            text = texts.get_text("follow_up", lang).format(
                # Без имени было «Привет, None!».
                name=booking.user.first_name or texts.get_text("welcome_fallback_name", lang),
                stylist=booking.stylist.name if booking.stylist else "Maestro",
                link=link,
            )
            outgoing.append(_Outgoing(booking.id, booking.user.telegram_id, text, "follow_up"))

    sent = await _deliver(bot, outgoing, event="follow_up")
    if sent:
        async with db.async_session() as session:
            await session.execute(
                update(db.Booking)
                .where(db.Booking.id.in_([item.booking_id for item in sent]))
                .values(follow_up_sent=True)
            )
            await session.commit()
    logging.info("follow_ups.done due=%s sent=%s", len(outgoing), len(sent))
    return len(sent)


async def send_health_alerts(bot: Bot):
    """
    Сводка проблем владельцу сервиса.

    Метрики, на которые никто не смотрит, не отличаются от их отсутствия:
    заявка, которую мастер не разобрал третьи сутки, ничего не роняет —
    клиент просто не дождался ответа и ушёл.

    Пишем только когда есть что сказать. Ежедневное «всё хорошо» читать
    перестают через неделю, и вместе с ним перестают читать настоящие
    предупреждения.

    Без ALERT_CHAT_ID задача не делает ничего: адресата нет. Текст по-русски
    сознательно: его читает владелец, как и веб-панель.
    """
    chat_id = get_optional_env("ALERT_CHAT_ID")
    if not chat_id:
        return

    async with db.async_session() as session:
        snapshot = await metrics.collect(session)

    found = metrics.problems(snapshot)
    if not found:
        logging.info("alerts.nothing_to_report")
        return

    text = "<b>Maestro: требует внимания</b>\n\n" + "\n".join(f"• {item}" for item in found)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        logging.warning("alerts.sent problems=%s", len(found))
    except Exception as e:
        # Не глушим молча: если алерты не доходят, об этом надо узнать
        # из логов, а не по тишине.
        logging.warning("alerts.send_failed error=%s", e)


#: За сколько дней до конца тарифа предупреждаем мастера.
SUBSCRIPTION_WARN_DAYS = (7, 3, 1)


async def check_subscription_expiry(bot: Bot):
    logging.info("subscription.check_started")
    today = timeutils.today()

    async with db.async_session() as session:
        users = (await session.execute(
            select(db.User).where(
                db.User.role == "stylist",
                db.User.is_active.is_(True),
                db.User.subscription_until.isnot(None),
            )
        )).scalars().all()
        outgoing = [
            (user.id, user.telegram_id, user.language_code or "ru", (user.subscription_until - today).days)
            for user in users
            if (user.subscription_until - today).days in SUBSCRIPTION_WARN_DAYS
        ]

    for db_user_id, telegram_id, lang, days_left in outgoing:
        text = texts.get_text("subscription_expiring", lang).format(days=days_left)
        try:
            await bot.send_message(telegram_id, text, parse_mode="HTML")
        except Exception as e:
            logging.warning("notify.subscription_failed db_user_id=%s error=%s", db_user_id, e)
