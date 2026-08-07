"""names, birthdates, and an address waiting to be confirmed

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-07

Five nullable columns on users and nothing else. Purely additive, so it runs the
same on a database that has been live since 0001 as on a fresh one, and every
account that existed before it keeps working with all five empty.

pending_email is deliberately not unique. Two accounts are allowed to ask for
the same address; only the one that answers its mail first may have it, and that
is checked when the swap happens rather than when the request is made, because
refusing here would say out loud that the address already belongs to somebody.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(40), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(40), nullable=True))
    # A date rather than an age: an age stored beside a birthdate is a second
    # copy of the same fact that starts drifting on the next birthday.
    op.add_column("users", sa.Column("birthdate", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("gender", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("pending_email", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "pending_email")
    op.drop_column("users", "gender")
    op.drop_column("users", "birthdate")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
