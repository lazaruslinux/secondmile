"""twelve medals, and the end of the achievements

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-07

The achievements go, as a system rather than as a few ids. What replaces them
is the medal catalogue grown to twelve: the five race medals it already had,
four weekly ones, two for the hour of the day, and the Second Mile. Everything
in it is repeatable, so there is nothing left that is earned once and ticked
off, and user_achievements is dropped whole.

Three schema changes carry it.

badge_earns loses the unique on workout_id and gains one on the pair. A workout
can now hold one race medal and one time medal at once, and the pair is still
what makes replaying a history idempotent. SQLite cannot drop a column
constraint in place, so it recreates the table; Postgres drops the constraint
0006 created and adds the new one, looked up by catalogue rather than by a name
this file guesses at.

weekly_badge_earns is new: one row per family per week, keyed by the account,
the Monday, and the family. That key is what lets a week upgrade its medal in
place as the miles add up, rather than wearing three medals for the same seven
days.

Any id sitting in a badge slot that the twelve do not name is pruned out of it,
the way 0006 and 0009 pruned theirs: a slot naming a medal no release defines
renders as nothing.

The new families are NOT backfilled here: they belong to particular workouts
and particular weeks, and awarding them means replaying the history. Do that
per account with

    docker compose exec backend python manage.py backfill-badges theirname

which writes nothing but medals.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG_ID = sa.String(48)

# Written out rather than imported, for the reason 0004 gives: a migration has
# to keep doing what it did on the day it ran, and a catalogue is retuned.
_MEDAL_IDS = (
    "race_5k",
    "race_10k",
    "race_half",
    "race_marathon",
    "race_ultra",
    "weekly_10",
    "weekly_15",
    "weekly_25",
    "weekly_40",
    "early_riser",
    "night_owl",
    "second_mile",
)

# badge_earns as it stands after this revision, which batch mode on SQLite
# needs in full: it recreates the table from this definition rather than from
# what it can reflect.
_BADGE_EARNS = sa.Table(
    "badge_earns",
    sa.MetaData(),
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column(
        "user_id",
        sa.Integer(),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("badge_id", _CATALOG_ID, nullable=False),
    sa.Column(
        "workout_id",
        sa.Integer(),
        sa.ForeignKey("workouts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
)


def _unique_constraint_names(connection, table: str) -> list[str]:
    """The unique constraints on a Postgres table, by name.

    0006 wrote its one as a column flag, so the name is whatever Postgres chose
    at the time. Reading it back is shorter than being wrong about it.
    """
    return list(
        connection.execute(
            sa.text(
                # CAST rather than ::, which text() cannot tell apart from a
                # bound parameter.
                "SELECT conname FROM pg_constraint"
                " WHERE conrelid = CAST(:table AS regclass) AND contype = 'u'"
            ).bindparams(table=table)
        ).scalars()
    )


def upgrade() -> None:
    connection = op.get_bind()

    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(
            "badge_earns", copy_from=_BADGE_EARNS, recreate="always"
        ) as batch:
            batch.create_unique_constraint(
                "uq_badge_earn_workout_medal", ["workout_id", "badge_id"]
            )
    else:
        for name in _unique_constraint_names(connection, "badge_earns"):
            op.drop_constraint(name, "badge_earns", type_="unique")
        op.create_unique_constraint(
            "uq_badge_earn_workout_medal", "badge_earns", ["workout_id", "badge_id"]
        )

    op.create_table(
        "weekly_badge_earns",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # The Monday of the week, in the instance timezone.
        sa.Column("week_start", sa.Date(), primary_key=True),
        sa.Column("family", sa.String(16), primary_key=True),
        sa.Column("badge_id", _CATALOG_ID, nullable=False),
        # The workout that crossed the line, so the letter can ask when the
        # medal arrived rather than when it was earned.
        sa.Column(
            "workout_id",
            sa.Integer(),
            sa.ForeignKey("workouts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
    )

    # The achievements are gone as a system. Their weekly targets survive as
    # the weekly medals, which are earned from the workouts rather than held
    # forever, so there is nothing in here worth carrying across.
    op.drop_table("user_achievements")

    # Badge slots are a JSON list, so this is read, filtered, and written back
    # rather than done in SQL: the two databases spell JSON array surgery
    # differently and neither spelling is worth learning for twelve ids.
    kept_ids = set(_MEDAL_IDS)
    for user_id, raw in connection.execute(
        sa.text("SELECT id, displayed_badges FROM users")
    ).all():
        current = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(current, list):
            continue
        kept = [badge for badge in current if badge in kept_ids]
        if len(kept) != len(current):
            connection.execute(
                # A typed bind, so each database serializes the list into its
                # own JSON column spelling.
                sa.text(
                    "UPDATE users SET displayed_badges = :badges WHERE id = :user_id"
                ).bindparams(
                    sa.bindparam("badges", value=kept, type_=sa.JSON()),
                    sa.bindparam("user_id", value=user_id),
                )
            )


def downgrade() -> None:
    """Back to one medal per workout, and an empty achievements table.

    What was earned cannot come back. The achievement rows were deleted with
    their table, and the weekly and time medals are dropped here because the
    older release has no catalogue entry for either: an id nothing in the
    source recognises would sit in a badge slot forever. Running the older
    release's evaluator awards its achievements again from the same history.
    """
    connection = op.get_bind()

    op.create_table(
        "user_achievements",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("achievement_id", _CATALOG_ID, primary_key=True),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gilded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_table("weekly_badge_earns")

    # The time medals go before the constraint comes back: a workout holding
    # two rows is exactly what the old unique refuses.
    connection.execute(
        sa.text("DELETE FROM badge_earns WHERE badge_id NOT LIKE 'race_%'")
    )
    # And out of the slots with them, the same read-filter-write the upgrade
    # does. The race ids stay: the older release still defines those.
    for user_id, raw in connection.execute(
        sa.text("SELECT id, displayed_badges FROM users")
    ).all():
        current = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(current, list):
            continue
        kept = [badge for badge in current if str(badge).startswith("race_")]
        if len(kept) != len(current):
            connection.execute(
                sa.text(
                    "UPDATE users SET displayed_badges = :badges WHERE id = :user_id"
                ).bindparams(
                    sa.bindparam("badges", value=kept, type_=sa.JSON()),
                    sa.bindparam("user_id", value=user_id),
                )
            )

    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(
            "badge_earns", copy_from=_BADGE_EARNS, recreate="always"
        ) as batch:
            batch.create_unique_constraint("uq_badge_earn_workout", ["workout_id"])
    else:
        op.drop_constraint("uq_badge_earn_workout_medal", "badge_earns", type_="unique")
        op.create_unique_constraint("uq_badge_earn_workout", "badge_earns", ["workout_id"])
