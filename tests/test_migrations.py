"""
Тесты миграций (docs/ROADMAP.md, Фаза 5).

Проверяем, что схема накатывается на пустую базу, откатывается до нуля и
накатывается снова — без этого любой откат на проде становится ручной операцией.
"""
import sqlite3
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    "barbershops",
    "bookings",
    "catalog_services",
    "favorites",
    "portfolios",
    "schedules",
    "services",
    "special_schedules",
    "stylists",
    "users",
}


@pytest.fixture
def scratch_db():
    path = Path(tempfile.mkdtemp()) / "migrations_test.db"
    yield path
    if path.exists():
        path.unlink()


def _config(db_path: Path) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    return cfg


def _objects(db_path: Path, kind: str) -> set[str]:
    # sqlite3-соединение нужно закрывать явно: контекстный менеджер только коммитит,
    # а на Windows незакрытый файл нельзя удалить.
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))
        return {r[0] for r in rows}
    finally:
        conn.close()


def _query_one(db_path: Path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_upgrade_creates_full_schema(scratch_db):
    command.upgrade(_config(scratch_db), "head")
    assert EXPECTED_TABLES <= _objects(scratch_db, "table")


def test_slot_guard_index_exists(scratch_db):
    command.upgrade(_config(scratch_db), "head")
    indexes = _objects(scratch_db, "index")
    assert "uq_active_booking_slot" in indexes, "защита от двойной брони не создана"
    assert "ix_bookings_stylist_datetime" in indexes
    assert "ix_schedules_stylist_day" in indexes


def test_slot_guard_is_partial(scratch_db):
    """Индекс должен покрывать только активные записи, иначе отменённый слот не переиспользовать."""
    command.upgrade(_config(scratch_db), "head")
    sql = _query_one(
        scratch_db, "SELECT sql FROM sqlite_master WHERE name = 'uq_active_booking_slot'"
    )[0]
    assert "WHERE" in sql.upper()
    assert "pending" in sql and "approved" in sql


def test_downgrade_and_upgrade_again(scratch_db):
    cfg = _config(scratch_db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    remaining = _objects(scratch_db, "table") - {"alembic_version"}
    assert remaining == set(), f"после отката остались таблицы: {remaining}"

    command.upgrade(cfg, "head")
    assert EXPECTED_TABLES <= _objects(scratch_db, "table")


def test_reviews_count_column_added(scratch_db):
    command.upgrade(_config(scratch_db), "head")
    assert "reviews_count" in _columns(scratch_db, "stylists")
