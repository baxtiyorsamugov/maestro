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

os.environ["BOT_TOKEN"] = "123456789:AAFakeTokenForTestsOnlyDoNotUseInProd"
os.environ["ADMIN_USERNAME"] = "test"
os.environ["ADMIN_PASSWORD"] = "test"
os.environ["ADMIN_SECRET_KEY"] = "test-secret-key-for-tests-only-32ch"

# По умолчанию — временная SQLite: быстро и без внешних зависимостей.
#
# TEST_DATABASE_URL переводит весь набор на другую базу. Это не удобство,
# а необходимость: compose объявляет PostgreSQL основной базой, и поддержка,
# которую никто не прогоняет, протухает молча. Уже поймали так одну миграцию,
# которая на PostgreSQL не накатывалась вовсе.
#
#   docker run -d --name pg -e POSTGRES_PASSWORD=pass -p 5432:5432 postgres:16-alpine
#   TEST_DATABASE_URL=postgresql+asyncpg://postgres:pass@127.0.0.1:5432/postgres pytest tests/ -q
_EXTERNAL_DB = os.getenv("TEST_DATABASE_URL")
if _EXTERNAL_DB:
    os.environ["DATABASE_URL"] = _EXTERNAL_DB
    os.environ.pop("DB_DRIVER", None)
    os.environ.pop("SQLITE_PATH", None)
else:
    _TEST_DB = Path(tempfile.gettempdir()) / "maestro_test.db"
    if _TEST_DB.exists():
        _TEST_DB.unlink()
    os.environ.pop("DATABASE_URL", None)
    os.environ["DB_DRIVER"] = "sqlite"
    os.environ["SQLITE_PATH"] = str(_TEST_DB)

from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import delete  # noqa: E402

import database as db  # noqa: E402
import timeutils  # noqa: E402

if _EXTERNAL_DB:
    # asyncpg привязывает соединение к циклу событий, в котором оно открыто,
    # а pytest-asyncio заводит новый цикл на каждый тест. Пул, переживший
    # предыдущий тест, отдаёт соединение от закрытого цикла — и весь набор
    # рассыпается на «RuntimeError: Event loop is closed».
    #
    # NullPool закрывает соединение сразу после использования: в тестах это
    # медленнее, но здесь важна не скорость, а совпадение с боевым поведением.
    # На боевом движке пул остаётся: там цикл событий один на весь процесс.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    db.engine = create_async_engine(_EXTERNAL_DB, echo=False, poolclass=NullPool)
    db.async_session = async_sessionmaker(db.engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def migrated_schema():
    """
    Один прогон миграций на всю сессию тестов.

    На внешней базе сначала сносим схему: она могла остаться от прошлого
    прогона, и миграции упали бы на уже существующих таблицах.
    """
    if _EXTERNAL_DB:
        # Чистим тем же драйвером, которым работает приложение: тянуть ради
        # одного DROP SCHEMA синхронный psycopg2 значит держать в зависимостях
        # второй драйвер к той же базе.
        import asyncio

        import sqlalchemy as sa

        async def _wipe():
            async with db.engine.begin() as conn:
                if db.engine.dialect.name == "postgresql":
                    # Двумя вызовами, а не одной строкой через «;»: asyncpg
                    # готовит запрос к исполнению и на нескольких командах
                    # в одном statement падает.
                    await conn.execute(sa.text("DROP SCHEMA public CASCADE"))
                    await conn.execute(sa.text("CREATE SCHEMA public"))

        asyncio.run(_wipe())

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

    starts_at = timeutils.parse_slot("2099-01-01 12:00")
    booking = db.Booking(
        user_id=client_user.id,
        stylist_id=stylist.id,
        service_id=service.id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=service.duration_min),
        status=db.BOOKING_PENDING,
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
