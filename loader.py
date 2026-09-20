"""
Объекты бота и диспетчера.

Вынесены отдельно, чтобы хендлеры из разных модулей могли отправлять сообщения,
не импортируя точку входа: bot.py импортирует хендлеры, и обратный импорт
дал бы цикл.

Здесь же регистрируется антифлуд — он должен стоять раньше любых хендлеров.
"""
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

import middlewares
from config import check_environment, load_bot_settings

load_dotenv()
logging.basicConfig(level=logging.INFO)

# Окружение проверяется до создания Bot: иначе первая же недостающая
# переменная роняет импорт своим трейсбеком, и про остальные человек
# узнаёт только на следующем запуске. Пароль админки здесь не нужен —
# бота можно запускать без неё.
check_environment(groups=("bot", "database"))

# Токен проверяется на похожесть на токен Telegram, а не уезжает в первый же
# запрос, чтобы вернуться оттуда «Unauthorized» без объяснения, что не так.
BOT = load_bot_settings()


def build_storage():
    """
    RedisStorage, если задан REDIS_URL, иначе MemoryStorage.

    С MemoryStorage незавершённый сценарий записи теряется при каждом рестарте
    бота — для прода нужен Redis (docs/AUDIT.md, A-6).
    """
    redis_url = BOT.redis_url
    if not redis_url:
        logging.warning(
            "storage.memory_fallback REDIS_URL не задан: состояние сценариев "
            "будет теряться при рестарте бота"
        )
        return MemoryStorage()

    from aiogram.fsm.storage.redis import RedisStorage

    logging.info("storage.redis url=%s", redis_url.split("@")[-1])
    return RedisStorage.from_url(redis_url)

storage = build_storage()

bot = Bot(token=BOT.token)

dp = Dispatcher(storage=storage)

# Порядок здесь — это порядок обёртывания, и он не случайный:
#   1. логирование снаружи всего, иначе отброшенные антифлудом апдейты
#      не попадут в лог и при разборе инцидента их будто бы не было;
#   2. кеш пользователя следующим — им пользуется и антифлуд, и хендлеры;
#   3. антифлуд последним, чтобы лишнее отсекалось до похода в базу.
logging_mw = middlewares.LoggingMiddleware()
user_context = middlewares.UserContextMiddleware()
throttling = middlewares.ThrottlingMiddleware()

for event in (dp.message, dp.callback_query):
    event.middleware(logging_mw)
    event.middleware(user_context)
    event.middleware(throttling)
