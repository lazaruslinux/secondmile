"""pets: what the harvest draws to a grove, and what fruit is fed to

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-24

Two new tables and one new column, all additive; no existing value is changed
and no existing row is rewritten.

A pet is presence and nothing else. Nothing in the earning lane reads this
table, nothing in the giving lane is spent on it, and no column here is a
currency: fruit_fed counts what has been fed and buys nothing at all.

The unique pair is the no-duplicate rule made structural: one of each species
per account, which is what makes an arrival a draw among the species a grove is
still missing rather than a roll that has to be retried.

staged_at is what lets the letter say a pet grew without an events table beside
it, the same way every other line of the letter is read off a stamp. grown_at is
the end of the growing and is never unset.

fruit_batches.borne_count comes with it, because feeding is the first thing in
the game that takes part of a batch rather than all of it. count is now what is
left of a batch and borne_count is what the plant bore, written once at the
bearing and never touched again: the letter's "your grove bore" sentence reads
the second, so fruit fed to a pet cannot turn a harvest of three into a harvest
of none. Existing rows are backfilled from their own count, which is exactly
what they bore: nothing before this release could take part of a batch.

fruit_gifts comes with it too, because giving became an amount rather than a
batch in the same round. A gift takes fruit off the oldest batches and may leave
a remainder in one of them, so there is no batch to hang it on: the giving is a
row of its own, exactly as a manna gift already is. Every gift the earlier era
wrote is copied across from the batches that carried it, because the renown
window and the flourish read the new table and a gift that vanished from them
would step somebody's frame back. The batch columns those gifts were written on
are left exactly as they stand and are simply no longer written to.

Stepping back drops all three. The pets are forgotten, gifts made after this
release are forgotten with them, and the letter goes back to reading the live
count.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("species", sa.String(16), nullable=False),
        sa.Column("name", sa.String(60), nullable=True),
        sa.Column("stage", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("fruit_fed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("staged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grown_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "species", name="uq_pet_user_species"),
    )

    # The server default is what lets a NOT NULL column land on a table that
    # already has rows, on both databases. It is left in place afterwards rather
    # than dropped: the app writes the column on every insert, and altering it
    # away would be a second migration chore for nothing.
    op.add_column(
        "fruit_batches",
        sa.Column("borne_count", sa.Integer(), nullable=False, server_default="0"),
    )
    # Quoted because count is a function name in both dialects. Every existing
    # row bore exactly what it still holds.
    op.execute('UPDATE fruit_batches SET borne_count = "count"')

    op.create_table(
        "fruit_gifts",
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
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("earned_renown", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_fruit_gift_pair", "fruit_gifts", ["from_user_id", "to_user_id", "created_at"]
    )
    # Every gift the batch-at-a-time era wrote, carried across as it stood. The
    # renown window and the flourish read this table now, so a gift somebody
    # made last week has to still be here or their frame would quietly step back.
    op.execute(
        'INSERT INTO fruit_gifts (from_user_id, to_user_id, "count", created_at, earned_renown) '
        'SELECT user_id, given_to_user_id, "count", given_at, earned_renown FROM fruit_batches '
        "WHERE given_at IS NOT NULL AND given_to_user_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_fruit_gift_pair", table_name="fruit_gifts")
    op.drop_table("fruit_gifts")
    op.drop_column("fruit_batches", "borne_count")
    op.drop_table("pets")
