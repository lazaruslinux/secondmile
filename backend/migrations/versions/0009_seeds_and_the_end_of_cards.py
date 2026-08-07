"""the chest ladder, the satchel, the plot, and the end of the cards

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-07

Chests stop holding cards and start holding tools. Three new tables carry the
whole of it: satchel_items is what a chest gave and has not been spent yet,
plantings is what is growing, and anointings is oil one person spent on
another. Chests gain the step of the ladder that dropped them, and the row that
says a chest was a gift rather than a distance.

The cards go completely. user_cards is dropped, chests.card_id with it, and the
collection achievements are deleted from the earned rows as well as from the
catalogue: an id nothing in the source knows about would sit in a badge slot
forever. Nothing else earned is taken back.

The chest accumulator resets to zero and the cycle starts at the 5K step, so
everybody's next chest is three miles away from the next mile they sync. The
chests already waiting keep their place with a null tier, which the code reads
as the first step of the ladder.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# native_enum off, as everywhere else here.
_ITEM_KIND = sa.Enum("seed", "water", "oil", name="satchel_kind", native_enum=False)

# Species ids are strings from the source rather than rows, the same as the
# card ids they replace, so nothing here has a foreign key to them.
_CATALOG_ID = sa.String(48)


def upgrade() -> None:
    # First, because chests grows a foreign key pointing at it.
    op.create_table(
        "anointings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "from_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "to_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        # Not a foreign key: a rebuild may throw chests away, and a record of
        # what one person gave another has to outlive that.
        sa.Column("consumed_chest_id", sa.Integer(), nullable=True),
    )
    # One unspent gift per pair. Partial, so the same pair can give again once
    # the last one has landed.
    op.create_index(
        "uq_anointing_pending",
        "anointings",
        ["from_user_id", "to_user_id"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL"),
        sqlite_where=sa.text("consumed_at IS NULL"),
    )

    op.create_table(
        "satchel_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", _ITEM_KIND, nullable=False),
        # Null for water and oil, which are the same wherever they came from.
        sa.Column("species", _CATALOG_ID, nullable=True),
        sa.Column("rarity", sa.String(16), nullable=False),
        # Nulled rather than cascaded: an item somebody is holding is theirs
        # whatever later happens to the chest it came out of.
        sa.Column(
            "chest_id",
            sa.Integer(),
            sa.ForeignKey("chests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        # Who it was given to, when it was given to somebody: water poured into
        # a friend's plot, or oil. Null for anything spent on your own.
        sa.Column(
            "given_to_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("earned_renown", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "plantings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("species", _CATALOG_ID, nullable=False),
        sa.Column("rarity", sa.String(16), nullable=False),
        sa.Column("planted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("growth_mi", sa.Float(), nullable=False, server_default="0"),
        sa.Column("matured_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Null on every chest that predates the ladder, which the code reads as the
    # first step: those chests roll the first step's odds and are named for it.
    op.add_column("chests", sa.Column("tier", sa.String(16), nullable=True))
    # Which anointing this chest came out of, or null for one the miles earned.
    # Not a foreign key: the pointer the other way is not one either, and a
    # column that can be added on either database is worth more here.
    op.add_column("chests", sa.Column("from_anointing_id", sa.Integer(), nullable=True))
    # The cards are gone, so what a chest was carrying is gone with them. The
    # chests themselves stay: nothing already earned is taken back.
    op.drop_column("chests", "card_id")

    op.add_column(
        "user_progress",
        sa.Column("cycle_pos", sa.Integer(), nullable=False, server_default="0"),
    )
    # The old accumulator was measured against a random gap that no longer
    # exists. Everybody starts the cycle at the 5K step from their next mile.
    op.drop_column("user_progress", "next_chest_gap_mi")
    op.execute("UPDATE user_progress SET chest_progress_mi = 0")

    op.drop_table("user_cards")
    # The collection achievements went with the catalogue. Leaving the earned
    # rows behind would leave ids nothing in the source recognises sitting in
    # people's badge slots.
    op.execute("DELETE FROM user_achievements WHERE achievement_id LIKE 'collection%'")


def downgrade() -> None:
    """Puts the columns and tables back and none of the content.

    The cards themselves cannot come back: which plate each chest held was
    thrown away above, and no other row remembers it. This is here so the
    revision can be stepped back on a test database, not so a release can be
    undone on a real one.
    """
    op.create_table(
        "user_cards",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("card_id", _CATALOG_ID, primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_found_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "user_progress", sa.Column("next_chest_gap_mi", sa.Float(), nullable=True)
    )
    op.drop_column("user_progress", "cycle_pos")
    # Nullable, unlike the original: there is nothing to fill it with.
    op.add_column("chests", sa.Column("card_id", _CATALOG_ID, nullable=True))
    op.drop_column("chests", "from_anointing_id")
    op.drop_column("chests", "tier")
    op.drop_table("plantings")
    op.drop_table("satchel_items")
    op.drop_index("uq_anointing_pending", table_name="anointings")
    op.drop_table("anointings")
