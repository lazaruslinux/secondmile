"""gear: what a default pair is put on by itself

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-13

One column, additive, with a server default, so every pair already recorded
arrives saying what it has been doing all along: both. Nothing is read and
nothing is rewritten, and a database that has never seen a pair of shoes runs
this in the same breath as one with a shelf of them.

The column gates the stamping at sync and nothing else. A pair set to runs is
still assignable to any walk by hand, which is why nothing here touches
workouts: no assignment already made is reconsidered by this revision or by the
code that reads the column.

Nothing in the game is touched, the same as 0028: gear earns nothing, and
stepping back drops the column without any number anywhere moving.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "gear",
        # "both", "run" or "walk". The last two are the activity names, so the
        # check the ingest makes is one comparison rather than a mapping.
        sa.Column(
            "applies_to", sa.String(length=4), nullable=False, server_default="both"
        ),
    )


def downgrade() -> None:
    op.drop_column("gear", "applies_to")
