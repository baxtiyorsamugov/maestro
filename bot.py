"""
Точка входа бота.

Здесь только сборка: подключение роутеров, обработчик ошибок, фоновые задачи
и запуск поллинга. Сами хендлеры живут в handlers/, бизнес-логика — в services/.

Объекты bot и dp создаются в loader.py, а не здесь: хендлеры должны иметь
возможность отправлять сообщения, не импортируя точку входа — иначе цикл.
"""
import asyncio
import logging
import sys

from aiogram.types import ErrorEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import database as db
import handlers
import observability
import scheduler
from config import load_sentry_settings
from guards import get_user_lang
from keyboards import get_main_keyboard
from loader import bot, dp

# Ошибка на проде видна только в логах контейнера — то есть её никто
# не видит, пока не пойдёт смотреть. Без SENTRY_DSN ничего не включается.
_sentry = load_sentry_settings()
observability.init_sentry(_sentry.dsn, _sentry.environment, component="bot")

ERROR_TEXT = {
    "ru": "Что-то пошло не так. Мы уже разбираемся, попробуйте через минуту.",
    "uz": "Nimadir xato ketdi. Biz tekshiryapmiz, bir daqiqadan so'ng urinib ko'ring.",
}


def register_routers() -> None:
    """
    Порядок подключения = порядок проверки фильтров.

    Сам порядок задан списком в handlers/__init__.py — там же объяснено,
    какие две зависимости в нём нельзя нарушать.
    """
    for router in handlers.ROUTERS:
        dp.include_router(router)


register_routers()


# Обработчик ошибок остаётся на диспетчере, а не в роутере: только так он
# поймает исключения из всех роутеров сразу.
@dp.errors()
async def handle_unexpected_error(event: ErrorEvent) -> bool:
    """
    Последний рубеж: любое необработанное исключение в хендлере.
    Пользователь не должен оставаться перед «зависшим» экраном без ответа.
    """
    update = event.update
    update_id = getattr(update, "update_id", None)

    # Привязываем событие к апдейту до логирования: sentry-sdk подхватывает
    # исключение из logging.exception, и теги должны быть проставлены раньше.
    source = update.callback_query or update.message
    observability.note_update(
        update_id, source.from_user.id if source and source.from_user else None
    )

    logging.exception(
        "handler.unhandled_error update_id=%s error=%s", update_id, event.exception
    )
    try:
        if update.callback_query:
            lang = await get_user_lang(update.callback_query.from_user.id)
            await update.callback_query.answer(ERROR_TEXT[lang], show_alert=True)
        elif update.message:
            lang = await get_user_lang(update.message.from_user.id)
            await update.message.answer(
                ERROR_TEXT[lang],
                reply_markup=await get_main_keyboard(update.message.from_user.id),
            )
    except Exception as e:
        logging.warning("handler.error_reply_failed error=%s", e)

    return True


def start_scheduler() -> AsyncIOScheduler:
    """Фоновые задачи: напоминания, follow-up, контроль срока тарифа."""
    tasks = AsyncIOScheduler(timezone="Asia/Tashkent")
    tasks.add_job(scheduler.check_reminders, "cron", hour="*", minute=0, args=(bot,))
    tasks.add_job(scheduler.check_follow_ups, "cron", hour=10, minute=0, args=(bot,))
    tasks.add_job(scheduler.check_subscription_expiry, "cron", hour=10, minute=5, args=(bot,))
    tasks.start()
    logging.info("scheduler.started jobs=%s", len(tasks.get_jobs()))
    return tasks


async def main() -> None:
    await db.run_migrations()
    tasks = start_scheduler()

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        # Без явной остановки процесс не завершается: шедулер держит свои потоки,
        # а незакрытый пул соединений оставляет висящие сессии в базе.
        tasks.shutdown(wait=False)
        await bot.session.close()
        await db.engine.dispose()
        logging.info("bot.stopped")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
