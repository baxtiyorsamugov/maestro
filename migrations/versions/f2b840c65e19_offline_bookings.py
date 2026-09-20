"""Записи офлайн-клиентов: bookings.user_id становится необязательным

Клиент, пришедший с улицы или позвонивший, существовал только в голове мастера:
занять его время в боте было нечем, и слот продолжали предлагать другим.

Аккаунта в Telegram у такого клиента нет. Заводить ему фиктивного User значит
мусорить в таблице, по которой считаются клиенты сервиса, поэтому user_id
становится NULL, а имя (если мастер его ввёл) живёт в guest_name.

Клиентские выборки ходят через JOIN по user_id и такие записи просто не видят —
менять их не понадобилось. Частичный уникальный индекс uq_active_booking_slot
работает по stylist_id и starts_at, поэтому двойную бронь он ловит и здесь.

ВНИМАНИЕ к downgrade: вернуть NOT NULL на колонку с NULL нельзя, поэтому
офлайн-записи перед этим удаляются. Представить их в старой схеме нечем —
это осознанная потеря, а не недосмотр. На проде перед откатом стоит снять дамп.

Revision ID: f2b840c65e19
Revises: a7c1e94b2d05
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2b840c65e19"
down_revision: str | Sequence[str] | None = "a7c1e94b2d05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("bookings") as batch:
        batch.add_column(sa.Column("guest_name", sa.String(length=100), nullable=True))
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Записи без клиента в старой схеме не представимы: NOT NULL их не примет.
    op.execute(sa.text("DELETE FROM bookings WHERE user_id IS NULL"))

    with op.batch_alter_table("bookings") as batch:
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("guest_name")
