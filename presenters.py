"""
Тексты сообщений.

Здесь всё, что возвращает строку для пользователя. Клавиатуры — в keyboards.py.

Каждая функция принимает язык: раньше половина экранов мастера была жёстко
русской, и узбекоязычный мастер видел смесь языков в своём рабочем интерфейсе.
Сами строки лежат в texts.py, здесь только сборка.

Пользовательские значения обязательно экранируются: имя вида "<b" ломает
отправку сообщения целиком, потому что почти всё отправляется с parse_mode=HTML
(docs/AUDIT.md, B-3).
"""
from html import escape

import database as db
import texts
import timeutils
from constants import DEFAULT_LANGUAGE, day_name
from services.access import get_subscription_days_left
from services.stats import change_percent


def format_break(schedule, lang: str = DEFAULT_LANGUAGE) -> str:
    """Перерыв в скобках — или пустая строка, если его нет."""
    if not schedule or not (
        getattr(schedule, "break_start", None) and getattr(schedule, "break_end", None)
    ):
        return ""
    label = texts.get_text("schedule_break_label", lang).format(
        start=schedule.break_start, end=schedule.break_end
    )
    return f" ({label})"


def format_buffer(buffer_min: int | None, lang: str = DEFAULT_LANGUAGE) -> str:
    """«15 мин» или «нет» — подпись буфера для кнопки и подтверждения."""
    if not buffer_min:
        return texts.get_text("buffer_off", lang)
    return texts.get_text("buffer_minutes", lang).format(minutes=buffer_min)


def format_schedule_range(schedule, lang: str = DEFAULT_LANGUAGE) -> str:
    """
    Часы дня без перерыва.

    Перерыв сюда не попадает намеренно: эта строка стоит и на кнопке дня,
    рядом с которой лежит «Выходной», и «10:00-18:00 (обед 13:00-14:00)»
    растянуло бы кнопку на две строки. Перерыв показывается в тексте обзора.
    """
    if not schedule:
        return texts.get_text("schedule_day_off_short", lang)
    return f"{schedule.start_time}-{schedule.end_time}"


def format_special_schedule_range(
    schedule: db.SpecialSchedule | None, lang: str = DEFAULT_LANGUAGE
) -> str:
    if not schedule:
        return texts.get_text("schedule_no_exception", lang)
    if schedule.is_day_off:
        return texts.get_text("schedule_day_off_short", lang)
    if schedule.start_time and schedule.end_time:
        return f"{schedule.start_time}-{schedule.end_time}"
    return texts.get_text("schedule_no_exception", lang)


