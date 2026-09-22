import logging
from datetime import datetime, timedelta
from html import escape

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from starlette.middleware.sessions import SessionMiddleware
from wtforms.fields import SelectField

import database as db
import logutil
import observability
import security
import timeutils
from config import check_environment, load_admin_settings, load_sentry_settings
from services import audit, metrics
from services.reviews import load_reviews_for_moderation

# Как и в loader.py: сначала собираем все претензии к окружению, потом падаем
# одним понятным списком. Токен бота админке не нужен — её можно поднять отдельно.
logutil.setup_logging()
check_environment(groups=("admin", "database"))
ADMIN_SETTINGS = load_admin_settings()

# Та же Sentry, что у бота, но с тегом component=admin: обе половины шлют
# в один проект, и без тега непонятно, где именно сломалось.
_sentry = load_sentry_settings()
observability.init_sentry(_sentry.dsn, _sentry.environment, component="admin")

login_throttle = security.LoginThrottle()

if not security.looks_like_hash(ADMIN_SETTINGS.password):
    logging.warning(
        "admin.plaintext_password ADMIN_PASSWORD хранится открытым текстом. "
        "Сгенерируйте хеш: python scripts/hash_password.py"
    )


def _client_key(request: Request) -> str:
    """Ключ для счётчика попыток. За прокси реальный адрес приходит в заголовке."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class MyBackend(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))
        client = _client_key(request)

        locked_for = login_throttle.is_locked(client)
        if locked_for:
            logging.warning("admin.login_blocked client=%s seconds_left=%s", client, locked_for)
            return False

        # Сравнение обеих учётных записей целиком и константно по времени
        # живёт в security.authenticate_admin — там же объяснено, почему
        # ранний выход по неверному логину недопустим.
        role = security.authenticate_admin(username, password, ADMIN_SETTINGS)

        if role:
            login_throttle.reset(client)
            # Роль и логин кладём в сессию: по роли решается доступ, а логином
            # подписывается журнал действий. Без логина действие помощника
            # записалось бы на владельца.
            request.session.update({
                "token": ADMIN_SETTINGS.secret_key,
                "role": role,
                "username": username,
            })
            logging.info(
                "admin.login_success client=%s user=%s role=%s", client, username, role
            )
            return True

        left = login_throttle.register_failure(client)
        logging.warning(
            "admin.login_failed client=%s user=%s attempts_left=%s", client, username, left
        )
        return False

    async def logout(self, request: Request) -> bool:
        logging.info("admin.logout client=%s", _client_key(request))
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return current_role(request) is not None


#: Части пути sqladmin, означающие изменение данных. Отличать чтение от записи
#: приходится по пути: sqladmin зовёт is_accessible() одинаково на всех
#: эндпоинтах, а can_edit и соседние — атрибуты класса, до запроса им не
#: добраться.
WRITE_PATH_MARKERS = ("/create", "/edit", "/delete")


def current_role(request: Request) -> str | None:
    """
    Роль вошедшего или None.

    Сессия без роли считается недействительной. Такие остались у тех, кто
    вошёл до появления ролей: пусть перелогинятся. Считать их владельцами
    было бы удобнее и неправильно — права не выдают по умолчанию.
    """
    token = request.session.get("token")
    # Через constant_time_equals: ADMIN_SECRET_KEY задаёт человек,
    # и не-ASCII в нём уронил бы проверку сессии, а не отклонил её.
    if not token or not security.constant_time_equals(str(token), ADMIN_SETTINGS.secret_key):
        return None
    role = request.session.get("role")
    return role if role in (security.ROLE_OWNER, security.ROLE_MANAGER) else None


def current_username(request: Request) -> str:
    """Логин вошедшего — для подписи в журнале действий."""
    return str(request.session.get("username") or "?")


def is_write_request(request: Request) -> bool:
    return any(marker in request.url.path for marker in WRITE_PATH_MARKERS)


authentication_backend = MyBackend(secret_key=ADMIN_SETTINGS.secret_key)

app = FastAPI(title="Maestro Admin")
app.add_middleware(SessionMiddleware, secret_key=ADMIN_SETTINGS.secret_key, same_site="lax")
admin = Admin(app, db.engine, authentication_backend=authentication_backend, title="Maestro Admin")


@app.on_event("startup")
async def startup_create_tables():
    await db.run_migrations()


def _is_admin_authenticated(request: Request) -> bool:
    """Вошёл ли вообще кто-нибудь. Роль проверяется отдельно, где она важна."""
    return current_role(request) is not None


def _format_money(value: float | int | None) -> str:
    return f"{float(value or 0):,.0f}".replace(",", " ") + " so'm"


def _booking_date_range(days: int) -> tuple[datetime, datetime]:
    """Полуинтервал [сегодня, сегодня + days) как моменты времени."""
    start = timeutils.today()
    return timeutils.range_bounds(start, start + timedelta(days=days - 1))


async def _collect_dashboard_data() -> dict:
    today_start, today_end = timeutils.day_bounds(timeutils.today())
    week_start, week_end = _booking_date_range(7)
    month_start, month_end = _booking_date_range(30)

    async with db.async_session() as session:
        users_count = await session.scalar(select(func.count(db.User.id))) or 0
        stylists_count = await session.scalar(select(func.count(db.Stylist.id))) or 0
        active_stylists_count = await session.scalar(
            select(func.count(db.User.id)).where(db.User.role == "stylist", db.User.is_active.is_(True))
        ) or 0
        barbershops_count = await session.scalar(select(func.count(db.Barbershop.id))) or 0
        services_count = await session.scalar(select(func.count(db.Service.id))) or 0
        avg_rating = await session.scalar(select(func.coalesce(func.avg(db.Stylist.avg_rating), 0))) or 0

        status_rows = (
            await session.execute(select(db.Booking.status, func.count(db.Booking.id)).group_by(db.Booking.status))
        ).all()
        status_counts = {status or "unknown": count for status, count in status_rows}

        bookings_today = await session.scalar(
            select(func.count(db.Booking.id)).where(
                db.Booking.starts_at >= today_start, db.Booking.starts_at < today_end
            )
        ) or 0
        bookings_week = await session.scalar(
            select(func.count(db.Booking.id)).where(
                db.Booking.starts_at >= week_start, db.Booking.starts_at < week_end
            )
        ) or 0
        bookings_month = await session.scalar(
            select(func.count(db.Booking.id)).where(
                db.Booking.starts_at >= month_start, db.Booking.starts_at < month_end
            )
        ) or 0
        revenue_month = await session.scalar(
            # Цена из записи: повышение цены не должно переписывать прошлый месяц.
            select(func.coalesce(func.sum(func.coalesce(db.Booking.price, db.Service.price)), 0))
            .select_from(db.Booking)
            .join(db.Service, db.Service.id == db.Booking.service_id, isouter=True)
            .where(
                db.Booking.status.in_((db.BOOKING_APPROVED, db.BOOKING_COMPLETED)),
                db.Booking.starts_at >= month_start,
                db.Booking.starts_at < month_end,
            )
        ) or 0

        booking_options = (
            joinedload(db.Booking.user),
            joinedload(db.Booking.stylist),
            joinedload(db.Booking.service).joinedload(db.Service.catalog_service),
        )
        upcoming_bookings = (
            await session.execute(
                select(db.Booking)
                .where(db.Booking.starts_at >= today_start, db.Booking.status.in_(db.ACTIVE_BOOKING_STATUSES))
                .options(*booking_options)
                .order_by(db.Booking.starts_at.asc())
                .limit(8)
            )
        ).scalars().all()
        pending_bookings = (
            await session.execute(
                select(db.Booking)
                .where(db.Booking.status == db.BOOKING_PENDING)
                .options(*booking_options)
                .order_by(db.Booking.starts_at.asc())
                .limit(8)
            )
        ).scalars().all()
        top_stylists = (
            await session.execute(
                select(db.Stylist)
                .options(joinedload(db.Stylist.barbershop))
                .order_by(db.Stylist.avg_rating.desc(), db.Stylist.name.asc())
                .limit(5)
            )
        ).scalars().all()

    return {
        "users_count": users_count,
        "stylists_count": stylists_count,
        "active_stylists_count": active_stylists_count,
        "barbershops_count": barbershops_count,
        "services_count": services_count,
        "avg_rating": avg_rating,
        "status_counts": status_counts,
        "bookings_today": bookings_today,
        "bookings_week": bookings_week,
        "bookings_month": bookings_month,
        "revenue_month": revenue_month,
        "upcoming_bookings": upcoming_bookings,
        "pending_bookings": pending_bookings,
        "top_stylists": top_stylists,
    }


def _booking_rows(bookings: list[db.Booking]) -> str:
    if not bookings:
        return '<tr><td colspan="5" class="empty">Нет записей</td></tr>'
    rows = []
    for booking in bookings:
        client = escape(booking.user.first_name if booking.user else "-")
        stylist = escape(booking.stylist.name if booking.stylist else "-")
        service = escape(
            booking.service.catalog_service.name
            if booking.service and booking.service.catalog_service
            else "-"
        )
        status = escape(booking.status or "unknown")
        rows.append(
            "<tr>"
            f"<td>{escape(timeutils.format_slot(booking.starts_at))}</td>"
            f"<td>{client}</td>"
            f"<td>{stylist}</td>"
            f"<td>{service}</td>"
            f"<td><span class='status status-{status}'>{status}</span></td>"
            "</tr>"
        )
    return "".join(rows)


def _stylist_rows(stylists: list[db.Stylist]) -> str:
    if not stylists:
        return '<tr><td colspan="4" class="empty">Нет мастеров</td></tr>'
    rows = []
    for stylist in stylists:
        rows.append(
            "<tr>"
            f"<td>{escape(stylist.name)}</td>"
            f"<td>{escape(stylist.barbershop.name if stylist.barbershop else '-')}</td>"
            f"<td>{float(stylist.avg_rating or 0):.1f}</td>"
            f"<td>{stylist.id}</td>"
            "</tr>"
        )
    return "".join(rows)


#: Подписи действий. Журнал читает человек, а не грепает машина:
#: «booking.approved» в таблице заставляет держать словарь в голове.
AUDIT_LABELS = {
    audit.BOOKING_CREATED: "Запись создана клиентом",
    audit.BOOKING_CREATED_OFFLINE: "Запись офлайн-клиента",
    audit.BOOKING_APPROVED: "Подтверждена мастером",
    audit.BOOKING_DECLINED: "Отклонена мастером",
    audit.BOOKING_COMPLETED: "Визит завершён",
    audit.BOOKING_CANCELLED: "Отменена клиентом",
    audit.BOOKING_RESCHEDULED: "Перенесена клиентом",
    audit.REVIEW_HIDDEN: "Отзыв скрыт",
    audit.REVIEW_RESTORED: "Отзыв возвращён",
}

ACTOR_LABELS = {
    db.ACTOR_CLIENT: "клиент",
    db.ACTOR_STYLIST: "мастер",
    db.ACTOR_ADMIN: "админ",
    db.ACTOR_SYSTEM: "система",
}


def _audit_actor(entry: db.AuditLog) -> str:
    """
    Кто совершил действие, в читаемом виде.

    Имя берём у связанного пользователя, а для админки и фоновых задач —
    из actor_label: строки в users у них нет.
    """
    kind = ACTOR_LABELS.get(entry.actor_kind, entry.actor_kind)
    if entry.actor and entry.actor.first_name:
        return f"{entry.actor.first_name} ({kind})"
    if entry.actor_label:
        return f"{entry.actor_label} ({kind})"
    return kind


def _render_audit(rows: list[dict]) -> str:
    """
    Журнал действий над записями.

    Только чтение: строки журнала не редактируются и не удаляются ни здесь,
    ни где-либо ещё в коде. Журнал, который можно поправить, не доказывает
    ничего.
    """
    if rows:
        body = "".join(
            f"""
        <tr>
          <td class="muted">{escape(row['when'])}</td>
          <td><b>{escape(row['action'])}</b></td>
          <td>{escape(row['actor'])}</td>
          <td>{escape(str(row['booking_id'])) if row['booking_id'] else '—'}</td>
          <td class="muted">{escape(row['details'])}</td>
        </tr>"""
            for row in rows
        )
        table = f"""
    <table>
      <thead>
        <tr><th>Когда</th><th>Что</th><th>Кто</th><th>Запись</th><th>Подробности</th></tr>
      </thead>
      <tbody>{body}</tbody>
    </table>"""
    else:
        table = "<div class='empty'>Журнал пуст — действий над записями ещё не было.</div>"

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Maestro — журнал действий</title>
  <style>
    :root {{ --panel:#fff; --line:#e2e8f0; --muted:#64748b; --brand:#2563eb; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:system-ui,-apple-system,"Segoe UI",sans-serif; background:#f8fafc; color:#0f172a; }}
    header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding:18px 24px; background:var(--panel); border-bottom:1px solid var(--line); flex-wrap:wrap; }}
    h1 {{ margin:0; font-size:20px; }}
    a.button {{ display:inline-block; padding:8px 14px; border-radius:6px; background:var(--brand); color:#fff; text-decoration:none; font-size:14px; }}
    main {{ max-width:1100px; margin:0 auto; padding:24px; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    th, td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
    .muted {{ color:var(--muted); }}
    .empty {{ color:var(--muted); text-align:center; padding:28px; background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
    @media (max-width: 720px) {{ th:nth-child(5), td:nth-child(5) {{ display:none; }} }}
  </style>
</head>
<body>
  <header>
    <div><h1>Журнал действий</h1><div class="muted">Последние {len(rows)} записей. Только чтение: журнал не редактируется.</div></div>
    <div><a class="button" href="/reviews">Отзывы</a> <a class="button" href="/dashboard">К дашборду</a></div>
  </header>
  <main>{table}</main>
</body>
</html>"""


