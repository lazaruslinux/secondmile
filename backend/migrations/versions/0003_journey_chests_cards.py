"""journeys, chests, cards, accolades

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-30

Additive: eight new tables and no change to anything that already exists.
Types stay portable for the same reason 0001 and 0002 did, so JSON rather
than JSONB and a plain VARCHAR check constraint rather than a native enum.

The one data step gives every account that already exists a journey starting
now. Starting it at the account's creation date instead would fire months of
stored training through the map the moment the instance is updated, and the
first thing anybody saw would be a recap of a journey they did not take.
Anyone who wants that can ask for it afterwards with:

    python manage.py journey-restart <username> --from-beginning
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matches models.ActivityEnum. Named the same so Postgres does not try to
# create a second type for it.
_activity = sa.Enum("walk", "run", "cycle", "swim", name="activity", native_enum=False)

# World ids (places, roads, regions, cards, accolades) are strings from the
# source rather than rows, so nothing here has a foreign key to them.
_WORLD_ID = sa.String(48)

# Kept in step with app.world. Written out rather than imported: a migration
# has to keep doing what it did on the day it ran, and app.world is content
# that will be edited.
_START_LOCATION = "homestead"
_START_DESTINATION = "millbrook"


def upgrade() -> None:
    op.create_table(
        "journeys",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("location_id", _WORLD_ID, nullable=True),
        sa.Column("road_id", _WORLD_ID, nullable=True),
        sa.Column("position_mi", sa.Float(), nullable=False, server_default="0"),
        sa.Column("destination_id", _WORLD_ID, nullable=True),
        # Null until the first workout rolls it, so this migration does not
        # have to invent a random number and neither does registration.
        sa.Column("next_chest_mi", sa.Float(), nullable=True),
        sa.Column("traveled_mi", sa.Float(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "processed_workouts",
        sa.Column(
            "workout_id",
            sa.Integer(),
            sa.ForeignKey("workouts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
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
        "chests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("card_id", _WORLD_ID, nullable=False),
        sa.Column("dropped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "user_cards",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("card_id", _WORLD_ID, primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_found_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "user_accolades",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("accolade_id", _WORLD_ID, primary_key=True),
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
        sa.Column("region_id", _WORLD_ID, primary_key=True),
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
        sa.Column("activity", _activity, nullable=False),
        sa.Column("amount_mi", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Everyone who already has an account starts where a new one would, from
    # the moment of the upgrade. On a fresh database this selects nothing.
    op.execute(
        sa.text(
            "INSERT INTO journeys "
            "(user_id, location_id, road_id, position_mi, destination_id, "
            " next_chest_mi, traveled_mi, started_at, updated_at) "
            "SELECT id, :start, NULL, 0, :destination, NULL, 0, "
            "       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "FROM users"
        ).bindparams(start=_START_LOCATION, destination=_START_DESTINATION)
    )


def downgrade() -> None:
    op.drop_table("mile_spends")
    op.drop_table("region_unlocks")
    op.drop_table("user_accolades")
    op.drop_table("user_cards")
    op.drop_table("chests")
    op.drop_table("journey_events")
    op.drop_table("processed_workouts")
    op.drop_table("journeys")
