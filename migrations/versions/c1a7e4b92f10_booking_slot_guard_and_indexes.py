"""A-4: защита от двойной брони + индексы + A-3.1 reviews_count

Частичный уникальный индекс по (stylist_id, datetime) действует только для активных
записей (pending/approved), поэтому отменённый или отклонённый слот можно занять снова.

SQLite и PostgreSQL поддерживают частичные индексы. MySQL — нет: там индекс не
создаётся, и единственной защитой остаётся повторная проверка слота в транзакции
плюс обработка IntegrityError в bot.finalize_booking.

Revision ID: c1a7e4b92f10
Revises: b8d3d117f0f2
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c1a7e4b92f10"
down_revision: str | Sequence[str] | None = "b8d3d117f0f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_STATUSES = "status IN ('pending', 'approved')"
SLOT_INDEX = "uq_active_booking_slot"


def _supports_partial_index(dialect: str) -> bool:
    return dialect in ("sqlite", "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    op.create_index("ix_bookings_stylist_datetime", "bookings", ["stylist_id", "datetime"])
    op.create_index("ix_bookings_user_datetime", "bookings", ["user_id", "datetime"])
    op.create_index("ix_bookings_status", "bookings", ["status"])
    op.create_index("ix_schedules_stylist_day", "schedules", ["stylist_id", "day_of_week"])

    if _supports_partial_index(dialect):
        # Перед созданием уникального индекса убираем возможные дубли,
        # оставляя самую раннюю активную запись на слот.
        bind.execute(
            sa.text(
                f"""
                UPDATE bookings SET status = 'declined'
                WHERE {ACTIVE_STATUSES}
                  AND id NOT IN (
                      SELECT MIN(id) FROM bookings
                      WHERE {ACTIVE_STATUSES}
                      GROUP BY stylist_id, datetime
                  )
                """
            )
        )
        op.create_index(
            SLOT_INDEX,
            "bookings",
            ["stylist_id", "datetime"],
            unique=True,
            sqlite_where=sa.text(ACTIVE_STATUSES),
            postgresql_where=sa.text(ACTIVE_STATUSES),
        )

    with op.batch_alter_table("stylists") as batch:
        batch.add_column(sa.Column("reviews_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    dialect = op.get_bind().dialect.name

    with op.batch_alter_table("stylists") as batch:
        batch.drop_column("reviews_count")

    if _supports_partial_index(dialect):
        op.drop_index(SLOT_INDEX, table_name="bookings")

    op.drop_index("ix_schedules_stylist_day", table_name="schedules")
    op.drop_index("ix_bookings_status", table_name="bookings")
    op.drop_index("ix_bookings_user_datetime", table_name="bookings")
    op.drop_index("ix_bookings_stylist_datetime", table_name="bookings")
