"""
Конфигурация из окружения.

Настройки описаны моделями pydantic-settings, а не набором os.getenv по коду.
Разница не косметическая: раньше пустой `.env` выдавал по одной ошибке за запуск —
исправил переменную, перезапустил, узнал про следующую. Теперь `describe_problems()`
собирает все претензии разом и печатает их списком.

Проверяются не только наличие, но и значения: порт должен быть числом, секретный
ключ сессии — достаточно длинным, токен бота — похожим на токен. Переменная,
заданная с опечаткой, до этого молча доезжала до Telegram и падала там.

Публичные функции (`load_database_settings`, `load_admin_settings`,
`get_required_env`, `get_optional_env`) сохранены: их зовут database.py, loader.py,
admin_panel.py и migrations/env.py.
"""
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

#: Минимальная длина ключа подписи сессий админки. Короткий ключ подбирается,
#: а Starlette его молча примет — проверять приходится самим.
MIN_SECRET_KEY_LEN = 32


class ConfigError(RuntimeError):
    pass


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise ConfigError(f"Missing required environment variable: {name}")
    return value.strip()


def get_optional_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


class _Base(BaseSettings):
    model_config = SettingsConfigDict(
        # Пустая строка в .env — это «не задано», а не «задано пустым».
        # Иначе закомментированная переменная вида `DB_PASS=` проходила бы
        # проверку на наличие и падала уже при подключении.
        env_ignore_empty=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


class BotSettings(_Base):
    """Токен бота и хранилище FSM."""

    token: str = Field(alias="BOT_TOKEN")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")

    @field_validator("token")
    @classmethod
    def token_looks_like_token(cls, value: str) -> str:
        """
        Токен Telegram — это «<цифры>:<буквы и цифры>». Полную проверку
        сделать нельзя, но опечатка вроде вставленного имени бота отсекается
        здесь, а не через отказ Telegram при первом же запросе.
        """
        head, _, tail = value.partition(":")
        if not (head.isdigit() and len(tail) >= 20):
            raise ValueError(
                "BOT_TOKEN не похож на токен Telegram (ожидается «123456789:AA...»)"
            )
        return value


#: Допустимые символы секрета вебхука — ограничение самого Telegram.
WEBHOOK_SECRET_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)
MIN_WEBHOOK_SECRET_LEN = 32


