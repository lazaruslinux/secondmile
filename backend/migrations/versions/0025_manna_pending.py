"""manna: what the calories have already come to

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-12

One column on user_progress, and the history converted into it in the same
breath.

The column is additive with a default of zero, exactly as renown arrived in
0008, so it runs on a database that has been live since 0001 as it runs on a
fresh one and every existing row is carried by the default rather than by a
statement.

The backfill is the release's whole point. Manna is what burned calories become
and every account's calories are already recorded, so starting everybody at
nothing would be the app forgetting a year of work it has in front of it. Each
workout converts on its own, one for one and rounded up to the next multiple of
five, and the account's pending manna is the sum of those. Per workout and never
over a total: two sessions of 651 are 1320 and never 1305, which is the same
arithmetic app.progress.manna_for does, so a backfilled account and a rebuilt
one land on the same number.

Counted in Python rather than in SQL, and deliberately. Rounding up a division
is spelt differently on the two engines, and a cast to an integer truncates on
one and rounds on the other, so the one line that decides what a workout is
worth would have been two lines that have to be kept agreeing. The row count
here is a history of workouts, which is small.

Which workouts count: the ones that are not deleted and have already been
credited. Deleted miles never earned anything, and a workout still waiting for
its first sweep is paid for by that sweep a moment later; counting it here as
well would credit it twice. The processed marker is the same line the pipeline
itself draws between the two.

Nothing is spent yet, so there is nothing this can take away from anybody. The
round that adds spending is the round that has to answer spent-stays-spent.
"""

import math
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The same step app.config.MANNA_STEP_KCAL holds. Written out rather than
# imported: a migration is a record of what ran on the day it ran, and a
# constant the app retunes later must not quietly rewrite this one's history.
STEP_KCAL = 5


def upgrade() -> None:
    op.add_column(
        "user_progress",
        sa.Column("manna_pending", sa.Integer(), nullable=False, server_default="0"),
    )
    _backfill(op.get_bind())


def _backfill(connection) -> None:
    """Every account's pending manna, from the workouts it has been credited for."""
    totals: dict[int, int] = {}
    for row in connection.execute(
        sa.text(
            "SELECT w.user_id AS user_id, w.active_kcal AS active_kcal FROM workouts w"
            " JOIN processed_workouts p ON p.workout_id = w.id"
            " WHERE w.deleted_at IS NULL"
        )
    ):
        kcal = row.active_kcal
        # Nothing recorded is worth nothing, and so is a negative reading from a
        # confused sensor. Neither is a free step of manna.
        if kcal is None or kcal <= 0:
            continue
        totals[row.user_id] = totals.get(row.user_id, 0) + math.ceil(kcal / STEP_KCAL) * STEP_KCAL

    for user_id, pending in totals.items():
        connection.execute(
            sa.text("UPDATE user_progress SET manna_pending = :pending WHERE user_id = :user_id"),
            {"pending": pending, "user_id": user_id},
        )


def downgrade() -> None:
    """Drops the column. The release before this one never read it, and the
    workouts every number in it was worked out from are untouched, so stepping
    back loses nothing that cannot be worked out again."""
    op.drop_column("user_progress", "manna_pending")
