"""Карточка мастера: описание и фото

До этого в карточке были только имя, рейтинг и адрес салона. Выбирать мастера
было не по чему: все карточки выглядели одинаково, и человек жал «Записаться»
у первого попавшегося или уходил.

about — пара строк от самого мастера. photo_file_id — file_id из Telegram,
а не файл: перезаливать своё же фото на каждый показ карточки незачем,
а file_id живёт, пока жив бот.

Флага «опубликован» здесь нет намеренно. Видимость мастера уже определяет
подписка (users.subscription_until); второй выключатель дал бы два источника
правды, и однажды они разойдутся.

Revision ID: b5d29f13ac60
Revises: c3e71a5d9084
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5d29f13ac60"
down_revision: str | Sequence[str] | None = "c3e71a5d9084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("stylists") as batch:
        batch.add_column(sa.Column("about", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("photo_file_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("stylists") as batch:
        batch.drop_column("photo_file_id")
        batch.drop_column("about")
