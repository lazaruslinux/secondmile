"""steps: what a pedometer covered, and what it earns

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-12

Three new tables and one column that learns to be null.

daily_steps is one row per account per local day: what the phone claimed, and
how much of it has been credited. Both readings are high-water and so is the
credit, because an export covers a window rather than a finished day and the
same day arrives again and again; a partial reading must never take a fuller
one back down, and credit already spent must never be withdrawn. The unique
pair on (user_id, day) is what makes the upsert an upsert.

step_credits is the ledger beside it: one row for every time a day's credit
went up, for the amount it went up by. The sum of a day's rows is that day's
credited_mi, which is an invariant a test pins rather than a constraint the
database can express. It exists because a total answers "how much" and only a
ledger answers "how much since Tuesday", which is the question the letter asks.

processed_step_credits is the same idempotency spine processed_workouts is, one
table over: the marker is written before the credit it stands for, and the
primary key settles which of two concurrent syncs owns the row.

The column is weekly_badge_earns.workout_id, which becomes nullable. A week is
a total, steps are miles, and so a week can now be carried over a medal line by
the leftover steps of a day rather than by a session: that crossing has no
workout to point at, and null is the honest way to say so. Every row already in
the table has a workout and keeps it. SQLite has no ALTER COLUMN, so the change
runs through batch mode, which copies the table; Postgres alters it in place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distance_mi", sa.Float(), nullable=False, server_default="0"),
        sa.Column("credited_mi", sa.Float(), nullable=False, server_default="0"),
        # Only so a row inserted by hand has something to be. The application
        # sends all four on every insert, which is why they come straight off
        # again below.
        sa.Column("capped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "day", name="uq_daily_steps"),
    )
    with op.batch_alter_table("daily_steps") as batch:
        batch.alter_column("steps", existing_type=sa.Integer(), server_default=None)
        batch.alter_column("distance_mi", existing_type=sa.Float(), server_default=None)
        batch.alter_column("credited_mi", existing_type=sa.Float(), server_default=None)
        batch.alter_column("capped", existing_type=sa.Boolean(), server_default=None)

    op.create_table(
        "step_credits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("delta_mi", sa.Float(), nullable=False),
        sa.Column("credited_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "processed_step_credits",
        sa.Column(
            "step_credit_id",
            sa.Integer(),
            sa.ForeignKey("step_credits.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    with op.batch_alter_table("weekly_badge_earns") as batch:
        batch.alter_column("workout_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Takes the three tables away and puts the workout back on every weekly row.

    A weekly medal the steps carried over the line cannot be expressed in the
    old shape at all, so those rows go rather than being given a workout that
    did not earn them. Nothing is lost by it: weekly earns are a derivation, and
    the release this steps back to rebuilds them from the workouts it can see.
    """
    earns = sa.table("weekly_badge_earns", sa.column("workout_id", sa.Integer()))
    op.execute(earns.delete().where(earns.c.workout_id.is_(None)))
    with op.batch_alter_table("weekly_badge_earns") as batch:
        batch.alter_column("workout_id", existing_type=sa.Integer(), nullable=False)
    op.drop_table("processed_step_credits")
    op.drop_table("step_credits")
    op.drop_table("daily_steps")
