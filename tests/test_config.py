"""
Тесты конфигурации (docs/ROADMAP.md, Фаза 2).

Раньше пустое окружение выдавало по одной ошибке за запуск: поправил переменную,
перезапустил, узнал про следующую. Настройка нового сервера превращалась в цикл.
Теперь все претензии собираются разом.

Второе, чего не было вовсе, — проверка значений. Переменная с опечаткой
(токен без двоеточия, порт словом, короткий ключ сессии) молча доезжала до
Telegram, до драйвера базы или до Starlette и падала уже там, в чужом коде
и с чужим сообщением.

Важно: config.load_dotenv() отрабатывает при импорте модуля, поэтому переменные
здесь гасятся через monkeypatch.delenv уже ПОСЛЕ импорта. Иначе реальный .env
разработчика подменяет то, что проверяет тест, и тест зеленеет впустую.
"""
from pathlib import Path

import pytest

import config

ALL_VARS = (
    "BOT_TOKEN",
    "REDIS_URL",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "ADMIN_SECRET_KEY",
    "DATABASE_URL",
    "DB_DRIVER",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASS",
    "DB_NAME",
    "SQLITE_PATH",
    "WEBHOOK_URL",
    "WEBHOOK_PATH",
    "WEBHOOK_SECRET",
    "WEBHOOK_HOST",
    "WEBHOOK_PORT",
)

GOOD = {
    "BOT_TOKEN": "123456789:AAFakeTokenForTestsOnlyDoNotUseInProd",
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "secret",
    "ADMIN_SECRET_KEY": "x" * config.MIN_SECRET_KEY_LEN,
    "DB_DRIVER": "sqlite",
}


@pytest.fixture
def clean_env(monkeypatch):
    """Пустое окружение: ни одной переменной проекта."""
    for name in ALL_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def good_env(clean_env):
    for name, value in GOOD.items():
        clean_env.setenv(name, value)
    return clean_env


class TestEverythingAtOnce:
    def test_empty_environment_lists_every_missing_variable(self, clean_env):
        """
        Главное в этой задаче. По одной ошибке за запуск — это цикл
        «поправил — перезапустил — узнал про следующую».
        """
        problems = config.describe_problems()
        reported = " ".join(problems)

        for name in ("BOT_TOKEN", "ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_SECRET_KEY"):
            assert name in reported, f"{name} не упомянута в списке проблем"

    def test_good_environment_has_no_complaints(self, good_env):
        assert config.describe_problems() == []

    def test_strict_check_raises_with_all_problems_in_one_message(self, clean_env):
        with pytest.raises(config.ConfigError) as exc:
            config.check_environment()

        message = str(exc.value)
        assert "BOT_TOKEN" in message
        assert "ADMIN_SECRET_KEY" in message
        assert ".env.example" in message, "человеку нужно сказать, куда смотреть"

    def test_non_strict_check_returns_instead_of_raising(self, clean_env):
        problems = config.check_environment(strict=False)

        assert problems, "проблемы должны вернуться списком"

    def test_groups_are_independent(self, clean_env):
        """
        Админке не нужен BOT_TOKEN, а боту — пароль панели. Требовать их
        вместе значит запретить запускать половинки по отдельности.
        """
        clean_env.setenv("BOT_TOKEN", GOOD["BOT_TOKEN"])
        clean_env.setenv("DB_DRIVER", "sqlite")

        assert config.describe_problems(groups=("bot", "database")) == []
        assert config.describe_problems(groups=("admin",)) != []


