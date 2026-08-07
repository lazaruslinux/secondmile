"""diamond sports on the profile

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-06

One nullable column. Null is not a missing value here, it is the default the
profile ships with: the three diamonds are picked for you from your own
lifetime miles until you choose them yourself, and choosing null again is how
you go back to that.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # JSON rather than JSONB, and no server default, for the same reasons the
    # earlier migrations give: SQLite runs this file too, and null carries
    # meaning that an empty list would not.
    op.add_column("users", sa.Column("diamond_sports", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "diamond_sports")
