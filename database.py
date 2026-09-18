# Файл: database.py
import asyncio
import datetime
from pathlib import Path

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import load_database_settings

DATABASE_URL = load_database_settings().url

engine = create_async_engine(DATABASE_URL, echo=False, pool_recycle=60)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


# --- Статусы записи ---
# Строковые литералы разъезжаются по коду и молча ломают выборки, поэтому
# имя статуса задаётся здесь в одном месте. Модули bot и scheduler берут их отсюда:
# импортировать из bot нельзя — bot сам импортирует scheduler.
BOOKING_PENDING = "pending"
BOOKING_APPROVED = "approved"
BOOKING_DECLINED = "declined"
BOOKING_COMPLETED = "completed"
BOOKING_CANCELLED = "cancelled"

# Статусы, занимающие слот в расписании. Должны совпадать с условием частичного
# индекса uq_active_booking_slot в миграции c1a7e4b92f10.
ACTIVE_BOOKING_STATUSES = (BOOKING_PENDING, BOOKING_APPROVED)


# --- Таблицы ---

class Favorite(Base):
    __tablename__ = 'favorites'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    stylist_id: Mapped[int] = mapped_column(ForeignKey("stylists.id"))

    # Гарантирует, что одна и та же пара (юзер, стилист) не может быть добавлена дважды
    __table_args__ = (UniqueConstraint('user_id', 'stylist_id', name='_user_stylist_uc'),)

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    first_name: Mapped[str] = mapped_column(String(50), nullable=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=True)
    language_code: Mapped[str] = mapped_column(String(2), nullable=True)
    role: Mapped[str] = mapped_column(String(10), default="client")
    subscription_until: Mapped[datetime.date] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- ИСПРАВЛЕНИЯ ЗДЕСЬ ---
    # Связь №1: Прямая, для определения, является ли этот User стилистом
    stylist_profile = relationship("Stylist", back_populates="user_account", uselist=False)

    # Связь №2: Через "Избранное", для получения списка любимых мастеров
    favorite_stylists = relationship("Stylist", secondary="favorites", back_populates="favorited_by_users")
    # --------------------------

    def __repr__(self):
        return f"{self.first_name}"


class Barbershop(Base):
    __tablename__ = 'barbershops'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    district: Mapped[str] = mapped_column(String(50))
    address: Mapped[str] = mapped_column(String(200))

    latitude: Mapped[float] = mapped_column(Float, nullable=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=True)

    stylists = relationship("Stylist", back_populates="barbershop")

    def __repr__(self):
        return self.name


class Stylist(Base):
    __tablename__ = 'stylists'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    barbershop_id: Mapped[int] = mapped_column(ForeignKey("barbershops.id"))

    # Внешний ключ для прямой связи с User
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True, unique=True)

    avg_rating: Mapped[float] = mapped_column(Float, default=0.0)
    # Денормализация: число оценок нужно и в карточке, и в сортировке поиска.
    reviews_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # --- ИСПРАВЛЕНИЯ ЗДЕСЬ ---
    # Связь №1: Обратная прямая связь с аккаунтом User
    user_account = relationship("User", back_populates="stylist_profile", foreign_keys=[user_id])

    # Связь №2: Обратная связь через "Избранное"
    favorited_by_users = relationship("User", secondary="favorites", back_populates="favorite_stylists")
    # --------------------------

    # Остальные связи не трогаем, они правильные
    barbershop = relationship("Barbershop", back_populates="stylists")
    services = relationship("Service", back_populates="stylist")

    def __repr__(self):
        return self.name

class CatalogService(Base):
    __tablename__ = 'catalog_services'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True) # Названия должны быть уникальными

    def __repr__(self):
        return self.name

# НОВАЯ ТАБЛИЦА: Услуги
class Service(Base):
    __tablename__ = 'services'
    id: Mapped[int] = mapped_column(primary_key=True)
    catalog_service_id: Mapped[int] = mapped_column(ForeignKey("catalog_services.id"))
    price: Mapped[float] = mapped_column(Float)  # Цена
    duration_min: Mapped[int] = mapped_column(Integer)  # Длительность в минутах
    stylist_id: Mapped[int] = mapped_column(ForeignKey("stylists.id"))
    stylist = relationship("Stylist", back_populates="services")
    catalog_service = relationship("CatalogService")

    def __repr__(self):
        return f"Service(price={self.price})"