class WebhookSettings(_Base):
    """
    Режим приёма апдейтов. Без WEBHOOK_URL бот работает поллингом.

    Поллинг удобен локально, но на проде это постоянное соединение к Telegram
    и ровно один процесс на токен. Вебхук принимает апдейты через nginx
    по HTTPS и переживает рестарт без потери нажатий: Telegram держит
    недоставленные апдейты у себя и повторяет их.
    """

    url: str | None = Field(default=None, alias="WEBHOOK_URL")
    path: str = Field(default="/telegram/webhook", alias="WEBHOOK_PATH")
    secret: str | None = Field(default=None, alias="WEBHOOK_SECRET")
    host: str = Field(default="127.0.0.1", alias="WEBHOOK_HOST")
    port: int = Field(default=8081, alias="WEBHOOK_PORT")

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    @property
    def full_url(self) -> str:
        return self.url.rstrip("/") + self.path

    @field_validator("url")
    @classmethod
    def url_is_https(cls, value: str | None) -> str | None:
        # Telegram на http вебхук не поставит; лучше узнать это на старте.
        if value is not None and not value.startswith("https://"):
            raise ValueError("WEBHOOK_URL должен начинаться с https://")
        return value

    @field_validator("path")
    @classmethod
    def path_is_absolute(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("WEBHOOK_PATH должен начинаться с «/»")
        return value

    @field_validator("secret")
    @classmethod
    def secret_is_usable(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not set(value) <= WEBHOOK_SECRET_ALPHABET or len(value) > 256:
            raise ValueError("WEBHOOK_SECRET: только A-Z, a-z, 0-9, «_» и «-», до 256 символов")
        if len(value) < MIN_WEBHOOK_SECRET_LEN:
            raise ValueError(f"WEBHOOK_SECRET короче {MIN_WEBHOOK_SECRET_LEN} символов")
        return value

    @model_validator(mode="after")
    def secret_required_with_url(self) -> "WebhookSettings":
        # Без секрета любой, кто узнал адрес, шлёт боту поддельные апдейты
        # от имени любого пользователя — в том числе «подтвердить запись».
        if self.enabled and not self.secret:
            raise ValueError("WEBHOOK_SECRET обязателен, когда задан WEBHOOK_URL")
        return self


class SentrySettings(_Base):
    """
    Отправка ошибок наружу. Всё необязательно: без DSN Sentry не включается.

    Отдельная группа, а не поля в BotSettings: наблюдаемость нужна обеим
    половинам, и требовать её нельзя — локальная разработка идёт без неё.
    """

    dsn: str | None = Field(default=None, alias="SENTRY_DSN")
    environment: str = Field(default="production", alias="SENTRY_ENVIRONMENT")


class AdminSettings(_Base):
    """
    Учётные данные веб-панели.

    Вторая пара (MANAGER) необязательна. Она даёт вход с ограниченными правами:
    смотреть всё, менять только записи. Нужна, чтобы администратор на ресепшене
    мог разбирать заявки, не имея доступа к тарифам и учётным записям.

    Учётные записи заданы окружением, а не таблицей в базе. Для сервиса
    с одним владельцем и одним помощником это соразмерно: таблица потребовала
    бы миграции, UI управления пользователями и восстановления пароля —
    ради двух строк. Цена решения известна: третий человек требует правки
    `.env` и перезапуска.
    """

    username: str = Field(alias="ADMIN_USERNAME")
    password: str = Field(alias="ADMIN_PASSWORD")
    secret_key: str = Field(alias="ADMIN_SECRET_KEY")
    manager_username: str | None = Field(default=None, alias="ADMIN_MANAGER_USERNAME")
    manager_password: str | None = Field(default=None, alias="ADMIN_MANAGER_PASSWORD")

    @field_validator("secret_key")
    @classmethod
    def secret_key_is_long_enough(cls, value: str) -> str:
        if len(value) < MIN_SECRET_KEY_LEN:
            raise ValueError(
                f"ADMIN_SECRET_KEY короче {MIN_SECRET_KEY_LEN} символов — "
                "сгенерируйте новый: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        return value


#: Серверные драйверы: имя из DB_DRIVER -> префикс DSN для SQLAlchemy.
#:
#: PostgreSQL — основной для прода. Причина не в моде: частичный уникальный
#: индекс uq_active_booking_slot, единственная настоящая защита от двойной
#: брони, работает на SQLite и PostgreSQL и не работает на MySQL. На MySQL
#: защитой остаётся только перепроверка в транзакции (docs/SECURITY.md, S-6).
SERVER_DRIVERS = {
    "postgres": "postgresql+asyncpg",
    "postgresql": "postgresql+asyncpg",
    "mysql": "mysql+aiomysql",
}


class ServerDatabaseSettings(_Base):
    """Параметры серверной базы. Читаются, только когда драйвер не sqlite."""

    host: str = Field(alias="DB_HOST")
    port: int = Field(alias="DB_PORT")
    user: str = Field(alias="DB_USER")
    password: str = Field(default="", alias="DB_PASS")
    name: str = Field(alias="DB_NAME")

    @field_validator("port")
    @classmethod
    def port_is_a_real_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("DB_PORT вне диапазона 1..65535")
        return value


class DatabaseSettings:
    """
    Готовый DSN плюс разобранные части.

    Не модель pydantic: собирается из разных источников (DATABASE_URL целиком,
    SQLite с вычисляемым путём или MySQL по частям), и описать это одной
    моделью получилось бы менее понятно, чем тремя ветками ниже.
    """

    __slots__ = ("host", "name", "password", "port", "url_value", "user")

    def __init__(self, url_value: str, host: str = "", port: str = "",
                 user: str = "", password: str = "", name: str = ""):
        self.url_value = url_value
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.name = name

    @property
    def url(self) -> str:
        return self.url_value

    def __repr__(self) -> str:
        # Пароль в repr не попадает: настройки светятся в трейсбеках и логах.
        return f"DatabaseSettings(name={self.name!r}, host={self.host!r})"


def _sqlite_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        local_app_data = os.getenv("LOCALAPPDATA")
        base_dir = Path(local_app_data) / "Maestro" if local_app_data else Path.home() / "AppData" / "Local" / "Maestro"
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir
    return Path.cwd()


def _sqlite_settings() -> DatabaseSettings:
    base_dir = _sqlite_base_dir()
    db_path_obj = Path(get_optional_env("SQLITE_PATH") or "maestro.db")
    if not db_path_obj.is_absolute():
        db_path_obj = base_dir / db_path_obj
    return DatabaseSettings(
        url_value=f"sqlite+aiosqlite:///{db_path_obj.as_posix()}",
        name=str(db_path_obj),
    )


def load_database_settings() -> DatabaseSettings:
    explicit_url = get_optional_env("DATABASE_URL")
    if explicit_url:
        return DatabaseSettings(url_value=explicit_url)

    driver = (get_optional_env("DB_DRIVER", "sqlite") or "sqlite").lower()
    if driver == "sqlite":
        return _sqlite_settings()

    prefix = SERVER_DRIVERS.get(driver)
    if not prefix:
        known = ", ".join(["sqlite", *SERVER_DRIVERS])
        raise ConfigError(f"DB_DRIVER={driver!r} не поддерживается. Доступны: {known}")

    server = ServerDatabaseSettings()
    return DatabaseSettings(
        url_value=(
            f"{prefix}://{server.user}:{quote_plus(server.password)}@"
            f"{server.host}:{server.port}/{server.name}"
        ),
        host=server.host,
        port=str(server.port),
        user=server.user,
        password=server.password,
        name=server.name,
    )


def load_admin_settings() -> AdminSettings:
    return AdminSettings()


def load_bot_settings() -> BotSettings:
    return BotSettings()


def load_sentry_settings() -> SentrySettings:
    return SentrySettings()


def load_webhook_settings() -> WebhookSettings:
    return WebhookSettings()


def _problems_of(loader) -> list[str]:
    """Читаемые строки об ошибках одной группы настроек."""
    try:
        loader()
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            # alias — это имя переменной окружения; именно его человек и правит.
            name = str(error["loc"][0]) if error["loc"] else ""
            message = error["msg"].removeprefix("Value error, ")
            if error["type"] == "missing":
                message = "не задана"
            # У проверки всей группы (model_validator) нет одной переменной:
            # имя уже в самом сообщении.
            problems.append(f"  {name}: {message}" if error["loc"] else f"  {message}")
        return problems
    except ConfigError as exc:
        return [f"  {exc}"]
    return []


#: Группы настроек. Разделены не для красоты: админке не нужен BOT_TOKEN,
#: а боту — пароль веб-панели, и требовать их вместе значит мешать запускать
#: половинки по отдельности (`python admin_panel.py`).
SETTING_GROUPS = {
    "bot": load_bot_settings,
    "admin": load_admin_settings,
    "database": load_database_settings,
    "webhook": load_webhook_settings,
}
ALL_GROUPS = tuple(SETTING_GROUPS)


def describe_problems(groups: tuple[str, ...] = ALL_GROUPS) -> list[str]:
    """
    Все претензии к окружению разом.

    Именно «разом» здесь главное: по одной ошибке за запуск настройка нового
    сервера превращалась в цикл «поправил — перезапустил — узнал про следующую».
    """
    problems = []
    for group in groups:
        problems.extend(_problems_of(SETTING_GROUPS[group]))
    return problems


def check_environment(groups: tuple[str, ...] = ALL_GROUPS, strict: bool = True) -> list[str]:
    """
    Проверка окружения на старте. Зовётся из loader.py и admin_panel.py.

    strict=False нужен утилитам, которым хватает части переменных:
    им полезно увидеть список проблем, но падать из-за него незачем.
    """
    problems = describe_problems(groups)
    if problems and strict:
        raise ConfigError(
            "Окружение настроено не полностью:\n"
            + "\n".join(problems)
            + "\n\nЗаполните .env — образец лежит в .env.example."
        )
    return problems
