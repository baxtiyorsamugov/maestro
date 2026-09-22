"""
Вебхук-режим (docs/ROADMAP.md, C-7).

Две группы проверок. Настройки: вебхук без секрета или по http не должен
запуститься вовсе — узнать об этом на старте дешевле, чем по поддельным
апдейтам. Приём: запрос без секрета или с чужим секретом до диспетчера
не доходит, а настоящий — проходит весь путь до хендлера.
"""
import asyncio

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from scenario_harness import RecordingSession

import bot as entry
import config
import loader

WEBHOOK_VARS = ("WEBHOOK_URL", "WEBHOOK_PATH", "WEBHOOK_SECRET", "WEBHOOK_HOST", "WEBHOOK_PORT")
SECRET = "s" * config.MIN_WEBHOOK_SECRET_LEN


@pytest.fixture
def webhook_env(monkeypatch):
    for name in WEBHOOK_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class TestSettings:
    def test_polling_by_default(self, webhook_env):
        settings = config.load_webhook_settings()
        assert not settings.enabled
        assert config.describe_problems(("webhook",)) == []

    def test_url_without_secret_is_refused(self, webhook_env):
        """Без секрета любой, кто узнал адрес, шлёт поддельные нажатия."""
        webhook_env.setenv("WEBHOOK_URL", "https://bot.example.uz")
        problems = config.describe_problems(("webhook",))
        assert any("WEBHOOK_SECRET" in p for p in problems), problems

    def test_plain_http_is_refused(self, webhook_env):
        webhook_env.setenv("WEBHOOK_URL", "http://bot.example.uz")
        webhook_env.setenv("WEBHOOK_SECRET", SECRET)
        problems = config.describe_problems(("webhook",))
        assert any("WEBHOOK_URL" in p and "https" in p for p in problems), problems

    @pytest.mark.parametrize("secret", ["короткий", "a b" * 20, "s" * 10, "x" * 257])
    def test_bad_secret_is_refused(self, webhook_env, secret):
        """Telegram принимает только A-Z, a-z, 0-9, _ и - — проверяем до него."""
        webhook_env.setenv("WEBHOOK_URL", "https://bot.example.uz")
        webhook_env.setenv("WEBHOOK_SECRET", secret)
        assert config.describe_problems(("webhook",))

    def test_full_url_joins_without_double_slash(self, webhook_env):
        webhook_env.setenv("WEBHOOK_URL", "https://bot.example.uz/")
        webhook_env.setenv("WEBHOOK_SECRET", SECRET)
        settings = config.load_webhook_settings()
        assert settings.enabled
        assert settings.full_url == "https://bot.example.uz/telegram/webhook"

    def test_all_problems_listed_at_once(self, webhook_env):
        """Как и остальные группы: все претензии разом, а не по одной за запуск."""
        webhook_env.setenv("WEBHOOK_URL", "http://bot.example.uz")
        webhook_env.setenv("WEBHOOK_PATH", "no-slash")
        problems = config.describe_problems(("webhook",))
        assert any("WEBHOOK_URL" in p for p in problems)
        assert any("WEBHOOK_PATH" in p for p in problems)


def _update(telegram_id: int = 9101) -> dict:
    return {
        "update_id": 555001,
        "message": {
            "message_id": 1,
            "date": 1_700_000_000,
            "chat": {"id": telegram_id, "type": "private"},
            "from": {"id": telegram_id, "is_bot": False, "first_name": "Web"},
            "text": "/start",
            "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
        },
    }


@pytest_asyncio.fixture
async def client(session):
    """
    Настоящее aiohttp-приложение бота с подменённой сессией Telegram.
    Антифлуд выключен по той же причине, что в test_scenarios.
    """
    recording = RecordingSession()
    original_session = loader.bot.session
    loader.bot.session = recording
    original_is_throttled = loader.throttling._is_throttled
    loader.throttling._is_throttled = lambda user_id: False
    loader.dp.storage.storage.clear()

    settings = config.WebhookSettings(WEBHOOK_URL="https://bot.example.uz", WEBHOOK_SECRET=SECRET)
    test_client = TestClient(TestServer(entry.build_webhook_app(settings)))
    await test_client.start_server()
    test_client.recording = recording
    test_client.settings = settings

    yield test_client

    await test_client.close()
    loader.bot.session = original_session
    loader.throttling._is_throttled = original_is_throttled
    loader.dp.storage.storage.clear()


async def _wait_for_calls(recording: RecordingSession, limit_seconds: float = 3.0) -> list:
    """
    Апдейт обрабатывается в фоне: Telegram получает 200 сразу, не дожидаясь хендлера.

    Опрос, а не Event: фоновую задачу создаёт aiogram внутри себя, и дождаться
    её из теста напрямую нечем. Предел по времени не даёт тесту зависнуть.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit_seconds
    while not recording.calls and loop.time() < deadline:  # noqa: ASYNC110
        await asyncio.sleep(0.02)
    return recording.calls


class TestReceiving:
    async def test_health_answers_without_telegram(self, client):
        response = await client.get("/health")
        assert response.status == 200
        assert (await response.json()) == {"status": "ok"}

    async def test_request_without_secret_is_rejected(self, client):
        response = await client.post(client.settings.path, json=_update())
        assert response.status == 401
        await asyncio.sleep(0.1)
        assert client.recording.calls == [], "апдейт без секрета дошёл до хендлеров"

    async def test_wrong_secret_is_rejected(self, client):
        response = await client.post(
            client.settings.path, json=_update(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "w" * len(SECRET)},
        )
        assert response.status == 401
        await asyncio.sleep(0.1)
        assert client.recording.calls == []

    async def test_non_ascii_secret_is_401_not_500(self, client):
        """
        Заголовок присылает кто угодно. secrets.compare_digest на str с
        кириллицей бросает TypeError — без своей сверки это была бы пятисотка.
        """
        response = await client.post(
            client.settings.path, json=_update(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "секрет".encode().decode("latin-1")},
        )
        assert response.status == 401

    async def test_genuine_update_reaches_the_handler(self, client):
        """Правильный секрет — и /start проходит весь путь до ответа человеку."""
        response = await client.post(
            client.settings.path, json=_update(9101),
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        )
        assert response.status == 200

        calls = await _wait_for_calls(client.recording)
        assert any(
            type(c).__name__ == "SendMessage" and c.chat_id == 9101 for c in calls
        ), f"бот не ответил на /start через вебхук: {[type(c).__name__ for c in calls]}"
