"""
Тесты антифлуда (docs/AUDIT.md, B-8).

Без ограничителя быстрые повторные нажатия порождают параллельные запросы
к базе и дублирующие уведомления: нажатие «Подтвердить» два раза подряд
отправляло клиенту два сообщения.
"""
import asyncio
import time
from dataclasses import dataclass, field

import pytest

from middlewares import ThrottlingMiddleware, throttle_message


@dataclass
class FakeUser:
    id: int = 1
    language_code: str = "ru"


@dataclass
class FakeEvent:
    """Минимальный апдейт: middleware различает типы через isinstance."""

    answers: list = field(default_factory=list)

    async def answer(self, text="", **kwargs):
        self.answers.append(text)


async def call(middleware: ThrottlingMiddleware, user: FakeUser) -> bool:
    """True — хендлер выполнился, False — был заблокирован."""
    executed = False

    async def handler(event, data):
        nonlocal executed
        executed = True
        return "результат"

    await middleware(handler, FakeEvent(), {"event_from_user": user})
    return executed


class TestThrottling:
    async def test_first_action_passes(self):
        middleware = ThrottlingMiddleware()
        assert await call(middleware, FakeUser())

    async def test_burst_is_allowed(self):
        """Двойной клик не должен выглядеть атакой."""
        middleware = ThrottlingMiddleware(burst=3)
        user = FakeUser()
        results = [await call(middleware, user) for _ in range(3)]
        assert all(results)

    async def test_blocks_beyond_burst(self):
        middleware = ThrottlingMiddleware(burst=3)
        user = FakeUser()
        for _ in range(3):
            await call(middleware, user)
        assert not await call(middleware, user)

    async def test_limit_is_per_user(self):
        middleware = ThrottlingMiddleware(burst=2)
        first, second = FakeUser(id=1), FakeUser(id=2)

        for _ in range(3):
            await call(middleware, first)

        assert not await call(middleware, first)
        assert await call(middleware, second), "чужой флуд не должен блокировать других"

    async def test_passes_again_after_window(self):
        middleware = ThrottlingMiddleware(rate_limit=0.01, burst=2)
        user = FakeUser()
        for _ in range(3):
            await call(middleware, user)

        await asyncio.sleep(0.05)
        assert await call(middleware, user)

    async def test_event_without_user_passes_through(self):
        """Служебные апдейты без пользователя ограничивать нечем и незачем."""
        middleware = ThrottlingMiddleware(burst=1)
        executed = 0

        async def handler(event, data):
            nonlocal executed
            executed += 1

        for _ in range(5):
            await middleware(handler, FakeEvent(), {})

        assert executed == 5


class TestWarning:
    """
    Отправка предупреждения завязана на реальные типы aiogram (CallbackQuery,
    Message) — подделкой это не проверить, а поднимать фейковый Telegram ради
    одной строки неоправданно. Поэтому выбор текста вынесен в чистую функцию
    и проверяется здесь, а частота предупреждений — через _should_warn.
    """

    @pytest.mark.parametrize(
        ("lang", "fragment"),
        [("ru", "быстро"), ("uz", "tez"), (None, "быстро"), ("en", "быстро")],
    )
    def test_warning_language(self, lang, fragment):
        assert fragment in throttle_message(lang)

    def test_warning_is_rate_limited(self):
        """Предупреждать на каждое нажатие — это тоже спам, только от нас."""
        middleware = ThrottlingMiddleware(warn_cooldown=10)
        assert middleware._should_warn(1) is True
        assert middleware._should_warn(1) is False
        assert middleware._should_warn(1) is False

    def test_warning_cooldown_is_per_user(self):
        middleware = ThrottlingMiddleware(warn_cooldown=10)
        assert middleware._should_warn(1) is True
        assert middleware._should_warn(2) is True

    def test_warning_returns_after_cooldown(self):
        middleware = ThrottlingMiddleware(warn_cooldown=0)
        assert middleware._should_warn(1) is True
        time.sleep(0.01)
        assert middleware._should_warn(1) is True
