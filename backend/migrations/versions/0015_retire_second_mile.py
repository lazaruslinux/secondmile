"""the Second Mile stops being a medal

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-08

No schema changes. The Second Mile fired at twenty raw miles in a week, which
sits between the fifteen and the twenty-five: a fifth weekly rung wearing a
special name rather than an achievement of its own. It leaves the catalogue,
and its history has to leave with it, because a medal no release defines would
sit in the profile counting toward nothing forever.

Two things to clear. Its weekly earns are rows of a family of one, so the id
names them exactly and they are deleted outright; no other family shares them.
The badge slots are a JSON list, so they are read, filtered and written back
the way 0012 does it rather than in SQL: the two databases spell JSON array
surgery differently and neither spelling is worth learning to drop one id. What
is left keeps the order it was chosen in, since that is the order it is worn.

The name is not what is being retired. The app is called after it and a week's
distance still gilds by it; this is the medal alone.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out rather than imported, for the reason 0012 gives: a migration has
# to keep doing what it did on the day it ran, and a catalogue is retuned.
_RETIRED = "second_mile"


def upgrade() -> None:
    connection = op.get_bind()

    connection.execute(
        sa.text("DELETE FROM weekly_badge_earns WHERE badge_id = :badge").bindparams(
            badge=_RETIRED
        )
    )

    for user_id, raw in connection.execute(
        sa.text("SELECT id, displayed_badges FROM users")
    ).all():
        current = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(current, list) or _RETIRED not in current:
            continue
        connection.execute(
            # A typed bind, so each database serializes the list into its own
            # JSON column spelling.
            sa.text(
                "UPDATE users SET displayed_badges = :badges WHERE id = :user_id"
            ).bindparams(
                sa.bindparam(
                    "badges",
                    value=[badge for badge in current if badge != _RETIRED],
                    type_=sa.JSON(),
                ),
                sa.bindparam("user_id", value=user_id),
            )
        )


def downgrade() -> None:
    """Nothing to put back.

    The weeks the medal was earned in are still there, so the earlier release
    earns it again from the same history: its backfill writes a row wherever
    twenty miles were run. The slots are left alone for the same reason a slot
    is only worth filling once something owns what is in it.
    """
