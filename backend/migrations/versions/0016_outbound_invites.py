"""the invites you sent, kept as what you typed

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-10

One new table, and one backfill into it.

An invite only ever wrote a friendship row when the name resolved, so the list
of invites you sent was built from resolved names alone: send, read the list,
cancel, repeat, and the form becomes a way to walk the username space and read
a person's card out of every hit. The table here holds the names as they were
typed, whether or not anybody answers to them, and the list is served from it
instead.

The backfill is what keeps the release quiet. Every invite already waiting is a
name its sender typed, so it belongs in the new table; without this, the day of
the deploy every sent invite would disappear from the sender's screen while
still sitting on the recipient's. Only pending rows are carried over: an
accepted one is a friendship now and has nothing left to wait for.

Nothing is dropped. The friendship rows still carry who asked whom, which is
what accepting and declining are answered from.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbound_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # As long as a username may be. No foreign key on purpose: most of the
        # value of this table is the rows that name nobody.
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # One attempt per name per account, so sending the same invite twice is
        # the no-op it always looked like.
        sa.UniqueConstraint("user_id", "username", name="uq_outbound_invite"),
    )

    # One statement on either database. A requester has at most one row per
    # addressee and a username is unique, so this cannot collide with itself.
    op.execute(
        sa.text(
            "INSERT INTO outbound_invites (user_id, username, created_at)"
            " SELECT f.requester_id, u.username, f.created_at"
            " FROM friendships f JOIN users u ON u.id = f.addressee_id"
            " WHERE f.status = 'pending'"
        )
    )


def downgrade() -> None:
    """Drops the table. The invites themselves are the friendship rows and are
    untouched, so the earlier release lists them again from those."""
    op.drop_table("outbound_invites")
