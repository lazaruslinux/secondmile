"""hidden from feed: which sessions their owner keeps off the cards

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-21

One column on workouts, additive, with a server default of false, so a database
that has been live since 0001 runs it in the same breath as a fresh one and
every row already recorded arrives saying what it has been saying all along.

Display only, and that is the whole of it. Nothing earns or stops earning from
this column: the experience, the medals, the chests, the grove, the totals, the
insights and the bests all read the rows they read yesterday, so the two-lane
law is untouched. The feed, the recent list on a profile, and the friend gates
around a workout's details, its line, its pictures and its words are the only
readers, and the owner's own history is not one of them.

Nothing is removed by it either. The hypes and the notes already written on a
workout stay in their own tables while it is hidden and are read again the
moment it is not, so nobody's words are spent by somebody else's decision.

Stepping back drops the column and every workout is on every feed again, which
is where they all were before this ran: no number anywhere is derived from it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workouts",
        sa.Column(
            "hidden_from_feed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("workouts", "hidden_from_feed")
