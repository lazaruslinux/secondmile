"""profiles, levels, achievements

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-31

The journey map is gone. Everything that only existed to serve it is dropped:
journeys, journey_events, region_unlocks, mile_spends, and user_accolades,
whose accolades are replaced by the achievements catalogue rather than
migrated into it (an accolade was a mark on a road, and there are no roads).

processed_workouts survives untouched as the idempotent spine of the pipeline.
chests and user_cards survive as tables but are emptied: their card ids point
at a catalogue that no longer exists, and a row naming a card no release can
define is worse than no row. This is acceptable exactly once, before 1.0, with
no public instance to answer to. Take a dump first anyway.

The backfill gives every existing account the experience its whole workout
history is worth, computed here in the same shape app.progress computes it, and
marks every existing workout as already credited so nothing is counted twice.
It deliberately does not replay the chest stream: an account would otherwise
open the app to a pile of several hundred chests it did not know it had.
Anybody who wants that replay can ask for it afterwards with:

    python manage.py recompute-progress <username>

Achievements need no backfill. The evaluator reads aggregates over the whole
history rather than watching workouts go past, so the first request after this
migration awards every badge the account had already earned.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Card and achievement ids are strings from the source rather than rows, so
# nothing here has a foreign key to them.
_CATALOG_ID = sa.String(48)

# Kept in step with app.config and app.progress, and written out rather than
# imported: a migration has to keep doing what it did on the day it ran, and
# those are constants that will be retuned.
_MILES_PER_RAW = {"walk": 1.0, "run": 1.0, "cycle": 1.0 / 3.0, "swim": 4.0}
_XP_PER_MILE = 10.0
_XP_PER_MINUTE = 1.0
_LEVEL_STEP_XP = 100


def _level_for_xp(xp: int) -> int:
    """The same curve as app.progress: level n costs 100 * n beyond level n-1."""
    level = 1
    while xp >= _LEVEL_STEP_XP * ((level + 1) * (level + 2) // 2 - 1):
        level += 1
    return level


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_path", sa.String(128), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "displayed_badges", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
    )

    op.create_table(
        "user_progress",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("chest_progress_mi", sa.Float(), nullable=False, server_default="0"),
        # Null until the first workout's seeded generator rolls one, so this
        # migration does not have to invent a random number.
        sa.Column("next_chest_gap_mi", sa.Float(), nullable=True),
        sa.Column("last_ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
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

    op.drop_table("mile_spends")
    op.drop_table("region_unlocks")
    op.drop_table("user_accolades")
    op.drop_table("journey_events")
    op.drop_table("journeys")

    # Re-keyed rather than migrated: every card id in these two tables names a
    # set that no longer exists.
    op.execute(sa.text("DELETE FROM user_cards"))
    op.execute(sa.text("DELETE FROM chests"))
    op.execute(sa.text("DELETE FROM processed_workouts"))

    connection = op.get_bind()
    totals = connection.execute(
        sa.text(
            "SELECT user_id, activity, SUM(distance_mi), SUM(duration_s) "
            "FROM workouts GROUP BY user_id, activity"
        )
    ).all()
    experience: dict[int, float] = {}
    for user_id, activity, distance_mi, duration_s in totals:
        miles = float(distance_mi or 0.0) * _MILES_PER_RAW.get(activity, 1.0)
        minutes = float(duration_s or 0) / 60.0
        experience[user_id] = experience.get(user_id, 0.0) + (
            miles * _XP_PER_MILE + minutes * _XP_PER_MINUTE
        )

    # A row for every account, including the ones with no workouts at all, so
    # nothing has to create one lazily on a database that has just been
    # migrated.
    for (user_id,) in connection.execute(sa.text("SELECT id FROM users")).all():
        xp = round(experience.get(user_id, 0.0))
        connection.execute(
            sa.text(
                "INSERT INTO user_progress "
                "(user_id, xp, level, chest_progress_mi, next_chest_gap_mi, "
                " last_ack_at, updated_at) "
                "VALUES (:user_id, :xp, :level, 0, NULL, NULL, CURRENT_TIMESTAMP)"
            ).bindparams(user_id=user_id, xp=xp, level=_level_for_xp(xp))
        )

    # Every workout that already exists is history, and history has just been
    # paid for in one lump above. Marking it credited is what stops the first
    # sweep after the upgrade paying for it a second time.
    connection.execute(
        sa.text("INSERT INTO processed_workouts (workout_id) SELECT id FROM workouts")
    )


def downgrade() -> None:
    """Put the journey tables back, empty.

    A downgrade cannot restore a journey: the positions, the events, and the
    accolades were dropped, and no column here holds enough to reconstruct
    them. This gets the schema back to 0003 so an older release will start, and
    everybody begins again from the Homestead.
    """
    op.create_table(
        "journeys",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("location_id", _CATALOG_ID, nullable=True),
        sa.Column("road_id", _CATALOG_ID, nullable=True),
        sa.Column("position_mi", sa.Float(), nullable=False, server_default="0"),
        sa.Column("destination_id", _CATALOG_ID, nullable=True),
        sa.Column("next_chest_mi", sa.Float(), nullable=True),
        sa.Column("traveled_mi", sa.Float(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "journey_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("seen", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "user_accolades",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("accolade_id", _CATALOG_ID, primary_key=True),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "region_unlocks",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("region_id", _CATALOG_ID, primary_key=True),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "mile_spends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "activity",
            sa.Enum("walk", "run", "cycle", "swim", name="activity", native_enum=False),
            nullable=False,
        ),
        sa.Column("amount_mi", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(sa.text("DELETE FROM user_cards"))
    op.execute(sa.text("DELETE FROM chests"))
    op.execute(sa.text("DELETE FROM processed_workouts"))
    op.drop_table("user_achievements")
    op.drop_table("user_progress")
    op.drop_column("users", "displayed_badges")
    op.drop_column("users", "avatar_path")
