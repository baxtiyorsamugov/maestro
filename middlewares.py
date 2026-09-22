"""
Middleware бота.

Порядок регистрации задан в loader.py и важен: логирование должно охватывать
всё остальное, кеш пользователя — существовать до антифлуда (тот читает язык),
а антифлуд — отсекать лишнее до того, как хендлер пойдёт в базу.

Пока файл один: выносить в пакет имеет смысл вместе с общим разбором bot.py
(Фаза 3 дорожной карты), а не раньше.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

import guards
import texts
from logutil import mask_user

logger = logging.getLogger(__name__)

def throttle_message(lang: str | None) -> str:
    """
    Текст предупреждения. Вынесен отдельно, чтобы проверяться без Telegram.

    lang здесь — язык клиента Telegram (например, «en»), а не выбранный
    в боте: get_text откатывается на русский для незнакомого языка.
    """
    return texts.get_text("throttled", lang or "ru")


class ThrottlingMiddleware(BaseMiddleware):
    """
    Ограничение частоты действий на пользователя.

    Зачем: без него быстрые повторные нажатия «Записаться» или «Подтвердить»
    порождают параллельные запросы к базе и дублирующие уведомления.
    Живой человек не нажимает кнопку чаще пары раз в секунду.

    Состояние в памяти процесса. Для одного инстанса этого достаточно;
    при переходе на несколько процессов счётчик надо вынести в Redis —
    туда же, где будет FSM.
    """

    def __init__(
        self,
        rate_limit: float = 0.5,
        burst: int = 3,
        warn_cooldown: float = 3.0,
    ) -> None:
        # rate_limit — минимальный интервал между действиями, burst — сколько
        # действий подряд прощаем (двойной клик не должен выглядеть атакой).
        self.rate_limit = rate_limit
        self.burst = burst
        self.warn_cooldown = warn_cooldown
        self._history: dict[int, list[float]] = defaultdict(list)
        self._last_warning: dict[int, float] = {}

    def _is_throttled(self, user_id: int) -> bool:
        now = time.monotonic()
        window_start = now - self.rate_limit * self.burst

        history = [t for t in self._history[user_id] if t > window_start]
        history.append(now)
        self._history[user_id] = history

        return len(history) > self.burst

    def _should_warn(self, user_id: int) -> bool:
        """Предупреждаем не чаще раза в несколько секунд, чтобы не спамить в ответ."""
        now = time.monotonic()
        if now - self._last_warning.get(user_id, 0) < self.warn_cooldown:
            return False
        self._last_warning[user_id] = now
        return True

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if not self._is_throttled(user.id):
            return await handler(event, data)

        logger.warning(
            "throttle.blocked user=%s event=%s", mask_user(user.id), type(event).__name__
        )

        if not self._should_warn(user.id):
            # Callback всё равно нужно закрыть, иначе в клиенте висят «часики».
            if isinstance(event, CallbackQuery):
                await event.answer()
            return None

        text = throttle_message(getattr(user, "language_code", None))

        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=False)
        elif isinstance(event, Message):
            await event.answer(text)

        return None


class UserContextMiddleware(BaseMiddleware):
    """
    Один запрос к users на апдейт вместо трёх-четырёх.

    Раньше одно нажатие кнопки приводило к ensure_registered_callback,
    затем к get_user_lang, затем к ещё одному get_user_lang внутри
    deny_access — три одинаковых SELECT и три соединения к базе.

    Кеш живёт ровно один апдейт и лежит в ContextVar: апдейты обрабатываются
    конкурентно, и общий словарь выдавал бы одному пользователю данные другого.
    Хендлеры менять не пришлось — они по-прежнему зовут guards.get_user_lang().
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        token = guards.open_user_cache()
        try:
            return await handler(event, data)
        finally:
            guards.close_user_cache(token)


class LoggingMiddleware(BaseMiddleware):
    """
    Одна строка на апдейт: что пришло, от кого и сколько заняло.

    До этого при разборе инцидента не было даже точки отсчёта — по логам нельзя
    было сказать, дошёл ли апдейт до бота вообще. update_id связывает строки
    одного нажатия между собой, включая те, что пишут сами хендлеры.

    Идентификатор пользователя маскируется (CLAUDE.md, 4.4).
    """

    #: Медленный апдейт заслуживает WARNING, а не INFO: такие и ищут в логах.
    SLOW_SECONDS = 3.0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        update = data.get("event_update")
        update_id = getattr(update, "update_id", "?")
        # Текст сообщения в лог не попадает: это переписка живых людей.
        # Для callback пишем data — это наши же служебные строки.
        action = event.data if isinstance(event, CallbackQuery) else type(event).__name__

        started = time.monotonic()
        try:
            return await handler(event, data)
        except Exception:
            logger.exception(
                "update.failed id=%s user=%s action=%s",
                update_id, mask_user(getattr(user, "id", None)), action,
            )
            raise
        finally:
            elapsed = time.monotonic() - started
            level = logging.WARNING if elapsed >= self.SLOW_SECONDS else logging.INFO
            logger.log(
                level,
                "update.done id=%s user=%s action=%s elapsed=%.3f",
                update_id, mask_user(getattr(user, "id", None)), action, elapsed,
            )
