"""how far a plant had grown when the letter was last put down

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-11

One nullable column on plantings, additive and the same statement on both
engines, so it runs on a database that has been live since 0001 exactly as it
runs on a fresh one.

The recorded level 0014 writes cannot tell a seed in the ground from a plant
half way up: both stand at level zero, and the drawing changes a third of the
way to level one. The letter now names the crossings, so it needs the growth
itself and not the level worked out from it.

This one IS backfilled, and 0014's reason for not backfilling does not apply:
copying growth_mi across needs no catalogue and computes nothing, so there is
no frozen copy of the species table to go stale. The backfill is what keeps the
first letter after the release quiet, and it is the strict version of quiet: a
plant is recorded exactly where it stands, so nothing it did before today can
read as a crossing. Old news is not news.

Null stays possible for a row written between this migration and the release
that fills the column in, and a plant with nothing recorded says nothing about
its stage, the same rule the level follows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plantings", sa.Column("growth_at_ack", sa.Float(), nullable=True))
    # Every plant is recorded where it stands, so the first letter after this
    # tells no old news.
    op.execute("UPDATE plantings SET growth_at_ack = growth_mi")


def downgrade() -> None:
    """Drops the recorded growth. The older release never read it, and the
    levels it does read are untouched, so nothing it needs goes with them."""
    op.drop_column("plantings", "growth_at_ack")
