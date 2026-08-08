"""the level a plant stood at when the letter was last put down

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-08

One nullable column on plantings. Purely additive and the same statement on
both engines, so it runs on a database that has been live since 0001 exactly
as it runs on a fresh one, and every planting that existed before it keeps
working with the column empty.

The letter used to say what grew by taking the workouts that arrived since the
last acknowledgement back off a plant's growth and reading the old level off
the rest. That is exact for workouts and blind to water: nothing records which
planting a water item was poured into, so a level that water alone paid for was
never announced. From here the level is written down when the letter is
acknowledged and the next letter compares against it, which stays true however
a future release grows a plant.

Existing rows arrive null rather than backfilled, and the letter says nothing
about a plant whose level it does not know. Working one out here would mean
this file carrying its own copy of the species catalogue, and 0012 says why a
migration must not: a catalogue is retuned, and a frozen copy would have this
one computing levels the release disagrees with. Reading a missing number as
zero instead would announce every plant somebody already has, all at once, in
the first letter after the release. One quiet letter is the cheaper wrong, and
acknowledging it writes every number.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plantings", sa.Column("level_at_ack", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drops the recorded levels. The older release works them out by
    subtraction again, so nothing it needs goes with them."""
    op.drop_column("plantings", "level_at_ack")
