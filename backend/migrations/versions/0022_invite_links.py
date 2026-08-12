"""invite links: never expiring, revocable, and able to make a friendship

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-11

Three changes to one table, all of them things the old shape could not say.

expires_at becomes nullable, and null means it never expires. A link somebody
texts to their brother is not a thing to put a fortnight's clock on: it is
single use, so the code stops working the moment it is spent, and that is the
only ending it needs. Codes already in the table keep the date they were minted
with, so nothing that was going to expire stops expiring.

revoked_at is how a link is taken back before anybody spends it. A separate
column rather than a flag on used_by: those are two different endings, and a
row has to be able to say which one it met.

auto_friend says whether claiming the code also makes the two accounts friends.
Existing rows get false, which is the truth about every one of them: they came
out of the command line, where an invite is an account gate and nothing more.

Every one of the three is a column change rather than a table rebuild on
Postgres. SQLite has no ALTER COLUMN at all, so the nullable change runs
through batch mode, which copies the table; the other two are plain additions
either way.
"""

import datetime as dt
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# What a link with no date of its own is given if this migration is ever
# stepped back down. Far enough away that a code somebody is holding still
# works, rather than the alternative of stamping it with a date in the past and
# killing every unclaimed link on the way down.
FAR_FUTURE = dt.datetime(2099, 1, 1, tzinfo=dt.timezone.utc)


def upgrade() -> None:
    op.add_column("invites", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "invites",
        sa.Column(
            "auto_friend",
            sa.Boolean(),
            nullable=False,
            # Only so the existing rows have something to be. The application
            # sends the value on every insert, so the default is not part of
            # the shape and comes straight back off.
            server_default=sa.false(),
        ),
    )
    with op.batch_alter_table("invites") as batch:
        batch.alter_column("expires_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch.alter_column("auto_friend", existing_type=sa.Boolean(), server_default=None)


def downgrade() -> None:
    """Puts the date back on every link that had none, then takes the two
    columns away. A revoked link stops being revoked, which the older release
    would not have read anyway."""
    invites = sa.table("invites", sa.column("expires_at", sa.DateTime(timezone=True)))
    op.execute(
        invites.update().where(invites.c.expires_at.is_(None)).values(expires_at=FAR_FUTURE)
    )
    with op.batch_alter_table("invites") as batch:
        batch.alter_column("expires_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    op.drop_column("invites", "auto_friend")
    op.drop_column("invites", "revoked_at")