def _review_form(row: dict, can_moderate: bool) -> str:
    """
    Кнопка скрытия — только тому, кто вправе ею пользоваться.

    Показать помощнику кнопку, которая ответит отказом, хуже, чем не показать
    её вовсе: он решит, что панель сломана, а не что у него нет прав.
    """
    if not can_moderate:
        return ""
    label = "Показать" if row["hidden"] else "Скрыть"
    return (
        f'<form method="post" action="/reviews/{row["id"]}/toggle">'
        f'<button type="submit">{label}</button></form>'
    )


def _render_reviews(rows: list[dict], can_moderate: bool = True) -> str:
    """
    Страница модерации отзывов.

    Текст экранируется: отзыв пишет клиент, и это ровно тот случай, когда
    чужая строка попадает в HTML. Переносы восстанавливаем уже после
    экранирования — иначе <br> съест сам escape.
    """
    hint = (
        "Отзыв виден клиентам сразу — скрытие убирает его из карточки мастера."
        if can_moderate
        else "Только просмотр: скрывать отзывы может владелец."
    )
    if rows:
        cards = "".join(
            f"""
      <article class="review {'hidden' if row['hidden'] else ''}">
        <div class="review-head">
          <b>{'★' * row['rating']}</b>
          <span>{escape(row['author'])} → {escape(row['stylist'])}</span>
          <span class="muted">{escape(row['when'])}</span>
          {'<span class="status status-declined">скрыт</span>' if row['hidden'] else ''}
        </div>
        <p>{escape(row['text']).replace(chr(10), '<br>')}</p>
        {_review_form(row, can_moderate)}
      </article>"""
            for row in rows
        )
    else:
        cards = "<div class='empty'>Отзывов пока нет.</div>"

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Maestro — модерация отзывов</title>
  <style>
    :root {{ --panel:#fff; --line:#e2e8f0; --muted:#64748b; --brand:#2563eb; --bad:#dc2626; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:system-ui,-apple-system,"Segoe UI",sans-serif; background:#f8fafc; color:#0f172a; }}
    header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding:18px 24px; background:var(--panel); border-bottom:1px solid var(--line); flex-wrap:wrap; }}
    h1 {{ margin:0; font-size:20px; }}
    a.button {{ display:inline-block; padding:8px 14px; border-radius:6px; background:var(--brand); color:#fff; text-decoration:none; font-size:14px; }}
    main {{ max-width:860px; margin:0 auto; padding:24px; display:grid; gap:14px; }}
    .review {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .review.hidden {{ opacity:.55; }}
    .review-head {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; font-size:14px; margin-bottom:8px; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    .review p {{ margin:0 0 12px; white-space:normal; line-height:1.5; }}
    .status {{ display:inline-block; padding:3px 8px; border-radius:999px; font-size:12px; font-weight:700; }}
    .status-declined {{ color:var(--bad); background:#fee2e2; }}
    button {{ padding:7px 14px; border:1px solid var(--line); border-radius:6px; background:#f1f5f9; cursor:pointer; font-size:14px; }}
    button:hover {{ background:#e2e8f0; }}
    .empty {{ color:var(--muted); text-align:center; padding:28px; background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
  </style>
</head>
<body>
  <header>
    <div><h1>Модерация отзывов</h1><div class="muted">{hint}</div></div>
    <a class="button" href="/dashboard">К дашборду</a>
  </header>
  <main>{cards}</main>
</body>
</html>"""


def _render_dashboard(data: dict) -> str:
    statuses = {
        "pending": data["status_counts"].get("pending", 0),
        "approved": data["status_counts"].get("approved", 0),
        "completed": data["status_counts"].get("completed", 0),
        "declined": data["status_counts"].get("declined", 0),
    }
    max_status = max(max(statuses.values()), 1)
    status_bars = "".join(
        f"<div class='bar-row'><span>{label}</span><div class='bar'><i style='width:{count / max_status * 100:.0f}%'></i></div><b>{count}</b></div>"
        for label, count in [
            ("Новые", statuses["pending"]),
            ("Подтвержденные", statuses["approved"]),
            ("Завершенные", statuses["completed"]),
            ("Отклоненные", statuses["declined"]),
        ]
    )

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Maestro Dashboard</title>
  <style>
    :root {{ --bg:#f5f7fb; --panel:#fff; --text:#172033; --muted:#64748b; --line:#e2e8f0; --brand:#2563eb; --ok:#16a34a; --warn:#d97706; --bad:#dc2626; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter,Segoe UI,Arial,sans-serif; background:var(--bg); color:var(--text); }}
    header {{ padding:24px clamp(16px,4vw,44px); background:var(--panel); border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
    h1 {{ margin:0; font-size:28px; }} h2 {{ margin:0 0 14px; font-size:18px; }}
    a.button {{ color:white; background:var(--brand); padding:10px 14px; border-radius:8px; text-decoration:none; font-weight:600; }}
    main {{ padding:24px clamp(16px,4vw,44px); display:grid; gap:22px; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }}
    .card, section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; box-shadow:0 10px 30px rgba(15,23,42,.05); }}
    .card span {{ color:var(--muted); font-size:13px; }} .card strong {{ display:block; margin-top:8px; font-size:26px; }}
    .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:22px; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }} th, td {{ padding:10px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }} .empty {{ color:var(--muted); text-align:center; padding:22px; }}
    .status {{ display:inline-block; padding:4px 8px; border-radius:999px; background:#e2e8f0; font-size:12px; font-weight:700; }}
    .status-pending {{ color:var(--warn); background:#fef3c7; }} .status-approved {{ color:var(--brand); background:#dbeafe; }}
    .status-completed {{ color:var(--ok); background:#dcfce7; }} .status-declined {{ color:var(--bad); background:#fee2e2; }}
    .bar-row {{ display:grid; grid-template-columns:130px 1fr 44px; align-items:center; gap:12px; margin:12px 0; }}
    .bar {{ height:12px; background:#e2e8f0; border-radius:999px; overflow:hidden; }} .bar i {{ display:block; height:100%; background:var(--brand); border-radius:999px; }}
    @media (max-width: 960px) {{ .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .two-col {{ grid-template-columns:1fr; }} }}
    @media (max-width: 560px) {{ .grid {{ grid-template-columns:1fr; }} table {{ font-size:13px; }} th:nth-child(4), td:nth-child(4) {{ display:none; }} }}
  </style>
</head>
<body>
  <header><div><h1>Maestro Dashboard</h1><div>Обновлено: {timeutils.now().strftime("%Y-%m-%d %H:%M")}</div></div><div><a class="button" href="/audit">Журнал</a> <a class="button" href="/reviews">Отзывы</a> <a class="button" href="/admin">Открыть CRUD-админку</a></div></header>
  <main>
    <div class="grid">
      <div class="card"><span>Пользователи</span><strong>{data["users_count"]}</strong></div>
      <div class="card"><span>Мастера / активные</span><strong>{data["stylists_count"]} / {data["active_stylists_count"]}</strong></div>
      <div class="card"><span>Салоны</span><strong>{data["barbershops_count"]}</strong></div>
      <div class="card"><span>Услуги</span><strong>{data["services_count"]}</strong></div>
      <div class="card"><span>Записи сегодня</span><strong>{data["bookings_today"]}</strong></div>
      <div class="card"><span>Записи 7 дней</span><strong>{data["bookings_week"]}</strong></div>
      <div class="card"><span>Выручка 30 дней</span><strong>{_format_money(data["revenue_month"])}</strong></div>
      <div class="card"><span>Средний рейтинг</span><strong>{float(data["avg_rating"]):.1f}</strong></div>
    </div>
    <div class="two-col"><section><h2>Статусы записей</h2>{status_bars}</section><section><h2>Топ мастеров</h2><table><thead><tr><th>Мастер</th><th>Салон</th><th>Рейтинг</th><th>ID</th></tr></thead><tbody>{_stylist_rows(data["top_stylists"])}</tbody></table></section></div>
    <section><h2>Ближайшие записи</h2><table><thead><tr><th>Дата</th><th>Клиент</th><th>Мастер</th><th>Услуга</th><th>Статус</th></tr></thead><tbody>{_booking_rows(data["upcoming_bookings"])}</tbody></table></section>
    <section><h2>Новые заявки</h2><table><thead><tr><th>Дата</th><th>Клиент</th><th>Мастер</th><th>Услуга</th><th>Статус</th></tr></thead><tbody>{_booking_rows(data["pending_bookings"])}</tbody></table></section>
  </main>
</body>
</html>"""


def _render_status_page(db_status: str, db_error: str | None = None) -> str:
    is_ok = db_status == "ok"
    status_label = "База данных подключена" if is_ok else "База данных недоступна"
    status_class = "ok" if is_ok else "bad"
    error_block = f"<pre>{escape(db_error or '')}</pre>" if db_error else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Maestro Status</title>
  <style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; font-family:Segoe UI,Arial,sans-serif; background:#f5f7fb; color:#172033; }}
    main {{ width:min(760px, calc(100vw - 32px)); background:white; border:1px solid #e2e8f0; border-radius:10px; padding:28px; box-shadow:0 16px 50px rgba(15,23,42,.08); }}
    h1 {{ margin:0 0 10px; }} p {{ color:#64748b; line-height:1.5; }}
    .badge {{ display:inline-block; padding:8px 12px; border-radius:999px; font-weight:700; margin:12px 0; }}
    .ok {{ color:#166534; background:#dcfce7; }} .bad {{ color:#991b1b; background:#fee2e2; }}
    .actions {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:22px; }}
    a {{ color:white; background:#2563eb; padding:10px 14px; border-radius:8px; text-decoration:none; font-weight:600; }}
    a.secondary {{ color:#172033; background:#e2e8f0; }}
    pre {{ white-space:pre-wrap; background:#0f172a; color:#e2e8f0; padding:14px; border-radius:8px; overflow:auto; }}
  </style>
</head>
<body>
  <main>
    <h1>Maestro готов к запуску</h1>
    <p>Локальная панель администратора работает на <b>127.0.0.1:8002</b>. Для полноценной работы бота и dashboard нужна доступная MySQL-база из файла <code>.env</code>.</p>
    <div class="badge {status_class}">{status_label}</div>
    {error_block}
    <div class="actions">
      <a href="/admin/login">Войти в админку</a>
      <a class="secondary" href="/health">Health check</a>
    </div>
  </main>
</body>
</html>"""


def _render_dashboard_error(error: Exception) -> str:
    return _render_status_page("error", f"{type(error).__name__}: {error}")


async def _check_database() -> tuple[str, str | None]:
    try:
        async with db.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok", None
    except Exception as exc:
        return "error", f"{type(exc).__name__}: {exc}"


class RoleAwareView(ModelView):
    """
    Представление, знающее про роли.

    Смотреть может любой вошедший. Менять — только тот, чья роль указана
    в `writable_by`. По умолчанию это один владелец: право на запись
    выдаётся явно, а не отбирается.

    Зачем так, а не через can_edit: sqladmin проверяет can_edit как атрибут
    класса, у которого нет доступа к запросу, и на все эндпоинты зовёт один
    и тот же is_accessible(). Поэтому чтение от записи отличаем по пути.
    """

    writable_by: tuple[str, ...] = (security.ROLE_OWNER,)

    def is_accessible(self, request: Request) -> bool:
        role = current_role(request)
        if role is None:
            return False
        if is_write_request(request):
            return role in self.writable_by
        return True


class CatalogServiceAdmin(RoleAwareView, model=db.CatalogService):
    name = "Услуга каталога"
    name_plural = "Каталог услуг"
    icon = "fa-solid fa-book"

    column_list = [db.CatalogService.id, db.CatalogService.name]
    column_searchable_list = [db.CatalogService.name]
    column_sortable_list = [db.CatalogService.id, db.CatalogService.name]


class BarbershopAdmin(RoleAwareView, model=db.Barbershop):
    name = "Барбершоп"
    name_plural = "Барбершопы"
    icon = "fa-solid fa-shop"

    column_list = [
        db.Barbershop.id,
        db.Barbershop.name,
        db.Barbershop.district,
        db.Barbershop.address,
        db.Barbershop.latitude,
        db.Barbershop.longitude,
    ]
    column_searchable_list = [
        db.Barbershop.name,
        db.Barbershop.district,
        db.Barbershop.address,
    ]
    column_sortable_list = [db.Barbershop.id, db.Barbershop.name, db.Barbershop.district]


class UserAdmin(RoleAwareView, model=db.User):
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-user"

    column_list = [
        db.User.id,
        db.User.first_name,
        db.User.phone_number,
        db.User.role,
        db.User.is_active,
        db.User.subscription_until,
    ]
    column_details_list = [
        db.User.id,
        db.User.telegram_id,
        db.User.first_name,
        db.User.phone_number,
        db.User.language_code,
        db.User.role,
        db.User.is_active,
        db.User.subscription_until,
    ]
    column_editable_list = [db.User.role, db.User.is_active, db.User.subscription_until]
    column_searchable_list = [db.User.first_name, db.User.phone_number, db.User.telegram_id]
    column_sortable_list = [db.User.id, db.User.first_name, db.User.role, db.User.subscription_until]
    column_labels = {
        db.User.telegram_id: "Telegram ID",
        db.User.first_name: "Имя",
        db.User.phone_number: "Телефон",
        db.User.language_code: "Язык",
        db.User.role: "Роль",
        db.User.is_active: "Активен",
        db.User.subscription_until: "Подписка до",
    }

    form_overrides = {"role": SelectField}
    form_args = {
        "role": {
            "choices": [
                ("client", "client"),
                ("stylist", "stylist"),
                ("owner", "owner"),
            ]
        }
    }

    async def after_model_change(self, data: dict, model: db.User, is_created: bool, request: Request) -> None:
        async with db.async_session() as session:
            user = await session.get(db.User, model.id)
            if not user or user.role != "stylist":
                return

            existing_stylist = await session.scalar(
                select(db.Stylist).where(db.Stylist.user_id == user.id)
            )
            if existing_stylist:
                if not existing_stylist.name:
                    existing_stylist.name = user.first_name or f"Stylist {user.id}"
                    await session.commit()
                return

            default_barbershop = await session.scalar(
                select(db.Barbershop).order_by(db.Barbershop.id)
            )
            if not default_barbershop:
                return

            session.add(
                db.Stylist(
                    name=user.first_name or f"Stylist {user.id}",
                    user_id=user.id,
                    barbershop_id=default_barbershop.id,
                )
            )
            await session.commit()


class StylistAdmin(RoleAwareView, model=db.Stylist):
    name = "Мастер"
    name_plural = "Мастера"
    icon = "fa-solid fa-scissors"

    column_list = [
        db.Stylist.id,
        db.Stylist.name,
        "user_account.first_name",
        "barbershop.name",
        db.Stylist.avg_rating,
    ]
    column_details_list = [
        db.Stylist.id,
        db.Stylist.name,
        "user_account.telegram_id",
        "user_account.first_name",
        "barbershop.name",
        db.Stylist.avg_rating,
    ]
    column_labels = {
        "user_account.first_name": "Аккаунт Telegram",
        "user_account.telegram_id": "Telegram ID",
        "barbershop.name": "Барбершоп",
        db.Stylist.avg_rating: "Рейтинг",
    }
    column_searchable_list = [db.Stylist.name]
    column_sortable_list = [db.Stylist.id, db.Stylist.name, db.Stylist.avg_rating]


class ServiceAdmin(RoleAwareView, model=db.Service):
    name = "Услуга мастера"
    name_plural = "Услуги мастеров"
    icon = "fa-solid fa-tag"

    column_list = [
        db.Service.id,
        "catalog_service.name",
        "stylist.name",
        db.Service.price,
        db.Service.duration_min,
    ]
    column_labels = {
        "catalog_service.name": "Услуга",
        "stylist.name": "Мастер",
        db.Service.duration_min: "Длительность, мин",
        db.Service.price: "Цена",
    }
    column_sortable_list = [db.Service.id, db.Service.price, db.Service.duration_min]


class ScheduleAdmin(RoleAwareView, model=db.Schedule):
    name = "График"
    name_plural = "Графики мастеров"
    icon = "fa-solid fa-calendar-days"

    column_list = [
        db.Schedule.id,
        "stylist.name",
        db.Schedule.day_of_week,
        db.Schedule.start_time,
        db.Schedule.end_time,
    ]
    column_labels = {
        "stylist.name": "Мастер",
        db.Schedule.day_of_week: "День недели",
        db.Schedule.start_time: "Начало",
        db.Schedule.end_time: "Конец",
    }
    column_sortable_list = [db.Schedule.id, db.Schedule.day_of_week, db.Schedule.start_time]


class BookingAdmin(RoleAwareView, model=db.Booking):
    # Разбор заявок — и есть работа помощника. Всё остальное
    # (тарифы, учётные записи, справочники) ему только на чтение.
    writable_by = (security.ROLE_OWNER, security.ROLE_MANAGER)

    name = "Запись"
    name_plural = "Записи"
    icon = "fa-solid fa-calendar-check"

    column_list = [
        db.Booking.id,
        "user.first_name",
        "stylist.name",
        "service.catalog_service.name",
        db.Booking.starts_at,
        db.Booking.status,
        db.Booking.rating,
        db.Booking.review_hidden,
    ]
    column_labels = {
        "user.first_name": "Клиент",
        "stylist.name": "Мастер",
        "service.catalog_service.name": "Услуга",
        db.Booking.starts_at: "Дата и время",
        db.Booking.status: "Статус",
        db.Booking.rating: "Оценка",
        db.Booking.review_text: "Отзыв",
        db.Booking.review_hidden: "Отзыв скрыт",
        db.Booking.guest_name: "Офлайн-клиент",
    }
    column_searchable_list = [db.Booking.starts_at, db.Booking.status]
    column_sortable_list = [db.Booking.id, db.Booking.starts_at, db.Booking.status, db.Booking.rating]
    column_default_sort = [(db.Booking.starts_at, True)]


class PortfolioAdmin(RoleAwareView, model=db.Portfolio):
    name = "Фото портфолио"
    name_plural = "Портфолио"
    icon = "fa-solid fa-images"

    column_list = [db.Portfolio.id, "stylist.name", db.Portfolio.telegram_photo_file_id]
    column_labels = {"stylist.name": "Мастер", db.Portfolio.telegram_photo_file_id: "Telegram file_id"}
    column_sortable_list = [db.Portfolio.id]


admin.add_view(CatalogServiceAdmin)
admin.add_view(BarbershopAdmin)
admin.add_view(UserAdmin)
admin.add_view(StylistAdmin)
admin.add_view(ServiceAdmin)
admin.add_view(ScheduleAdmin)
admin.add_view(BookingAdmin)
admin.add_view(PortfolioAdmin)


@app.get("/")
async def index():
    db_status, db_error = await _check_database()
    return HTMLResponse(_render_status_page(db_status, db_error))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not _is_admin_authenticated(request):
        return RedirectResponse("/admin/login")
    try:
        data = await _collect_dashboard_data()
    except SQLAlchemyError as exc:
        return HTMLResponse(_render_dashboard_error(exc), status_code=503)
    return HTMLResponse(_render_dashboard(data))


@app.get("/reviews", response_class=HTMLResponse)
async def reviews_moderation(request: Request):
    """
    Очередь модерации отзывов.

    Отдельная страница, а не фильтр в CRUD: модератору нужен текст целиком
    и одно нажатие, чтобы скрыть, — в табличном списке sqladmin отзыв
    обрезается до неузнаваемости.
    """
    if not _is_admin_authenticated(request):
        return RedirectResponse("/admin/login")
    try:
        async with db.async_session() as session:
            rows = await load_reviews_for_moderation(session)
            data = [
                {
                    "id": item.id,
                    "author": (item.user.first_name if item.user else None) or "—",
                    "stylist": item.stylist.name if item.stylist else "—",
                    "rating": item.rating or 0,
                    "when": timeutils.format_slot(item.starts_at),
                    "text": item.review_text or "",
                    "hidden": bool(item.review_hidden),
                }
                for item in rows
            ]
    except SQLAlchemyError as exc:
        return HTMLResponse(_render_dashboard_error(exc), status_code=503)
    return HTMLResponse(
        _render_reviews(data, can_moderate=current_role(request) == security.ROLE_OWNER)
    )


@app.post("/reviews/{booking_id}/toggle")
async def toggle_review_visibility(booking_id: int, request: Request):
    """
    Скрыть отзыв или вернуть его. Текст при этом не трогаем: разбирать
    жалобу «почему скрыли мой отзыв» по пустой колонке невозможно.
    """
    # Скрытие отзыва — не работа помощника: он разбирает заявки, а не решает,
    # чьё мнение о мастере увидят клиенты.
    if current_role(request) != security.ROLE_OWNER:
        logging.warning(
            "review.moderation_denied user=%s role=%s booking_id=%s",
            current_username(request), current_role(request), booking_id,
        )
        return RedirectResponse("/reviews", status_code=303)

    async with db.async_session() as session:
        booking = await session.get(db.Booking, booking_id)
        if booking and booking.review_text:
            booking.review_hidden = not booking.review_hidden
            # Скрытие чужого отзыва — именно то действие, о котором потом
            # спрашивают «кто и почему». Журнал уезжает тем же commit'ом.
            # Подписываем тем, кто вошёл, а не владельцем из настроек:
            # иначе действие помощника записалось бы на владельца.
            audit.record_admin(
                session,
                audit.REVIEW_HIDDEN if booking.review_hidden else audit.REVIEW_RESTORED,
                current_username(request),
                booking_id=booking_id,
            )
            await session.commit()
            logging.info(
                "review.moderated booking_id=%s hidden=%s", booking_id, booking.review_hidden
            )

    return RedirectResponse("/reviews", status_code=303)


@app.get("/audit", response_class=HTMLResponse)
async def audit_feed(request: Request):
    """
    Журнал действий над записями.

    Раньше на вопрос «кто отменил эту запись и когда» ответить было нечем:
    статус менялся, а следов не оставалось.
    """
    if not _is_admin_authenticated(request):
        return RedirectResponse("/admin/login")
    try:
        async with db.async_session() as session:
            entries = await audit.load_feed(session)
            rows = [
                {
                    "when": timeutils.format_slot(item.created_at),
                    "action": AUDIT_LABELS.get(item.action, item.action),
                    "actor": _audit_actor(item),
                    "booking_id": item.booking_id,
                    "details": item.details or "",
                }
                for item in entries
            ]
    except SQLAlchemyError as exc:
        return HTMLResponse(_render_dashboard_error(exc), status_code=503)
    return HTMLResponse(_render_audit(rows))


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """
    Метрики в текстовом формате Prometheus.

    Без авторизации намеренно: система наблюдения ходит сюда без сессии,
    а внутри только агрегаты — ни одного персонального значения. Наружу
    эндпоинт всё равно не торчит: порт админки проброшен на localhost.
    """
    try:
        async with db.async_session() as session:
            snapshot = await metrics.collect(session)
    except SQLAlchemyError as exc:
        # Явный текст вместо пустого ответа: молчащий /metrics система
        # наблюдения примет за «метрик нет», а не за «база недоступна».
        logging.warning("metrics.failed error=%s", exc)
        return PlainTextResponse("# база недоступна" + chr(10), status_code=503)
    return PlainTextResponse(snapshot.as_prometheus())


@app.get("/health")
async def healthcheck():
    db_status, db_error = await _check_database()
    return {
        "status": "ok",
        "date": timeutils.today().isoformat(),
        "admin": "configured",
        "database": db_status,
        "database_error": db_error,
    }


if __name__ == "__main__":
    uvicorn.run("admin_panel:app", host="127.0.0.1", port=8002, reload=False)
