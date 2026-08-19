"""samples: the minute-by-minute detail an export has always carried

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-19

One new table and four new columns, all additive; nothing existing is read or
rewritten, and every row already in the database is carried by the nulls.

workout_samples holds one row per minute of a session: how far it covered, how
many steps it took, and what the heart was doing. The export has sent all of it
since long before this release, and the only copy of it until now was the raw
payload in ingest_log, which is deleted at INGEST_LOG_RETENTION_DAYS on the
account's next sync. That is the whole point of the table: a week unshipped is a
week of detail gone for good.

The unique key on (workout_id, minute) is what makes a re-sync harmless. Health
Auto Export sends overlapping windows forever, so a session arrives again and
again, and one minute of one workout may only ever be described once.

The four columns on workouts are the whole-session summaries beside those
arrays: the climb, the highest beat, and the air. They are nullable and stay
null on every workout imported before this release, which is honest rather than
complete, exactly as the indoor column in 0027 was: the ingest log can still
answer for the last ninety days and answers for nothing older. Filling those
ninety days is manage.py backfill-samples, run by hand, rather than a backfill
here, because it is a long replay of every stored payload on the instance and
belongs somewhere it can be run again after a parsing fix.

Nothing derived reads any of this. No medal, no conversion, no flag and no total
changes because a workout now knows how much it climbed, so stepping back drops
the table and the columns and loses only what a details screen would have drawn.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workout_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workout_id",
            sa.Integer(),
            sa.ForeignKey("workouts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("distance_mi", sa.Float(), nullable=True),
        sa.Column("hr_min", sa.Integer(), nullable=True),
        sa.Column("hr_avg", sa.Integer(), nullable=True),
        sa.Column("hr_max", sa.Integer(), nullable=True),
        sa.Column("steps", sa.Integer(), nullable=True),
        sa.UniqueConstraint("workout_id", "minute", name="uq_workout_sample"),
    )

    op.add_column("workouts", sa.Column("elevation_gain_ft", sa.Float(), nullable=True))
    op.add_column("workouts", sa.Column("max_hr", sa.Integer(), nullable=True))
    op.add_column("workouts", sa.Column("temperature_f", sa.Float(), nullable=True))
    op.add_column("workouts", sa.Column("humidity_pct", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("workouts", "humidity_pct")
    op.drop_column("workouts", "temperature_f")
    op.drop_column("workouts", "max_hr")
    op.drop_column("workouts", "elevation_gain_ft")
    op.drop_table("workout_samples")
