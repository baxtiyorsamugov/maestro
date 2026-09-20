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
    func,
)
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import load_database_settings

DATABASE_URL = load_database_settings().url


def _now() -> datetime.datetime:
    """
    Локальное время для значений по умолчанию.

    Импортировать timeutils здесь нельзя без риска цикла, а дублировать зону
    в двух местах — верный способ получить расхождение. Поэтому импорт ленивый.
    """
    import timeutils

    return timeutils.now()

engine = create_async_engine(DATABASE_URL, echo=False, pool_recycle=60)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class TimestampMixin:
    """
    Когда строка появилась и когда менялась в последний раз.

    Без этих полей невозможен ни разбор инцидента («когда запись стала
    отклонённой?»), ни аналитика («сколько времени мастер думает над заявкой»).
    Время локальное Asia/Tashkent, как и везде в проекте — см. timeutils.
    """

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, server_default=func.now()
    )


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

class User(Base, TimestampMixin):
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


class Barbershop(Base, TimestampMixin):
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


class Stylist(Base, TimestampMixin):
    __tablename__ = 'stylists'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    barbershop_id: Mapped[int] = mapped_column(ForeignKey("barbershops.id"))

    # Внешний ключ для прямой связи с User
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True, unique=True)

    avg_rating: Mapped[float] = mapped_column(Float, default=0.0)
    # Денормализация: число оценок нужно и в карточке, и в сортировке поиска.
    reviews_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Минуты между записями: убрать за клиентом, продезинфицировать инструмент,
    # выдохнуть. Свойство мастера, а не услуги: время нужно человеку, а не стрижке.
    # 0 — прежнее поведение, записи идут вплотную.
    buffer_min: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    # Карточка мастера: пара строк о себе и фото. До этого в карточке был
    # только адрес салона — выбрать по ней мастера было не по чему.
    # Отдельного флага «опубликован» нет намеренно: видимость уже определяет
    # подписка, и второй выключатель дал бы два источника правды.
    about: Mapped[str] = mapped_column(String(500), nullable=True)
    photo_file_id: Mapped[str] = mapped_column(String(255), nullable=True)

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
class Service(Base, TimestampMixin):
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


class Booking(Base, TimestampMixin):
    __tablename__ = 'bookings'

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL — запись, которую мастер завёл сам: офлайн-клиент, пришедший с улицы
    # или позвонивший. Аккаунта в Telegram у такого клиента нет, и заводить
    # ему фиктивного пользователя значит мусорить в таблице users.
    # Клиентские запросы идут через JOIN по user_id и такие записи не видят.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    stylist_id: Mapped[int] = mapped_column(ForeignKey("stylists.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))

    # Имя офлайн-клиента для памяти мастера. Пусто — просто занятое время.
    guest_name: Mapped[str] = mapped_column(String(100), nullable=True)

    # Наивное локальное время Asia/Tashkent — см. модуль timeutils, там же обоснование.
    # Раньше здесь была строка "2023-10-25 14:00": сравнения шли лексикографически,
    # выборки за день делались через LIKE и не могли использовать индекс.
    starts_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime.datetime] = mapped_column(DateTime)

    status: Mapped[str] = mapped_column(String(20), default=BOOKING_PENDING)

    rating: Mapped[int] = mapped_column(Integer, nullable=True)  # Оценка от 1 до 5
    review_text: Mapped[str] = mapped_column(String(500), nullable=True)  # Текст отзыва

    # Постмодерация: отзыв виден сразу, владелец сервиса может его скрыть.
    # Премодерация для сервиса с одним администратором означала бы, что отзывы
    # не появляются вообще — очередь некому разбирать.
    review_hidden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    
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
    # Обед. Заполнены обе колонки или ни одной: перерыв без конца — не перерыв.
    break_start: Mapped[str] = mapped_column(String(5), nullable=True)
    break_end: Mapped[str] = mapped_column(String(5), nullable=True)

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


#: Кто совершил действие. Строки, а не Enum: список пополняется чаще, чем
#: меняется схема, а миграция ради нового значения — лишний повод её не делать.
ACTOR_CLIENT = "client"
ACTOR_STYLIST = "stylist"
ACTOR_ADMIN = "admin"
ACTOR_SYSTEM = "system"


class AuditLog(Base):
    """
    Журнал действий над записями.

    Раньше на вопрос «кто отменил эту запись и когда» ответить было нечем:
    статус менялся, а следов не оставалось. Для сервиса, где клиент и мастер
    спорят о том, кто что отменил, это не мелочь.

    Строки только добавляются. Изменять и удалять их не должен никто —
    в админке представление открыто на чтение, а в коде нет ни одного места,
    которое правило бы существующую запись журнала.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=_now, server_default=func.now()
    )

    # Что произошло: "booking.approved", "review.hidden" и так далее.
    action: Mapped[str] = mapped_column(String(50))

    actor_kind: Mapped[str] = mapped_column(String(20))
    # Ссылка на пользователя, если действие совершил человек из бота.
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Подпись для тех, у кого нет строки в users: логин админки, "scheduler".
    actor_label: Mapped[str] = mapped_column(String(100), nullable=True)

    # Намеренно БЕЗ ForeignKey на bookings. Журнал обязан пережить то,
    # что он описывает: внешний ключ либо утащил бы запись журнала следом
    # за удалённой бронью, либо запретил бы удаление. Записи у нас и так
    # не удаляются, но журнал не должен зависеть от этого обещания.
    booking_id: Mapped[int] = mapped_column(Integer, nullable=True)

    # Человекочитаемая подробность: было -> стало, причина, старое время.
    details: Mapped[str] = mapped_column(String(500), nullable=True)

    actor = relationship("User", foreign_keys=[actor_user_id])

    __table_args__ = (
        Index("ix_audit_log_booking", "booking_id"),
        Index("ix_audit_log_created_at", "created_at"),
    )


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
