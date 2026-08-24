"""an index for the query every screen in the app runs

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-23

One index, additive, changing no data and no answer.

progress.process_user is what every screen comes through, and the first thing it
does is ask which of this account's workouts have not been credited yet. That
query filters on user_id and deleted_at and orders by start_ts then id, and until
now the only index it could use was user_id alone: the ordering was a sort on top
of whatever came back.

Composite and in that order, so one index serves the filter and the sort
together. It is the same shape the history page and the feed read in, so those
get it for nothing.

Plain rather than partial. `WHERE deleted_at IS NULL` would be smaller and this
suite runs on SQLite as well as Postgres, so a portable index is one the
migration tests actually exercise on both engines.

Stepping back drops it and the planner sorts again, which is where it started.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_workouts_user_pending", "workouts", ["user_id", "start_ts", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_workouts_user_pending", table_name="workouts")
