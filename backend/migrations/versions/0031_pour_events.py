"""pours are events now, and what a plot already grew is floored

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-13

One table and one column, both additive. Nothing already stored is rewritten
except the new column's own backfill, and no number anybody can see moves.

WHAT WAS WRONG. A pour added ten Miles to a planting and left no record of
itself anywhere: the water item said it had been spent, and nothing said which
plant it was spent on. A rebuild (progress.recompute) takes the plot back to
bare ground and replays the workouts, so every pour an account had ever made
came off the plants and stayed off: levels dropped, maturity dates vanished
while the fruit those plants had borne stayed in the basket, and a gilded plant
came back unfinished. pour_events is the missing record, written from now on in
the same transaction as the growth it stands for.

WHAT THIS CANNOT DO. It cannot invent the pours that already happened. Which
plant took which water is not recoverable: the spent item names a friend's plot
at best and never a planting, so there is no honest way to hand those miles back
to the right plant one at a time.

THE FLOOR, WHICH IS WHAT IS DONE INSTEAD. legacy_growth_mi is set to the growth
each planting stands at right now, and to zero on everything planted after this
runs. A rebuild reads it as the least a plant may come back with:

    growth = max(replayed workout growth, legacy_growth_mi) + recorded pours

So a rebuild on the day this runs lands every plant exactly where it already
stood, and every pour recorded from here on is added on top of that. The floor
is deliberately generous: part of each snapshot is workout growth the replay
would have reproduced anyway, and counting it twice is impossible because the
two are combined with a max rather than a sum. It decays on its own, the day the
miles pass it.

Stepping back drops both, and the growth already in the plot is left alone: the
column going away costs a rebuild its floor, which is a rebuild that has not
happened yet rather than anything stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pour_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "planting_id",
            sa.Integer(),
            sa.ForeignKey("plantings.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Whoever poured it, which is the plot's owner or a friend of theirs.
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # What the pour was worth when it happened, so retuning WATER_POUR_MI
        # never rewrites an old one.
        sa.Column("miles", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column(
        "plantings",
        sa.Column(
            "legacy_growth_mi", sa.Float(), nullable=False, server_default="0"
        ),
    )
    # Every plant standing today, floored at what it has already grown. Plants
    # put in the ground after this keep the zero the default gives them: their
    # pours are recorded, so a replay reaches them without any help.
    op.execute("UPDATE plantings SET legacy_growth_mi = growth_mi")


def downgrade() -> None:
    op.drop_column("plantings", "legacy_growth_mi")
    op.drop_table("pour_events")
