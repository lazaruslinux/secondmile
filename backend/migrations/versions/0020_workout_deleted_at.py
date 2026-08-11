"""deleting an activity

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-11

One nullable column on workouts, additive and the same statement on both
engines, so it runs on a database that has been live since 0001 exactly as it
runs on a fresh one. Nothing is backfilled: null means a workout nobody has
deleted, which is every row that already exists.

The column is a moment rather than a flag because both things that read it need
the date. The Log's Deleted section counts the days left from it, and the purge
at sync time compares it against DELETED_WORKOUT_RETENTION_DAYS.

No index. Every query that grew a "deleted_at IS NULL" test already narrows by
user_id first, which is indexed, and one account's history is a page of rows
rather than a table scan; an index here would be paid for on every sync and
read by nothing that needed it.

The row itself is never deleted, before or after the purge, so no cascade and
no cleanup job belong to this revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workouts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Drops the column, which brings every deleted workout back into the feed.

    The earlier release has no idea a workout can be deleted, so it would show
    them either way; dropping the column is the honest version of that rather
    than deleting the rows to keep them hidden. Whatever the purge already threw
    away is gone regardless: this cannot put pictures back.
    """
    op.drop_column("workouts", "deleted_at")
