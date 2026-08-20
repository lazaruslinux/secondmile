"""sample energy: the calories a minute burned

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-20

One nullable column on workout_samples, additive; nothing existing is read or
rewritten, and every row already in the table is carried by the null.

The export has always sent an activeEnergy array beside the distance, the steps
and the heart rate, and 0034 read the other three and left this one. The column
is what lets the details screen draw a calories lane over the minutes of a
session, which is the only thing that will ever read it.

Nothing derived reads it. The manna a workout is worth is converted from the
whole-session figure on the workout row and never from these, so the two-lane
law is untouched and stepping back loses only what a screen would have drawn.

Minutes already stored keep their null: the sync writes a workout's rows once
and never again, and manage.py backfill-samples skips a workout that already has
them. Rows written from here on carry the reading, which is honest rather than
complete, the same limit 0034 wrote down about its own four columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workout_samples", sa.Column("active_kcal", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("workout_samples", "active_kcal")
