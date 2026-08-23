"""pr stamps: where each workout stood in its own history when it arrived

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-23

One new table, additive, reading nothing and rewriting nothing. A row says that
a workout was this account's best, second best or third best at a race distance
in its own sport at the moment it was imported, and it is never written twice.

Empty after this runs, and a card with no row simply says nothing extra, which
is what every card says today. `manage.py backfill-pr-stamps` fills it by
replaying an account's history oldest first, so an old card gets the standing it
held then rather than the one it would hold now.

Nothing earns from it. No medal, chest, level, plant or total reads this table,
and the two-lane law is untouched: a standing is a reading of rows that were
already there, drawn on a card.

Stepping back drops the table and the cards go quiet again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workout_pr_stamps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workout_id",
            sa.Integer(),
            sa.ForeignKey("workouts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tier", sa.String(length=16), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.UniqueConstraint("workout_id", "tier", name="uq_workout_pr_stamp"),
    )
    op.create_index("ix_workout_pr_stamps_workout_id", "workout_pr_stamps", ["workout_id"])


def downgrade() -> None:
    op.drop_index("ix_workout_pr_stamps_workout_id", table_name="workout_pr_stamps")
    op.drop_table("workout_pr_stamps")
