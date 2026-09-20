"""Скрытие отзыва модератором: bookings.review_hidden

Колонка review_text существовала с самого начала, но UI под неё не было:
клиент ставил звёзды вслепую, а новый человек видел в карточке мастера
только цифру без единого слова.

Модерация постфактум, а не до публикации. Премодерация в сервисе с одним
администратором означает, что отзывы не появляются вообще: очередь некому
разбирать, и функция умирает тихо. Поэтому отзыв виден сразу, а владелец
может его скрыть — и это видно в админке отдельным списком.

Флаг, а не удаление текста: разбирать жалобу «почему скрыли мой отзыв»
по пустой колонке невозможно.

Revision ID: c3e71a5d9084
Revises: f2b840c65e19
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3e71a5d9084"
down_revision: str | Sequence[str] | None = "f2b840c65e19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("bookings") as batch:
        # server_default обязателен: ALTER идёт по непустой таблице.
        batch.add_column(
            sa.Column(
                "review_hidden",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("bookings") as batch:
        batch.drop_column("review_hidden")
