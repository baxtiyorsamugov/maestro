import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


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


@dataclass(frozen=True)
class DatabaseSettings:
    url_value: str
    host: str
    port: str
    user: str
    password: str
    name: str

    @property
    def url(self) -> str:
        return self.url_value


@dataclass(frozen=True)
class AdminSettings:
    username: str
    password: str
    secret_key: str


def _sqlite_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        local_app_data = os.getenv("LOCALAPPDATA")
        base_dir = Path(local_app_data) / "Maestro" if local_app_data else Path.home() / "AppData" / "Local" / "Maestro"
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir
    return Path.cwd()


def load_database_settings() -> DatabaseSettings:
    explicit_url = get_optional_env("DATABASE_URL")
    if explicit_url:
        return DatabaseSettings(
            url_value=explicit_url,
            host="",
            port="",
            user="",
            password="",
            name="",
        )

    driver = (get_optional_env("DB_DRIVER", "sqlite") or "sqlite").lower()
    if driver == "sqlite":
        base_dir = _sqlite_base_dir()
        db_path = get_optional_env("SQLITE_PATH")
        if not db_path:
            db_path = "maestro.db"
        db_path_obj = Path(db_path)
        if not db_path_obj.is_absolute():
            db_path_obj = base_dir / db_path_obj
        return DatabaseSettings(
            url_value=f"sqlite+aiosqlite:///{db_path_obj.as_posix()}",
            host="",
            port="",
            user="",
            password="",
            name=str(db_path_obj),
        )

    return DatabaseSettings(
        url_value=(
            f"mysql+aiomysql://{get_required_env('DB_USER')}:"
            f"{get_optional_env('DB_PASS', '') or ''}@"
            f"{get_required_env('DB_HOST')}:{get_required_env('DB_PORT')}/"
            f"{get_required_env('DB_NAME')}"
        ),
        host=get_required_env("DB_HOST"),
        port=get_required_env("DB_PORT"),
        user=get_required_env("DB_USER"),
        password=get_optional_env("DB_PASS", "") or "",
        name=get_required_env("DB_NAME"),
    )


def load_admin_settings() -> AdminSettings:
    return AdminSettings(
        username=get_required_env("ADMIN_USERNAME"),
        password=get_required_env("ADMIN_PASSWORD"),
        secret_key=get_required_env("ADMIN_SECRET_KEY"),
    )