class TestValueValidation:
    def test_token_without_colon_is_rejected(self, good_env):
        good_env.setenv("BOT_TOKEN", "maestro_bot")

        problems = " ".join(config.describe_problems(groups=("bot",)))

        assert "BOT_TOKEN" in problems

    def test_token_with_short_tail_is_rejected(self, good_env):
        good_env.setenv("BOT_TOKEN", "123456789:short")

        assert config.describe_problems(groups=("bot",)) != []

    def test_valid_token_passes(self, good_env):
        assert config.describe_problems(groups=("bot",)) == []

    def test_short_secret_key_is_rejected(self, good_env):
        good_env.setenv("ADMIN_SECRET_KEY", "x" * (config.MIN_SECRET_KEY_LEN - 1))

        problems = " ".join(config.describe_problems(groups=("admin",)))

        assert "ADMIN_SECRET_KEY" in problems

    def test_secret_key_at_the_boundary_passes(self, good_env):
        good_env.setenv("ADMIN_SECRET_KEY", "x" * config.MIN_SECRET_KEY_LEN)

        assert config.describe_problems(groups=("admin",)) == []

    def test_non_numeric_port_is_rejected(self, good_env):
        for name, value in (
            ("DB_DRIVER", "mysql"), ("DB_HOST", "localhost"), ("DB_USER", "maestro"),
            ("DB_NAME", "maestro"), ("DB_PORT", "три тысячи"),
        ):
            good_env.setenv(name, value)

        problems = " ".join(config.describe_problems(groups=("database",)))

        assert "DB_PORT" in problems

    def test_port_out_of_range_is_rejected(self, good_env):
        for name, value in (
            ("DB_DRIVER", "mysql"), ("DB_HOST", "localhost"), ("DB_USER", "maestro"),
            ("DB_NAME", "maestro"), ("DB_PORT", "70000"),
        ):
            good_env.setenv(name, value)

        assert config.describe_problems(groups=("database",)) != []

    def test_empty_string_counts_as_missing(self, good_env):
        """
        Закомментированная или обнулённая переменная (`ADMIN_PASSWORD=`) —
        это «не задано». Раньше она проходила проверку на наличие и падала
        уже при использовании.
        """
        good_env.setenv("ADMIN_PASSWORD", "")

        assert config.describe_problems(groups=("admin",)) != []


class TestDatabaseUrl:
    def test_sqlite_url_is_built(self, good_env):
        """Относительный путь достраивается до абсолютного от рабочего каталога."""
        good_env.setenv("SQLITE_PATH", "test_maestro.db")

        settings = config.load_database_settings()

        assert settings.url.startswith("sqlite+aiosqlite:///")
        assert "test_maestro.db" in settings.url
        assert Path(settings.name).is_absolute(), "относительный путь остался относительным"

    def test_explicit_database_url_wins(self, good_env):
        good_env.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")

        assert config.load_database_settings().url == "postgresql+asyncpg://u:p@h/db"

    def test_mysql_url_is_assembled_from_parts(self, good_env):
        for name, value in (
            ("DB_DRIVER", "mysql"), ("DB_HOST", "localhost"), ("DB_PORT", "3306"),
            ("DB_USER", "maestro"), ("DB_PASS", "pass"), ("DB_NAME", "maestro_db"),
        ):
            good_env.setenv(name, value)

        url = config.load_database_settings().url

        assert url == "mysql+aiomysql://maestro:pass@localhost:3306/maestro_db"

    def test_mysql_without_password_is_allowed(self, good_env):
        """Пустой DB_PASS — рабочий случай для локальной базы."""
        for name, value in (
            ("DB_DRIVER", "mysql"), ("DB_HOST", "localhost"), ("DB_PORT", "3306"),
            ("DB_USER", "root"), ("DB_NAME", "maestro_db"),
        ):
            good_env.setenv(name, value)

        assert config.load_database_settings().url.startswith("mysql+aiomysql://root:@")

    def test_password_does_not_leak_into_repr(self, good_env):
        """
        Настройки попадают в трейсбеки и логи. Пароль базы там быть не должен
        (CLAUDE.md, 4.4).
        """
        for name, value in (
            ("DB_DRIVER", "mysql"), ("DB_HOST", "localhost"), ("DB_PORT", "3306"),
            ("DB_USER", "maestro"), ("DB_PASS", "sup3rs3cret"), ("DB_NAME", "maestro_db"),
        ):
            good_env.setenv(name, value)

        assert "sup3rs3cret" not in repr(config.load_database_settings())


class TestLegacyHelpersStillWork:
    """
    get_required_env / get_optional_env остаются публичными: на них
    завязаны migrations/env.py и выбор пути к SQLite.
    """

    def test_required_raises_when_missing(self, clean_env):
        with pytest.raises(config.ConfigError):
            config.get_required_env("BOT_TOKEN")

    def test_required_strips_whitespace(self, clean_env):
        clean_env.setenv("BOT_TOKEN", "  value  ")

        assert config.get_required_env("BOT_TOKEN") == "value"

    def test_optional_returns_default(self, clean_env):
        assert config.get_optional_env("REDIS_URL", "fallback") == "fallback"

    def test_optional_treats_blank_as_missing(self, clean_env):
        clean_env.setenv("REDIS_URL", "   ")

        assert config.get_optional_env("REDIS_URL", "fallback") == "fallback"
