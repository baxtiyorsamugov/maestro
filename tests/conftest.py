"""
Общая настройка тестов.

Переменные окружения выставляются ДО импорта проекта: database.py создаёт engine
на уровне модуля, поэтому путь к тестовой базе должен быть известен заранее.

Схема поднимается Alembic-миграциями, а не create_all(): часть объектов
(частичный уникальный индекс uq_active_booking_slot) существует только в миграции,
и тесты должны проверять ровно то, что поедет на прод.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TEST_DB = Path(tempfile.gettempdir()) / "maestro_test.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()

os.environ["BOT_TOKEN"] = "123456789:AAFakeTokenForTestsOnlyDoNotUseInProd"
os.environ["DB_DRIVER"] = "sqlite"
os.environ["SQLITE_PATH"] = str(_TEST_DB)
os.environ["ADMIN_USERNAME"] = "test"
os.environ["ADMIN_PASSWORD"] = "test"
os.environ["ADMIN_SECRET_KEY"] = "test-secret-key-for-tests-only-32ch"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import delete  # noqa: E402

import database as db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_schema():
    """Один прогон миграций на всю сессию тестов."""
    db._run_alembic_upgrade()
    yield


@pytest_asyncio.fixture
async def session(migrated_schema):
    """Чистые таблицы на каждый тест — схему при этом не пересоздаём."""
    async with db.async_session() as s:
        for table in reversed(db.Base.metadata.sorted_tables):
            await s.execute(delete(table))
        await s.commit()
        yield s


@pytest_asyncio.fixture
async def fixture_data(session):
    """
    Минимальный набор: барбершоп, мастер с аккаунтом, клиент, посторонний пользователь
    и одна заявка в статусе pending.
    """
    shop = db.Barbershop(name="Test Shop", district="Chilanzar", address="Test 1")
    session.add(shop)
    await session.flush()

    stylist_user = db.User(telegram_id=1001, first_name="Мастер", role="stylist", is_active=True)
    client_user = db.User(telegram_id=2002, first_name="Клиент", phone_number="+998901234567")
    intruder = db.User(telegram_id=3003, first_name="Посторонний")
    session.add_all([stylist_user, client_user, intruder])
    await session.flush()

    stylist = db.Stylist(name="Мастер", barbershop_id=shop.id, user_id=stylist_user.id)
    catalog = db.CatalogService(name="Стрижка")
    session.add_all([stylist, catalog])
    await session.flush()

    service = db.Service(catalog_service_id=catalog.id, price=100000, duration_min=60, stylist_id=stylist.id)
    session.add(service)
    await session.flush()

    booking = db.Booking(
        user_id=client_user.id,
        stylist_id=stylist.id,
        service_id=service.id,
        datetime="2099-01-01 12:00",
        status="pending",
    )
    session.add(booking)
    await session.commit()

    return {
        "session": session,
        "stylist": stylist,
        "stylist_user": stylist_user,
        "client_user": client_user,
        "intruder": intruder,
        "booking": booking,
        "service": service,
    }
