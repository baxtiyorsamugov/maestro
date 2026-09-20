"""Журнал действий над записями

На вопрос «кто отменил эту запись и когда» ответить было нечем: статус
менялся, а следов не оставалось. Для сервиса, где клиент и мастер спорят
о том, кто что отменил, это не мелочь, а отсутствие доказательства.

booking_id намеренно без внешнего ключа. Журнал обязан пережить то, что он
описывает: FK либо утащил бы запись журнала следом за удалённой бронью,
либо запретил бы удаление. Записи у нас и так не удаляются (отмена — это
смена статуса), но журнал не должен зависеть от этого обещания.

actor_user_id — ссылка на users для тех, кто действует из бота.
actor_label — подпись для тех, у кого строки в users нет: логин админки,
"scheduler" для фоновых задач.

Revision ID: d8f3a71c9b42
Revises: b5d29f13ac60
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8f3a71c9b42"
down_revision: str | Sequence[str] | None = "b5d29f13ac60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("actor_kind", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_label", sa.String(length=100), nullable=True),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Два запроса, ради которых журнал и заводится: «что было с этой записью»
    # и «что происходило в системе за период».
    op.create_index("ix_audit_log_booking", "audit_log", ["booking_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_booking", table_name="audit_log")
    op.drop_table("audit_log")
