"""
Тесты кеша пользователя и маскировки в логах (docs/ROADMAP.md, Фаза 3).

Две проблемы, найденные при разборе middleware.

1. Одно нажатие кнопки читало строку из users три-четыре раза:
   ensure_registered_callback, затем get_user_lang, затем ещё раз внутри
   deny_access. Запросы одинаковые, соединений к базе — по числу вызовов.

2. CLAUDE.md, 4.4 запрещает писать telegram_id в логи открытым текстом,
   но правило было только на бумаге: девять мест печатали настоящий id.
   Логи проекта уже лежали в репозитории (docs/SECURITY.md, S-3),
   так что риск не теоретический.

Самое опасное в кеше — устаревание. Клиент меняет язык, строка в базе
обновляется, а кеш апдейта продолжает отдавать старую: подтверждение
о смене языка приходит на языке, который только что сменили.
"""
import logging

import pytest

import database as db
import guards
import logutil
import middlewares


@pytest.fixture(autouse=True)
def clean_context():
    """Каждый тест начинается без открытого кеша."""
    token = guards._user_cache.set(None)
    yield
    guards._user_cache.reset(token)


class TestUserCache:
    async def test_without_cache_every_call_goes_to_db(self, fixture_data, monkeypatch):
        """Базовое поведение вне апдейта не меняется: кеша нет — идём в базу."""
        calls = []

        async def fake(telegram_id):
            calls.append(telegram_id)
            return fixture_data["client_user"]

        monkeypatch.setattr(guards, "_load_user_from_db", fake)

        await guards.get_user_by_telegram_id(2002)
        await guards.get_user_by_telegram_id(2002)

        assert len(calls) == 2

    async def test_inside_update_second_call_is_free(self, fixture_data, monkeypatch):
        """Главное: три вызова за апдейт — один запрос к базе."""
        calls = []

        async def fake(telegram_id):
            calls.append(telegram_id)
            return fixture_data["client_user"]

        monkeypatch.setattr(guards, "_load_user_from_db", fake)

        token = guards.open_user_cache()
        try:
            await guards.get_user_by_telegram_id(2002)
            await guards.get_user_by_telegram_id(2002)
            await guards.get_user_by_telegram_id(2002)
        finally:
            guards.close_user_cache(token)

        assert len(calls) == 1, f"походов в базу: {len(calls)}, ожидался один"

    async def test_missing_user_is_cached_too(self, monkeypatch):
        """
        Отсутствие пользователя тоже кешируется: незарегистрированный
        человек не должен обходиться дороже зарегистрированного.
        """
        calls = []

        async def fake(telegram_id):
            calls.append(telegram_id)
            return None

        monkeypatch.setattr(guards, "_load_user_from_db", fake)

        token = guards.open_user_cache()
        try:
            assert await guards.get_user_by_telegram_id(999) is None
            assert await guards.get_user_by_telegram_id(999) is None
        finally:
            guards.close_user_cache(token)

        assert len(calls) == 1

    async def test_different_users_do_not_mix(self, monkeypatch):
        async def fake(telegram_id):
            user = db.User(telegram_id=telegram_id)
            user.language_code = "uz" if telegram_id == 2 else "ru"
            return user

        monkeypatch.setattr(guards, "_load_user_from_db", fake)

        token = guards.open_user_cache()
        try:
            assert await guards.get_user_lang(1) == "ru"
            assert await guards.get_user_lang(2) == "uz"
            assert await guards.get_user_lang(1) == "ru"
        finally:
            guards.close_user_cache(token)

    async def test_forget_user_drops_stale_row(self, monkeypatch):
        """
        Клиент сменил язык — кеш обязан о нём забыть. Иначе подтверждение
        о смене придёт на языке, который только что сменили.
        """
        state = {"lang": "ru"}

        async def fake(telegram_id):
            user = db.User(telegram_id=telegram_id)
            user.language_code = state["lang"]
            return user

        monkeypatch.setattr(guards, "_load_user_from_db", fake)

        token = guards.open_user_cache()
        try:
            assert await guards.get_user_lang(1) == "ru"
            state["lang"] = "uz"
            assert await guards.get_user_lang(1) == "ru", "кеш должен держать старое"

            guards.forget_user(1)
            assert await guards.get_user_lang(1) == "uz", "после forget_user — свежее"
        finally:
            guards.close_user_cache(token)

    async def test_cache_does_not_leak_between_updates(self, monkeypatch):
        """Кеш живёт ровно один апдейт: следующий начинает с чистого листа."""
        calls = []

        async def fake(telegram_id):
            calls.append(telegram_id)
            return db.User(telegram_id=telegram_id)

        monkeypatch.setattr(guards, "_load_user_from_db", fake)

        for _ in range(2):
            token = guards.open_user_cache()
            try:
                await guards.get_user_by_telegram_id(1)
                await guards.get_user_by_telegram_id(1)
            finally:
                guards.close_user_cache(token)

        assert len(calls) == 2, "каждый апдейт читает заново"