class Booking(Base):
    __tablename__ = 'bookings'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    stylist_id: Mapped[int] = mapped_column(ForeignKey("stylists.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))

    # Наивное локальное время Asia/Tashkent — см. модуль timeutils, там же обоснование.
    # Раньше здесь была строка "2023-10-25 14:00": сравнения шли лексикографически,
    # выборки за день делались через LIKE и не могли использовать индекс.
    starts_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime.datetime] = mapped_column(DateTime)

    status: Mapped[str] = mapped_column(String(20), default=BOOKING_PENDING)

    rating: Mapped[int] = mapped_column(Integer, nullable=True)  # Оценка от 1 до 5
    review_text: Mapped[str] = mapped_column(String(500), nullable=True)  # Текст отзыва
    
    reminder_day_sent: Mapped[bool] = mapped_column(Boolean, default=False)   # За 24 часа
    reminder_hour_sent: Mapped[bool] = mapped_column(Boolean, default=False)  # За 1 час
    follow_up_sent: Mapped[bool] = mapped_column(Boolean, default=False)      # Через 20 дней

    # Связи (опционально, для удобства)
    user = relationship("User")
    stylist = relationship("Stylist")
    service = relationship("Service")

    # Индексы под самые частые запросы: расписание мастера на дату, записи клиента,
    # выборки по статусу в шедулере и на дашборде.
    __table_args__ = (
        Index("ix_bookings_stylist_starts_at", "stylist_id", "starts_at"),
        Index("ix_bookings_user_starts_at", "user_id", "starts_at"),
        Index("ix_bookings_status", "status"),
    )


# Таблица Расписания Мастеров
class Schedule(Base):
    __tablename__ = 'schedules'

    id: Mapped[int] = mapped_column(primary_key=True)
    stylist_id: Mapped[int] = mapped_column(ForeignKey("stylists.id"))
    # День недели: 1=Понедельник, 2=Вторник ... 7=Воскресенье
    day_of_week: Mapped[int] = mapped_column(Integer)
    # Время в формате "09:00"
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))

    stylist = relationship("Stylist")

    __table_args__ = (Index("ix_schedules_stylist_day", "stylist_id", "day_of_week"),)


class SpecialSchedule(Base):
    __tablename__ = 'special_schedules'

    id: Mapped[int] = mapped_column(primary_key=True)
    stylist_id: Mapped[int] = mapped_column(ForeignKey("stylists.id"))
    work_date: Mapped[datetime.date] = mapped_column(Date)
    start_time: Mapped[str] = mapped_column(String(5), nullable=True)
    end_time: Mapped[str] = mapped_column(String(5), nullable=True)
    is_day_off: Mapped[bool] = mapped_column(Boolean, default=False)

    stylist = relationship("Stylist")

    __table_args__ = (UniqueConstraint('stylist_id', 'work_date', name='_stylist_work_date_uc'),)


class Portfolio(Base):
    __tablename__ = 'portfolios'

    id: Mapped[int] = mapped_column(primary_key=True)
    stylist_id: Mapped[int] = mapped_column(ForeignKey("stylists.id"))

    # file_id - это уникальный идентификатор фото в Telegram.
    # Он очень длинный, поэтому String(255)
    telegram_photo_file_id: Mapped[str] = mapped_column(String(255))


def _run_alembic_upgrade() -> None:
    """Синхронный прогон миграций. Вызывается из потока, чтобы не блокировать loop."""
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(cfg, "head")


async def run_migrations() -> None:
    """
    Приводит схему к последней миграции. Источник правды по схеме — Alembic,
    а не create_all(): create_all не умеет добавлять колонки к существующим таблицам.
    """
    await asyncio.to_thread(_run_alembic_upgrade)


async def create_tables():
    """
    Устаревшее: оставлено для тестов и локальных скриптов.
    В приложении используйте run_migrations().
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
