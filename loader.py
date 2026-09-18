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
from config import get_optional_env, get_required_env

load_dotenv()
logging.basicConfig(level=logging.INFO)


def build_storage():
    """
    RedisStorage, если задан REDIS_URL, иначе MemoryStorage.

    С MemoryStorage незавершённый сценарий записи теряется при каждом рестарте
    бота — для прода нужен Redis (docs/AUDIT.md, A-6).
    """
    redis_url = get_optional_env("REDIS_URL")
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

bot = Bot(token=get_required_env("BOT_TOKEN"))

dp = Dispatcher(storage=storage)

# Антифлуд. Регистрируется на оба типа апдейтов: быстрые повторные нажатия
# порождают параллельные запросы к базе и дублирующие уведомления.
throttling = middlewares.ThrottlingMiddleware()
dp.message.middleware(throttling)
dp.callback_query.middleware(throttling)
