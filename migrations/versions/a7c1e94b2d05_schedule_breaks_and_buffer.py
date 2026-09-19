"""Перерыв в расписании и буфер между записями

Слоты шли вплотную: мастер физически не успевал убрать за клиентом и вымыть
инструмент, а обед приходилось закрывать особой датой на каждый день.

buffer_min — свойство мастера, а не услуги: время нужно человеку, а не стрижке.
0 сохраняет прежнее поведение, поэтому существующие мастера ничего не заметят.

break_start / break_end заполняются парой. Одна заполненная колонка из двух —
это перерыв без конца, и расчёт слотов такой день просто не отличит от рабочего;
проверка пары лежит в services/booking.py, а не в схеме, потому что MySQL
до 8.0.16 молча игнорирует CHECK.

Перерыв добавлен только в недельный шаблон. У особых дат его нет намеренно:
разовый день задаётся своими часами, и отдельный обед внутри него — колонки,
которые некому заполнять. Появится сценарий — появится и миграция.

Автогенерация здесь не использовалась: она предлагает удалить частичный индекс
uq_active_booking_slot, которого нет в моделях (см. 30e532c7a648).

Revision ID: a7c1e94b2d05
Revises: 30e532c7a648
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c1e94b2d05"
down_revision: str | Sequence[str] | None = "30e532c7a648"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    # batch_alter_table: SQLite не умеет ALTER TABLE ADD COLUMN с ограничениями
    # и пересоздаёт таблицу. На MySQL это обычный ALTER.
    with op.batch_alter_table("schedules") as batch:
        batch.add_column(sa.Column("break_start", sa.String(length=5), nullable=True))
        batch.add_column(sa.Column("break_end", sa.String(length=5), nullable=True))

    with op.batch_alter_table("stylists") as batch:
        # server_default обязателен: без него ALTER упадёт на непустой таблице,
        # а у нас в проде уже есть мастера.
        batch.add_column(
            sa.Column("buffer_min", sa.Integer(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("stylists") as batch:
        batch.drop_column("buffer_min")

    with op.batch_alter_table("schedules") as batch:
        batch.drop_column("break_end")
        batch.drop_column("break_start")
