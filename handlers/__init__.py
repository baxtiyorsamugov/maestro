"""
Хендлеры бота, разложенные по доменам.

Порядок подключения роутеров — это порядок проверки фильтров, поэтому
он задаётся здесь явно и одним списком, а не разбросан по вызовам.
"""
from handlers import fallback
from handlers.stylist import bookings, panel, portfolio, schedule, services, stats

# Роутер fallback обязан быть последним: он отвечает на всё подряд.
ROUTERS = [
    panel.router,
    bookings.router,
    schedule.router,
    services.router,
    portfolio.router,
    stats.router,
    fallback.router,
]
