"""best efforts: the fastest stretch of each race distance a workout holds

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-23

One new table, additive, reading nothing and rewriting nothing. Every row in it
is derived from workout_samples, which is still there and still the source: this
is the same answer the insights band used to compute on every open, written down
once instead.

Empty after this runs. `manage.py backfill-best-efforts` fills it from the
per-minute rows already stored, and every workout imported afterwards fills its
own as its samples land. Until it is filled the band answers exactly as it did
before, because a missing row means "the samples could not answer" and the
reader falls back to the session's own average pace, which is what it always did
for a workout whose export carried no arrays.

Nothing earns from it. No medal, chest, level, plant or total reads this table,
and the two-lane law is untouched: these are seconds, read off minutes that were
already recorded, drawn on one screen.

Stepping back drops the table and the band recomputes from the samples again,
which is where it started.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workout_best_efforts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workout_id",
            sa.Integer(),
            sa.ForeignKey("workouts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tier", sa.String(length=16), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.UniqueConstraint("workout_id", "tier", name="uq_workout_best_effort"),
    )
    op.create_index(
        "ix_workout_best_efforts_workout_id", "workout_best_efforts", ["workout_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_workout_best_efforts_workout_id", table_name="workout_best_efforts")
    op.drop_table("workout_best_efforts")