def build_schedule_overview_text(
    stylist_name: str,
    schedule_map: dict[int, db.Schedule],
    special_dates: list[db.SpecialSchedule] | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> str:
    lines = [
        f"<b>{texts.get_text('schedule_title', lang).format(name=escape(stylist_name))}</b>",
        texts.get_text("schedule_subtitle", lang),
        "",
    ]
    for day in range(1, 8):
        schedule = schedule_map.get(day)
        lines.append(
            f"• {day_name(day, lang)}: <b>{format_schedule_range(schedule, lang)}</b>"
            f"{format_break(schedule, lang)}"
        )
    lines.append("")

    if special_dates:
        lines.append(f"<b>{texts.get_text('schedule_upcoming_special', lang)}</b>")
        for item in special_dates[:5]:
            date_text = item.work_date.strftime("%Y-%m-%d")
            lines.append(f"• {date_text}: <b>{format_special_schedule_range(item, lang)}</b>")
        lines.append("")

    lines.append(texts.get_text("schedule_hint", lang))
    return "\n".join(lines)


def build_special_dates_text(
    stylist_name: str,
    year: int,
    month: int,
    special_dates: list[db.SpecialSchedule],
    lang: str = DEFAULT_LANGUAGE,
) -> str:
    lines = [
        f"<b>{texts.get_text('special_title', lang).format(name=escape(stylist_name))}</b>",
        texts.get_text("special_month", lang).format(month=f"{year}-{month:02d}"),
        texts.get_text("special_subtitle", lang),
        texts.get_text("special_fallback_hint", lang),
        "",
    ]

    upcoming = [item for item in special_dates if item.work_date >= timeutils.today()]
    if upcoming:
        lines.append(f"<b>{texts.get_text('special_upcoming', lang)}</b>")
        for item in upcoming[:6]:
            date_text = item.work_date.strftime("%Y-%m-%d")
            lines.append(f"• {date_text}: <b>{format_special_schedule_range(item, lang)}</b>")
    else:
        lines.append(texts.get_text("special_empty", lang))

    return "\n".join(lines)


def build_special_date_detail_text(
    target_date: str,
    weekly_schedule: db.Schedule | None,
    special_schedule: db.SpecialSchedule | None,
    lang: str = DEFAULT_LANGUAGE,
) -> str:
    return (
        f"<b>{escape(target_date)}</b>\n"
        f"{texts.get_text('special_by_weekly', lang)}: "
        f"<b>{format_schedule_range(weekly_schedule, lang)}</b>\n"
        f"{texts.get_text('special_exception_for_date', lang)}: "
        f"<b>{format_special_schedule_range(special_schedule, lang)}</b>\n\n"
        f"{texts.get_text('special_choose_action', lang)}"
    )


def build_booking_card(
    booking: db.Booking, footer: str | None = None, lang: str = DEFAULT_LANGUAGE
) -> str:
    """
    Карточка заявки для мастера. Данные берём из базы, а не из текста сообщения:
    текст сообщения — ненадёжный источник, он ломается при любой смене шаблона.
    """
    service_name = (
        booking.service.catalog_service.name
        if booking.service and booking.service.catalog_service
        else texts.get_text("booking_service_unknown", lang)
    )
    if booking.user is None:
        # Запись, которую мастер завёл сам. Ни телефона, ни ссылки на Telegram
        # у такого клиента нет — показывать пустые строки вместо них незачем.
        client_name = booking.guest_name or texts.get_text("offline_guest_unnamed", lang)
        head = (
            f"{texts.get_text('booking_client', lang)}: {escape(client_name)}\n"
            f"{texts.get_text('offline_badge', lang)}\n"
        )
    else:
        client_name = booking.user.first_name or texts.get_text("booking_client", lang)
        phone = booking.user.phone_number or texts.get_text("booking_phone_unknown", lang)
        head = (
            f"{texts.get_text('booking_client', lang)}: {escape(client_name)}\n"
            f"{texts.get_text('booking_contact', lang)}: {escape(phone)}\n"
            f'<a href="tg://user?id={booking.user.telegram_id}">'
            f"{texts.get_text('booking_write_telegram', lang)}</a>\n"
        )

    card = (
        f"<b>{texts.get_text('booking_card_title', lang)}</b>\n\n"
        f"{head}"
        f"{texts.get_text('booking_service', lang)}: {escape(service_name)}\n"
        f"{texts.get_text('booking_datetime', lang)}: "
        f"{escape(timeutils.format_slot(booking.starts_at))}"
    )
    if footer:
        card += f"\n\n<b>{footer}</b>"
    return card


def format_price(value: float | int | None) -> str:
    """Цена с неразрывными пробелами по разрядам: «80 000 so'm»."""
    return f"{float(value or 0):,.0f}".replace(",", " ") + " so'm"


def build_stylist_button_label(card, lang: str = DEFAULT_LANGUAGE) -> str:
    """
    Подпись мастера в списке: имя и три факта, по которым выбирают.

    Всё на самой кнопке, а не в тексте сообщения над ней: иначе строку
    списка пришлось бы связывать с кнопкой номером, и человек каждый раз
    сверял бы «второй в тексте — вторая кнопка».
    """
    parts = [card.name]

    if card.rating:
        rating = f"⭐ {card.rating:.1f}"
        if card.reviews:
            rating += f" ({card.reviews})"
        parts.append(rating)
    else:
        parts.append(texts.get_text("search_no_rating", lang))

    if card.min_price is not None:
        parts.append(texts.get_text("search_price_from", lang).format(
            price=format_price(card.min_price)
        ))
    else:
        parts.append(texts.get_text("search_no_services", lang))
        return " · ".join(parts)

    if card.nearest:
        parts.append(timeutils.format_human(card.nearest, lang))
    else:
        parts.append(texts.get_text("search_no_slots", lang))

    return " · ".join(parts)


def build_reviews_text(
    stylist_name: str,
    reviews: list[db.Booking],
    total: int,
    lang: str = DEFAULT_LANGUAGE,
) -> str:
    """
    Список отзывов о мастере.

    Подписываем именем клиента, без фамилии и телефона: отзыв — публичный
    текст, и превращать его в способ найти человека не нужно.
    """
    lines = [f"<b>{texts.get_text('reviews_title', lang).format(name=escape(stylist_name))}</b>"]

    if not reviews:
        lines.append("")
        lines.append(texts.get_text("reviews_empty", lang))
        return "\n".join(lines)

    for booking in reviews:
        author = (
            booking.user.first_name
            if booking.user and booking.user.first_name
            else texts.get_text("reviews_anonymous", lang)
        )
        stars = "★" * (booking.rating or 0)
        lines.append("")
        lines.append(f"{stars} — <b>{escape(author)}</b>, {timeutils.format_slot(booking.starts_at)[:10]}")
        lines.append(escape(booking.review_text))

    if total > len(reviews):
        lines.append("")
        lines.append(texts.get_text("reviews_more", lang).format(
            count=total - len(reviews), shown=len(reviews)
        ))

    return "\n".join(lines)


def plural_days(count: int, lang: str) -> str:
    """
    Слово «день» в нужной форме.

    В узбекском числительное не меняет форму слова, в русском меняет —
    поэтому правило одно на язык, а не одно на всех.
    """
    if lang != "ru":
        return texts.get_text("day_plural_many", lang)
    if count % 10 == 1 and count % 100 != 11:
        return texts.get_text("day_plural_one", lang)
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return texts.get_text("day_plural_few", lang)
    return texts.get_text("day_plural_many", lang)


def get_subscription_menu_text(user: db.User | None, lang: str = DEFAULT_LANGUAGE) -> str:
    if not user or user.role != "stylist":
        return (
            f"<b>{texts.get_text('tariff_title', lang)}</b>\n"
            f"{texts.get_text('tariff_stylists_only', lang)}"
        )

    expiry_text = (
        user.subscription_until.strftime("%Y-%m-%d")
        if user.subscription_until
        else texts.get_text("tariff_unlimited", lang)
    )
    days_left = get_subscription_days_left(user)

    if user.subscription_until is None:
        status_line = texts.get_text("tariff_status_active", lang)
        detail_line = texts.get_text("tariff_detail_unlimited", lang)
    elif days_left is not None and days_left < 0:
        status_line = texts.get_text("tariff_status_expired", lang)
        detail_line = texts.get_text("tariff_detail_expired", lang)
    elif days_left == 0:
        status_line = texts.get_text("tariff_status_today", lang)
        detail_line = texts.get_text("tariff_detail_today", lang)
    else:
        status_line = texts.get_text("tariff_status_active", lang)
        detail_line = texts.get_text("tariff_detail_days_left", lang).format(
            days=days_left, word=plural_days(days_left, lang)
        )

    return (
        f"<b>{texts.get_text('tariff_period_title', lang)}</b>\n"
        f"{texts.get_text('tariff_expires_on', lang)}: <b>{expiry_text}</b>\n"
        f"{status_line}\n"
        f"{detail_line}\n\n"
        f"{texts.get_text('tariff_contact_admin', lang)}"
    )


def get_registration_text(key: str, lang: str) -> str:
    """Тексты регистрации. Живут в texts.py вместе с остальными."""
    return texts.get_text(key, lang)


#: Сколько услуг показывать прямо на карточке. Остальные — на экране записи.
CARD_SERVICES_SHOWN = 5


def build_card_services_block(services, lang: str) -> str:
    """
    Услуги с ценами на карточке мастера — дешёвые сверху.

    Раньше цены были только на следующем экране: чтобы узнать, по карману ли
    мастер, приходилось начинать запись. Возвращает пустую строку, если услуг
    нет — пустой заголовок «Услуги:» хуже, чем ничего.
    """
    if not services:
        return ""
    ordered = sorted(services, key=lambda s: (s.price or 0))
    minutes = texts.get_text("services_minutes_short", lang)
    lines = [f"<b>{texts.get_text('card_services_title', lang)}:</b>"]
    for service in ordered[:CARD_SERVICES_SHOWN]:
        name = service.catalog_service.name if service.catalog_service else "—"
        lines.append(
            f"• {escape(name)} — {format_money(service.price or 0)} so'm · "
            f"{service.duration_min} {minutes}"
        )
    hidden = len(ordered) - CARD_SERVICES_SHOWN
    if hidden > 0:
        lines.append(texts.get_text("card_services_more", lang).format(count=hidden))
    return "\n".join(lines)


def format_money(amount: int) -> str:
    """800000 → «800 000»: так пишут суммы в Узбекистане и в России."""
    return f"{amount:,.0f}".replace(",", " ")


def _change_suffix(current: int, previous: int, lang: str) -> str:
    if not current and not previous:
        return ""
    percent = change_percent(current, previous)
    if percent is None:
        # В прошлом периоде был ноль: процент роста ничего не скажет.
        return ""
    if percent == 0:
        return texts.get_text("stats_change_same", lang)
    return texts.get_text("stats_change", lang).format(
        arrow="↑" if percent > 0 else "↓", percent=abs(percent),
    )


def build_stats_report(report, period_label: str, lang: str) -> str:
    """
    Отчёт мастеру. report — services.stats.StatsReport.

    Строки без данных опускаются: «отменено 0 · отклонено 0» и «пиковые
    часы:» с пустотой — шум, за которым теряется то, что важно.
    """
    now, before = report.current, report.previous
    t = lambda key: texts.get_text(key, lang)  # noqa: E731
    lines = [f"<b>{t('stats_report_title').format(period=period_label)}</b>", ""]

    if not now.total and not now.lost:
        lines.append(t("stats_empty"))
        return "\n".join(lines)

    lines.append(t("stats_line_total").format(
        count=now.total, change=_change_suffix(now.total, before.total, lang),
    ))
    lines.append(t("stats_line_statuses").format(
        completed=now.completed, approved=now.approved, pending=now.pending,
    ))
    if now.lost:
        lines.append(t("stats_line_lost").format(cancelled=now.cancelled, declined=now.declined))

    lines.append("")
    lines.append(t("stats_line_earned").format(
        amount=format_money(now.earned), change=_change_suffix(now.earned, before.earned, lang),
    ))
    if now.expected:
        lines.append(t("stats_line_expected").format(amount=format_money(now.expected)))

    if now.clients or now.guests:
        lines.append("")
    if now.clients:
        lines.append(t("stats_line_clients").format(
            clients=now.clients, returning=now.returning_clients,
        ))
    if now.guests:
        lines.append(t("stats_line_guests").format(count=now.guests))
    if now.peak_hours:
        hours = ", ".join(f"{hour:02d}:00 ({count})" for hour, count in now.peak_hours)
        lines.append(t("stats_line_peak").format(hours=hours))

    return "\n".join(lines)
