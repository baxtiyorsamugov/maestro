"""B-2: Booking.datetime (строка) -> starts_at/ends_at (DateTime)

Строковое хранение "YYYY-MM-DD HH:MM" заставляло сравнивать время лексикографически,
выбирать записи за день через LIKE (индекс при этом не использовался) и парсить
строку в каждом месте кода.

ends_at считается как starts_at + длительность услуги. Отдельная колонка нужна,
чтобы проверять пересечения броней запросом, а не в памяти.

Бэкфилл идёт построчно на Python: формат даты в SQLite и MySQL разный, а строки
могли прийти битыми. Записи с неразбираемой датой не удаляются, а помечаются —
терять данные миграция не должна.

Revision ID: d4b6c0e83a17
Revises: c1a7e4b92f10
"""
from datetime import datetime, timedelta
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d4b6c0e83a17"
down_revision: str | Sequence[str] | None = "c1a7e4b92f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_STATUSES = "status IN ('pending', 'approved')"
SLOT_INDEX = "uq_active_booking_slot"
SLOT_FORMAT = "%Y-%m-%d %H:%M"
DEFAULT_DURATION_MIN = 60


def _supports_partial_index(dialect: str) -> bool:
    return dialect in ("sqlite", "postgresql")


def _parse(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in (SLOT_FORMAT, "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Индексы на старую колонку мешают её удалить.
    if _supports_partial_index(dialect):
        op.drop_index(SLOT_INDEX, table_name="bookings")
    op.drop_index("ix_bookings_stylist_datetime", table_name="bookings")
    op.drop_index("ix_bookings_user_datetime", table_name="bookings")

    op.add_column("bookings", sa.Column("starts_at", sa.DateTime(), nullable=True))
    op.add_column("bookings", sa.Column("ends_at", sa.DateTime(), nullable=True))

    rows = bind.execute(
        sa.text(
            """
            SELECT b.id, b.datetime, COALESCE(s.duration_min, :default_duration) AS duration_min
            FROM bookings b
            LEFT JOIN services s ON s.id = b.service_id
            """
        ),
        {"default_duration": DEFAULT_DURATION_MIN},
    ).fetchall()

    unparsed = []
    for row in rows:
        starts_at = _parse(row.datetime)
        if starts_at is None:
            unparsed.append(row.id)
            continue
        duration = row.duration_min or DEFAULT_DURATION_MIN
        bind.execute(
            sa.text("UPDATE bookings SET starts_at = :starts, ends_at = :ends WHERE id = :id"),
            {
                "starts": starts_at,
                "ends": starts_at + timedelta(minutes=duration),
                "id": row.id,
            },
        )

    if unparsed:
        # Дату восстановить нельзя, но и молча удалять запись нельзя.
        # Ставим эпоху и статус declined, чтобы такие строки не занимали слоты
        # и были видны при разборе.
        print(f"ВНИМАНИЕ: {len(unparsed)} записей с неразбираемой датой: {unparsed}")
        bind.execute(
            sa.text(
                """
                UPDATE bookings
                SET starts_at = :epoch, ends_at = :epoch, status = 'declined'
                WHERE starts_at IS NULL
                """
            ),
            {"epoch": datetime(1970, 1, 1)},
        )

    with op.batch_alter_table("bookings") as batch:
        batch.alter_column("starts_at", existing_type=sa.DateTime(), nullable=False)
        batch.alter_column("ends_at", existing_type=sa.DateTime(), nullable=False)
        batch.drop_column("datetime")

    op.create_index("ix_bookings_stylist_starts_at", "bookings", ["stylist_id", "starts_at"])
    op.create_index("ix_bookings_user_starts_at", "bookings", ["user_id", "starts_at"])

    if _supports_partial_index(dialect):
        op.create_index(
            SLOT_INDEX,
            "bookings",
            ["stylist_id", "starts_at"],
            unique=True,
            sqlite_where=sa.text(ACTIVE_STATUSES),
            postgresql_where=sa.text(ACTIVE_STATUSES),
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if _supports_partial_index(dialect):
        op.drop_index(SLOT_INDEX, table_name="bookings")
    op.drop_index("ix_bookings_user_starts_at", table_name="bookings")
    op.drop_index("ix_bookings_stylist_starts_at", table_name="bookings")

    op.add_column("bookings", sa.Column("datetime", sa.String(length=50), nullable=True))

    for row in bind.execute(sa.text("SELECT id, starts_at FROM bookings")).fetchall():
        starts_at = row.starts_at
        if isinstance(starts_at, str):
            starts_at = _parse(starts_at)
        bind.execute(
            sa.text("UPDATE bookings SET datetime = :value WHERE id = :id"),
            {"value": starts_at.strftime(SLOT_FORMAT) if starts_at else "", "id": row.id},
        )

    with op.batch_alter_table("bookings") as batch:
        batch.alter_column("datetime", existing_type=sa.String(length=50), nullable=False)
        batch.drop_column("ends_at")
        batch.drop_column("starts_at")

    op.create_index("ix_bookings_stylist_datetime", "bookings", ["stylist_id", "datetime"])
    op.create_index("ix_bookings_user_datetime", "bookings", ["user_id", "datetime"])

    if _supports_partial_index(dialect):
        op.create_index(
            SLOT_INDEX,
            "bookings",
            ["stylist_id", "datetime"],
            unique=True,
            sqlite_where=sa.text(ACTIVE_STATUSES),
            postgresql_where=sa.text(ACTIVE_STATUSES),
        )
