"""friends, encouragement, and the renown it earns

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-07

Two tables and one column, which together are the whole Fellowship round.

friendships holds one row per invite, in the direction it was asked. A pair is
friends when an accepted row exists either way round, which is why nothing
here is a "friends with" list on the user: mutual means both names are on the
same row and the row says who asked.

encouragements holds what one person said about another's workout: a wordless
cheer, or a note somebody typed. The cheer limit is a partial unique index
rather than a plain constraint, because one cheer each is the rule and notes
have no such limit.

user_progress.renown counts what encouraging other people has been worth to
the person who did it. It is never read back by any response: the API says
which flourish stage a border wears and never the number behind it. Nothing is
backfilled, because before this migration nobody had encouraged anybody.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# native_enum off, as everywhere else here: both databases store a plain
# VARCHAR with a check constraint, and Postgres never grows an enum type that
# a later release would have to alter.
_FRIENDSHIP_STATUS = sa.Enum("pending", "accepted", name="friendship_status", native_enum=False)
_ENCOURAGEMENT_KIND = sa.Enum("cheer", "note", name="encouragement_kind", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "friendships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "requester_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "addressee_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", _FRIENDSHIP_STATUS, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        # One invite per direction. The reverse direction is allowed to exist
        # as a row and is refused by the endpoint instead, so that two people
        # asking each other at once is a no-op rather than an error.
        sa.UniqueConstraint("requester_id", "addressee_id", name="uq_friendship"),
    )

    op.create_table(
        "encouragements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workout_id",
            sa.Integer(),
            sa.ForeignKey("workouts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "from_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # The workout's owner, denormalised so a person's own post bag is one
        # query rather than a join through their whole history.
        sa.Column(
            "to_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", _ENCOURAGEMENT_KIND, nullable=False),
        sa.Column("body", sa.String(500), nullable=True),
        sa.Column("earned_renown", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Partial, so it binds cheers only. Both databases take this spelling.
    op.create_index(
        "uq_encouragement_cheer",
        "encouragements",
        ["workout_id", "from_user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'cheer'"),
        sqlite_where=sa.text("kind = 'cheer'"),
    )
    # The seven day diminishing window, which is a lookup for one pair and one
    # kind over a short stretch of time.
    op.create_index(
        "ix_encouragement_pair",
        "encouragements",
        ["from_user_id", "to_user_id", "kind", "created_at"],
    )

    op.add_column(
        "user_progress",
        sa.Column("renown", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Drops every friendship and everything anybody said. Neither is derivable
    from anything else, so this is not reversible in any real sense; it is here
    so the revision can be stepped back on a test database."""
    op.drop_column("user_progress", "renown")
    op.drop_index("ix_encouragement_pair", table_name="encouragements")
    op.drop_index("uq_encouragement_cheer", table_name="encouragements")
    op.drop_table("encouragements")
    op.drop_table("friendships")