class TestMaskUser:
    def test_same_id_gives_same_token(self):
        """Иначе строки одного пользователя не сойдутся в логе."""
        assert logutil.mask_user(123456789) == logutil.mask_user(123456789)

    def test_different_ids_give_different_tokens(self):
        assert logutil.mask_user(1) != logutil.mask_user(2)

    def test_real_id_is_not_visible_in_the_token(self):
        token = logutil.mask_user(123456789)

        assert "123456789" not in token
        assert token.isalnum()

    def test_token_is_short(self):
        assert len(logutil.mask_user(123456789)) == logutil.MASK_LEN

    def test_missing_user_has_its_own_token(self):
        assert logutil.mask_user(None) == "anon"

    def test_string_and_int_agree(self):
        """Один и тот же пользователь не должен раздваиваться из-за типа."""
        assert logutil.mask_user(42) == logutil.mask_user("42")

    def test_salt_changes_the_token(self, monkeypatch):
        """
        Без соли маскировка была бы затемнением: пространство идентификаторов
        Telegram конечно и перебирается.
        """
        monkeypatch.setenv("LOG_SALT", "first-salt")
        logutil.reset_salt_cache()
        first = logutil.mask_user(123456789)

        monkeypatch.setenv("LOG_SALT", "second-salt")
        logutil.reset_salt_cache()
        second = logutil.mask_user(123456789)

        logutil.reset_salt_cache()
        assert first != second


class TestNoRawIdsInLogs:
    """
    Проверка правила, а не реализации: если кто-то допишет логирование
    с открытым telegram_id, это должно быть видно здесь.
    """

    async def test_access_denied_does_not_print_the_id(self, caplog):
        class FakeCb:
            data = "approve_1"

            class from_user:
                id = 987654321

            async def answer(self, *args, **kwargs):
                pass

        with caplog.at_level(logging.WARNING):
            await guards.deny_access(FakeCb())

        assert "987654321" not in caplog.text
        assert logutil.mask_user(987654321) in caplog.text

    def test_throttle_warning_does_not_print_the_id(self, caplog):
        message = "throttle.blocked user=%s event=%s"

        with caplog.at_level(logging.WARNING):
            logging.getLogger("middlewares").warning(
                message, logutil.mask_user(987654321), "CallbackQuery"
            )

        assert "987654321" not in caplog.text

    def test_source_has_no_plain_user_id_logging(self):
        """
        Прямая проверка исходников: строка `user_id=%s` рядом с telegram_id
        — это ровно то, что запрещает CLAUDE.md, 4.4.
        """
        import pathlib

        root = pathlib.Path(guards.__file__).parent
        offenders = []
        for path in [
            *root.glob("handlers/**/*.py"),
            root / "guards.py",
            root / "middlewares.py",
        ]:
            if not path.exists():
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "user_id=%s" in line and "db_user_id" not in line:
                    offenders.append(f"{path.name}:{number}")

        assert offenders == [], f"telegram_id в логах открытым текстом: {offenders}"


class TestMiddlewareWiring:
    def test_all_three_are_registered(self):
        import loader

        for event in (loader.dp.message, loader.dp.callback_query):
            classes = {type(mw) for mw in event.middleware}
            for expected in (
                middlewares.LoggingMiddleware,
                middlewares.UserContextMiddleware,
                middlewares.ThrottlingMiddleware,
            ):
                assert expected in classes, f"{expected.__name__} не подключён"

    def test_logging_wraps_throttling(self):
        """
        Порядок важен: логирование снаружи, иначе отброшенные антифлудом
        апдейты не попадут в лог и при разборе их будто бы не было.
        """
        import loader

        order = [type(mw).__name__ for mw in loader.dp.callback_query.middleware]

        assert order.index("LoggingMiddleware") < order.index("ThrottlingMiddleware")
        assert order.index("UserContextMiddleware") < order.index("ThrottlingMiddleware")
