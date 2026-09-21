"""
Точка входа бота.

Здесь только сборка: подключение роутеров, обработчик ошибок, фоновые задачи
и запуск: поллинг локально, вебхук на проде (задан WEBHOOK_URL).
Сами хендлеры живут в handlers/, бизнес-логика — в services/.

Объекты bot и dp создаются в loader.py, а не здесь: хендлеры должны иметь
возможность отправлять сообщения, не импортируя точку входа — иначе цикл.
"""
import asyncio
import logging
import sys

from aiogram.types import ErrorEvent
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import database as db
import handlers
import observability
import scheduler
import security
import texts
from config import WebhookSettings, load_sentry_settings, load_webhook_settings
from guards import get_user_lang
from keyboards import get_main_keyboard
from loader import bot, dp

# Ошибка на проде видна только в логах контейнера — то есть её никто
# не видит, пока не пойдёт смотреть. Без SENTRY_DSN ничего не включается.
_sentry = load_sentry_settings()
observability.init_sentry(_sentry.dsn, _sentry.environment, component="bot")


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
            await update.callback_query.answer(
                texts.get_text("unexpected_error", lang), show_alert=True
            )
        elif update.message:
            lang = await get_user_lang(update.message.from_user.id)
            await update.message.answer(
                texts.get_text("unexpected_error", lang),
                reply_markup=await get_main_keyboard(update.message.from_user.id),
            )
    except Exception as e:
        logging.warning("handler.error_reply_failed error=%s", e)

    return True


def start_scheduler() -> AsyncIOScheduler:
    """Фоновые задачи: напоминания, follow-up, контроль срока тарифа."""
    tasks = AsyncIOScheduler(timezone="Asia/Tashkent")
    # Каждые 15 минут, а не раз в час: слоты идут с шагом «длительность +
    # буфер», и визит в 11:30 при ежечасном запуске не попадал в окно
    # часового напоминания ни в 10:00 (осталось 90 минут), ни в 11:00 (30).
    tasks.add_job(
        scheduler.check_reminders, "cron",
        minute=f"*/{scheduler.REMINDER_INTERVAL_MIN}", args=(bot,),
    )
    tasks.add_job(scheduler.check_follow_ups, "cron", hour=10, minute=0, args=(bot,))
    tasks.add_job(scheduler.check_subscription_expiry, "cron", hour=10, minute=5, args=(bot,))
    # Раз в день, утром: сводка проблем владельцу. Молчит, когда сказать нечего —
    # ежедневное «всё хорошо» читать перестают через неделю, а вместе с ним
    # перестают читать и настоящие предупреждения.
    tasks.add_job(scheduler.send_health_alerts, "cron", hour=9, minute=0, args=(bot,))
    tasks.start()
    logging.info("scheduler.started jobs=%s", len(tasks.get_jobs()))
    return tasks


class WebhookHandler(SimpleRequestHandler):
    """
    Приём апдейтов со сверкой секрета через security.constant_time_equals.

    aiogram сверяет заголовок через secrets.compare_digest на str, а тот на
    не-ASCII бросает TypeError (S-11 в docs/SECURITY.md). Заголовок присылает
    кто угодно, так что запрос с кириллицей в нём ронял бы обработку
    пятисоткой вместо спокойного 401.
    """

    def verify_secret(self, telegram_secret_token: str, bot) -> bool:
        if not self.secret_token:
            return False
        return security.constant_time_equals(telegram_secret_token, self.secret_token)


def build_webhook_app(settings: WebhookSettings) -> web.Application:
    """
    aiohttp-приложение, которое принимает апдейты от Telegram.

    Секрет сверяет сам aiogram: запрос без заголовка
    X-Telegram-Bot-Api-Secret-Token или с чужим значением получает 401
    и до диспетчера не доходит. Без этой проверки кто угодно, узнавший адрес,
    слал бы поддельные нажатия от имени любого пользователя.
    """
    app = web.Application()

    async def health(_request: web.Request) -> web.Response:
        # nginx и docker healthcheck проверяют процесс, не трогая Telegram.
        return web.json_response({"status": "ok"})

    app.router.add_get("/health", health)
    WebhookHandler(
        dispatcher=dp, bot=bot, secret_token=settings.secret,
    ).register(app, path=settings.path)
    setup_application(app, dp, bot=bot)
    return app


async def run_webhook(settings: WebhookSettings) -> None:
    app = build_webhook_app(settings)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host=settings.host, port=settings.port).start()

    # drop_pending_updates=False сознательно: апдейты, пришедшие во время
    # рестарта, — это нажатия живых людей («Записаться», «Подтвердить»).
    # При поллинге их сбрасывали; вебхук позволяет их не терять.
    await bot.set_webhook(
        settings.full_url,
        secret_token=settings.secret,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=False,
    )
    # Адрес целиком не пишем: путь может быть частью защиты.
    logging.info("bot.webhook url=%s port=%s", settings.url, settings.port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


async def run_polling() -> None:
    # Поллинг и вебхук взаимоисключающие: пока вебхук стоит, getUpdates
    # отвечает ошибкой. Снимаем его — это и есть переход обратно на поллинг.
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("bot.polling")
    await dp.start_polling(bot)


async def main() -> None:
    await db.run_migrations()
    tasks = start_scheduler()
    webhook = load_webhook_settings()

    try:
        if webhook.enabled:
            await run_webhook(webhook)
        else:
            await run_polling()
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
