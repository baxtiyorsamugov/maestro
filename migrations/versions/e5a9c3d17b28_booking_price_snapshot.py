"""Цена визита в самой записи: bookings.price

Раньше цена бралась из услуги на момент показа. Мастер поднял цену — и вся
прошлая выручка в статистике пересчиталась по новой, а клиент в «Моих
записях» видел за прошлый визит сумму, которую не платил.

Теперь цена фиксируется при создании записи. Перенос времени её не меняет:
это та же запись на ту же услугу.

Существующие записи заполняются текущей ценой услуги — точнее для прошлого
восстановить нечем, истории цен в базе нет. Колонка допускает NULL: запись,
услугу которой потом удалили, цены не получит, и читающий код падает
обратно на цену услуги (services.stats, presenters).

Integer, а не Float, как у services.price: сумма в сумах без дробной части,
а сложение Float на выручке за месяц даёт копеечные хвосты.

Revision ID: e5a9c3d17b28
Revises: d8f3a71c9b42
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5a9c3d17b28"
down_revision: str | Sequence[str] | None = "d8f3a71c9b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("bookings") as batch:
        batch.add_column(sa.Column("price", sa.Integer(), nullable=True))

    # Коррелированный подзапрос работает и в SQLite, и в PostgreSQL.
    # CAST явный: services.price — Float, а PostgreSQL не приводит
    # double precision к integer в подзапросе без указания.
    op.execute(
        "UPDATE bookings SET price = ("
        "  SELECT CAST(ROUND(services.price) AS INTEGER) FROM services"
        "  WHERE services.id = bookings.service_id"
        ") WHERE price IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("bookings") as batch:
        batch.drop_column("price")
