"""what an account keeps back from its friends

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-10

One column on users, additive and the same statement on both engines, so it
runs on a database that has been live since 0001 exactly as it runs on a fresh
one.

It arrives empty for everybody, which is the release's point rather than a
convenience: from here a friend sees the heart rate, the calories, and the
route on a workout by default, and this column is the list of the ones an
account has asked to keep back. An empty list is somebody sharing everything,
which is what every existing account was already doing with the fields it had.

The names it may hold are "avg_hr", "active_kcal", and "route", checked by the
application on every write. Not checked here: the allowed set is a thing the
app retunes, and a constraint frozen into a migration would be a second copy
of it that disagrees with the release the day one is added.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # JSON rather than JSONB, the same reason the earlier ones give: SQLite runs
    # this file too. The server default is what carries the existing rows: the
    # column is not nullable, and a null here would be a third meaning beside
    # "nothing hidden" and a list.
    op.add_column(
        "users",
        sa.Column(
            "hidden_from_friends", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
    )


def downgrade() -> None:
    """Drops the column. The earlier release sends a friend less than this one
    does whatever it held, so nothing it needs goes with it."""
    op.drop_column("users", "hidden_from_friends")
