"""created_at / updated_at во всех основных таблицах

Без этих полей невозможен ни разбор инцидента («когда запись стала отклонённой?»),
ни аналитика («сколько времени мастер думает над заявкой»).

ВАЖНО: автогенерация предлагала удалить индекс uq_active_booking_slot — он не описан
в моделях, потому что частичные индексы задаются только в миграции, и Alembic считает
его лишним. Удаление снесло бы защиту от двойной брони. Этот шаг убран вручную;
при следующих автогенерациях его нужно убирать снова.

server_default стоит для того, чтобы ALTER прошёл на непустых таблицах. На SQLite
CURRENT_TIMESTAMP возвращает UTC, поэтому существующие строки дозаполняются
отдельным запросом с локальным временем — иначе история уехала бы на 5 часов.

Revision ID: 30e532c7a648
Revises: d4b6c0e83a17
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "30e532c7a648"
down_revision: str | Sequence[str] | None = "d4b6c0e83a17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("users", "barbershops", "stylists", "services", "bookings")


def _local_now() -> str:
    """Локальное время Asia/Tashkent тем же способом, что и в приложении."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import timeutils

    return timeutils.now().strftime("%Y-%m-%d %H:%M:%S")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "created_at",
                    sa.DateTime(),
                    server_default=sa.text("(CURRENT_TIMESTAMP)"),
                    nullable=False,
                )
            )
            batch.add_column(
                sa.Column(
                    "updated_at",
                    sa.DateTime(),
                    server_default=sa.text("(CURRENT_TIMESTAMP)"),
                    nullable=False,
                )
            )

    # Существующие строки получили UTC от CURRENT_TIMESTAMP — приводим к локальному.
    now = _local_now()
    bind = op.get_bind()
    for table in TABLES:
        bind.execute(
            sa.text(f"UPDATE {table} SET created_at = :now, updated_at = :now"),
            {"now": now},
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("updated_at")
            batch.drop_column("created_at")
