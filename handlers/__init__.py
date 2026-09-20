"""
Хендлеры бота, разложенные по доменам.

Порядок подключения роутеров — это порядок проверки фильтров, поэтому
он задаётся здесь явно и одним списком, а не разбросан по вызовам include_router.

Две зависимости от порядка, которые нельзя нарушать:
  * stylist_card идёт до booking: show_maestro_card ловит префикс stylist_,
    а show_services — ("book_", "maestro_", "stylist_"). Поменяй местами —
    и карточка мастера перестанет открываться;
  * fallback идёт последним: он отвечает на любое сообщение;
  * offline_booking идёт после остальных роутеров мастера: он ждёт имя
    офлайн-клиента обычным сообщением, и будь он раньше — кнопки панели
    («Мои записи», «Расписание») попадали бы в поле ввода имени.
"""
from handlers import fallback
from handlers.client import booking, profile, registration, stylist_card
from handlers.client import search as client_search
from handlers.stylist import (
    bookings,
    offline_booking,
    panel,
    portfolio,
    schedule,
    special_dates,
    stats,
)
from handlers.stylist import services as stylist_services

ROUTERS = [
    registration.router,
    client_search.router,
    stylist_card.router,
    booking.router,
    profile.router,
    panel.router,
    bookings.router,
    schedule.router,
    special_dates.router,
    stylist_services.router,
    portfolio.router,
    stats.router,
    offline_booking.router,
    fallback.router,
]
