"""fruit: what a grown plant bears, and the four things manna is spent on

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-12

Five tables and three columns, and every one of them is additive: nothing
already stored is read, rewritten or moved, so this runs on a database that has
been live since 0001 exactly as it runs on a fresh one.

The columns carry server defaults for the rows already there. A grove that has
never borne starts its meter at nothing and its season count at nothing, which
is the truth about it: fruit begins with this release, and backdating a harvest
would be inventing one. A plant starts unfed for the same reason.

There is no backfill here, and that is the whole of the design. Pending manna
was already seeded by 0025 from the calories on record; what this release adds
is somewhere for it to go, and where it goes is a decision each account makes
for itself.

The gathered pile is rows rather than a number. Gathered goods live seven days
from the day they were gathered, and a single balance could not say which part
of itself was old; the batches also give the rebuild the one figure it needs,
which is how much has ever left the pending pile.

Stepping back drops all of it. What is lost is the harvests and the gifts, which
is what stepping back past the release that invented them means; the miles, the
calories, the plants and the pending pile it all came from are untouched, so the
same upgrade run again lands on a grove that simply has not borne yet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The catalogue ids are strings of this length everywhere in the schema.
_CATALOG_ID = sa.String(48)


def upgrade() -> None:
    # The meter that decides WHEN a grove bears, and how many times it has. Both
    # are fed by converted Miles and by nothing else: bearing is earned, and no
    # currency may ever move either one (TWO-LANE LAW).
    op.add_column(
        "user_progress",
        sa.Column(
            "fruit_progress_mi", sa.Float(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "user_progress",
        sa.Column("fruit_seasons", sa.Integer(), nullable=False, server_default="0"),
    )
    # What decides HOW MUCH a plant bears next time, bought with gathered manna.
    # Fruit and only fruit: growth, levels, chests and medals never read it.
    op.add_column(
        "plantings",
        sa.Column("fed_bonus", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "fruit_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "planting_id",
            sa.Integer(),
            sa.ForeignKey("plantings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("species", _CATALOG_ID, nullable=False),
        sa.Column("golden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("count", sa.Integer(), nullable=False),
        # Which bearing it came from, counting from one. One workout can cross
        # the meter twice and both crossings carry that workout's stamp, so the
        # ordinal is the only thing that can count seasons apart.
        sa.Column("season", sa.Integer(), nullable=False, server_default="1"),
        # The provenance, written at the bearing: a gift's sentence must not
        # change when a constant is retuned years later.
        sa.Column("season_mi", sa.Float(), nullable=False),
        sa.Column("season_month", sa.String(16), nullable=False),
        sa.Column("borne_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gathered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("composted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("given_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "given_to_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "earned_renown", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index("ix_fruit_batches_user_id", "fruit_batches", ["user_id"])

    op.create_table(
        "fruit_keepsakes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Frozen beside the pointer, because a keepsake outlives the account
        # that sent it and a row that could only say "somebody" is not one.
        sa.Column("from_username", sa.String(32), nullable=False),
        sa.Column("species", _CATALOG_ID, nullable=False),
        sa.Column("golden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("provenance", sa.String(200), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fruit_keepsakes_user_id", "fruit_keepsakes", ["user_id"])

    op.create_table(
        "manna_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # What was gathered and what is left of it. The first never changes,
        # which is what lets a rebuild ask how much has ever been gathered.
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("remaining", sa.Integer(), nullable=False),
        sa.Column("gathered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("composted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_manna_batches_user_id", "manna_batches", ["user_id"])

    op.create_table(
        "manna_gifts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "from_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "earned_renown", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index("ix_manna_gifts_from_user_id", "manna_gifts", ["from_user_id"])
    op.create_index("ix_manna_gifts_to_user_id", "manna_gifts", ["to_user_id"])
    # The renown window: the newest earning row for one pair.
    op.create_index(
        "ix_manna_gift_pair", "manna_gifts", ["from_user_id", "to_user_id", "created_at"]
    )

    op.create_table(
        "plant_feedings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "from_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The plant's owner, which is the giver themselves when somebody fed
        # their own plot. That case earns nothing and is the quiet option.
        sa.Column(
            "to_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "planting_id",
            sa.Integer(),
            sa.ForeignKey("plantings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("manna_spent", sa.Integer(), nullable=False),
        sa.Column("bonus", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "earned_renown", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index("ix_plant_feedings_from_user_id", "plant_feedings", ["from_user_id"])
    op.create_index("ix_plant_feedings_to_user_id", "plant_feedings", ["to_user_id"])
    op.create_index(
        "ix_plant_feeding_pair",
        "plant_feedings",
        ["from_user_id", "to_user_id", "created_at"],
    )


def downgrade() -> None:
    """Take the whole release back out.

    In the reverse order it was built, and the indexes go with their tables.
    The three columns go last, because the pending pile they sit beside is the
    thing every number here came out of and it stays exactly as 0025 left it.
    """
    op.drop_table("plant_feedings")
    op.drop_table("manna_gifts")
    op.drop_table("manna_batches")
    op.drop_table("fruit_keepsakes")
    op.drop_table("fruit_batches")
    op.drop_column("plantings", "fed_bonus")
    op.drop_column("user_progress", "fruit_seasons")
    op.drop_column("user_progress", "fruit_progress_mi")
