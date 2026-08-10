"""a line or two about yourself

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-10

One column on users, additive and the same statement on both engines, so it
runs on a database that has been live since 0001 exactly as it runs on a fresh
one.

Nullable and nothing backfilled: an account that has not written a bio has no
bio, and null is what the rest of the optional text on a user row already
means. Two hundred characters because this sits under a name on the profile
screens rather than being a page of its own; the application checks the length
on every write, and the column is the second answer rather than the first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("bio", sa.String(200), nullable=True))


def downgrade() -> None:
    """Drops the column. The earlier release neither reads nor writes a bio, so
    nothing it needs goes with it."""
    op.drop_column("users", "bio")
