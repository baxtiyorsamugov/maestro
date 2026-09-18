"""
Middleware бота.

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

logger = logging.getLogger(__name__)

THROTTLE_WARNING = {
    "ru": "Слишком быстро. Подождите пару секунд.",
    "uz": "Juda tez. Bir necha soniya kuting.",
}


def throttle_message(lang: str | None) -> str:
    """Текст предупреждения. Вынесен отдельно, чтобы проверяться без Telegram."""
    return THROTTLE_WARNING.get(lang or "ru", THROTTLE_WARNING["ru"])


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

        logger.warning("throttle.blocked user_id=%s event=%s", user.id, type(event).__name__)

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
