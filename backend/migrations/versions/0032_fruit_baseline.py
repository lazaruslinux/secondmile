"""fruit: the miles that came before the meter, and are not a season

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-14

One column, additive, with the arithmetic that gives it a value in the same
breath. Nothing else is read or rewritten, and no number anybody can see moves.

WHAT WAS WRONG. 0026 backfilled nothing and said why: fruit begins with the
release, and backdating a harvest would be inventing one. That is the truth
about the harvest and it left something unsaid about the fuel. The meter is
banked converted Miles, and both replays of a whole history
(progress.recompute and progress.rebuild_from_surviving) walk every surviving
mile through it while paying back only the seasons actually borne. An account
that had been running for a year before the release therefore carried a year of
miles the meter had never seen, and the first workout it ever deleted handed all
of them over at once: a dozen seasons borne in a single pass, for crossings
nobody was there for.

WHAT THE COLUMN IS. fruit_baseline_mi is that unseen fuel, per account. The
replays walk max(0, fuel - baseline) from here on, so the history below the line
stays exactly what it was the day the release landed: counted for experience,
levels, chests, medals and manna, and no part of any season.

THE BACKFILL. Each account is asked what its own record says the meter has never
walked:

    baseline = max(0, lifetime converted fuel - seasons borne * a season - meter)

An account whose meter has walked all its fuel lands at nothing, which is every
account made since the release. One that walked none of it lands at its whole
history. Anything the arithmetic sends below zero lands at nothing rather than
below it: a meter claiming more fuel than the workouts behind it can account for
is a scrub or a retune, and no baseline is the honest answer to it.

WHAT THIS CANNOT DO. It cannot tell a pre-release mile from a post-release one.
The workouts carry their dates, but which day the release reached which database
is not a fact this schema holds, and an account already corrected by hand has a
season count that no longer stands for what it walked. So the formula reads the
meter rather than the calendar, and an account it cannot describe is put right
by hand afterwards rather than guessed at here.

Stepping back drops the column, and the replays walk raw fuel again. What is
lost is a fix rather than anything stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The conversions app.config.MILES_PER_RAW holds and the season
# app.config.FRUIT_SEASON_MI holds. Written out rather than imported, for 0025's
# reason: a migration is a record of what ran on the day it ran, and a constant
# the app retunes later must not quietly rewrite this one's history. Feet are one
# for one, which is the CASE below falling through.
CYCLE_PER_MI = 1.0 / 3.0
SWIM_PER_MI = 4.0
SEASON_MI = 33.0

# One account's lifetime converted fuel: the effort equivalence
# app.activity.converted_miles applies, said in SQL. A deleted workout is worth
# nothing here exactly as it is worth nothing anywhere else in the game.
_FUEL = """
        SELECT COALESCE(SUM(w.distance_mi * CASE w.activity
            WHEN 'cycle' THEN :cycle
            WHEN 'swim' THEN :swim
            ELSE 1.0
        END), 0)
        FROM workouts w
        WHERE w.user_id = user_progress.user_id AND w.deleted_at IS NULL
"""


def upgrade() -> None:
    op.add_column(
        "user_progress",
        sa.Column("fruit_baseline_mi", sa.Float(), nullable=False, server_default="0"),
    )
    # Two statements rather than one. The floor at zero is spelt GREATEST on one
    # engine and max on the other, and writing the subquery out twice to avoid
    # saying either is worse than a second pass over a table that holds one row
    # per account.
    op.execute(
        sa.text(
            "UPDATE user_progress SET fruit_baseline_mi ="
            f" ({_FUEL}) - fruit_seasons * :season - fruit_progress_mi"
        ).bindparams(cycle=CYCLE_PER_MI, swim=SWIM_PER_MI, season=SEASON_MI)
    )
    op.execute("UPDATE user_progress SET fruit_baseline_mi = 0 WHERE fruit_baseline_mi < 0")


def downgrade() -> None:
    op.drop_column("user_progress", "fruit_baseline_mi")
