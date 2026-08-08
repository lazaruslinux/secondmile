"""one of each species, and the duplicates folded into it

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-07

No schema changes. The rule is new and the rolls obey it from here on, so this
is the one-off tidy of what the old rolls already handed out.

Plantings: per account and species, the one that went in the ground first is
kept and every later one is added into it. Nothing is thrown away, so a second
strawberry that grew forty Miles becomes forty Miles on the first strawberry
and the plot reads as one plant that has come a long way. matured_at keeps the
keeper's own date, or the earliest one among the rows folded in when it has
none; it is bookkeeping either way, since the level is worked out from the
miles.

Satchel: an unused seed of something already growing turns into water, keeping
its rarity, because water is what that slot would hand over now. A species with
nothing in the ground keeps exactly one unused seed and the rest become water
the same way. Spent seeds are never touched: they are the plantings above.

There is no downgrade. Merged growth cannot be taken apart again, and a restore
point is what covers a release that has to go back.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    _merge_plantings(connection)
    _tidy_satchel(connection)


def _merge_plantings(connection) -> None:
    """Fold every duplicate planting into the oldest one of its species."""
    rows = connection.execute(
        sa.text(
            "SELECT id, user_id, species, growth_mi, matured_at FROM plantings"
            # Ordered in the database so the timestamps are compared as
            # timestamps on either engine; the keeper is the first of a group.
            " ORDER BY user_id, species, planted_at, id"
        )
    ).all()

    groups: dict[tuple[int, str], list] = {}
    for row in rows:
        groups.setdefault((row.user_id, row.species), []).append(row)

    for group in groups.values():
        if len(group) < 2:
            continue
        keeper, folded = group[0], group[1:]
        growth = keeper.growth_mi + sum(row.growth_mi or 0.0 for row in folded)
        matured = keeper.matured_at
        if matured is None:
            dates = sorted(row.matured_at for row in folded if row.matured_at is not None)
            matured = dates[0] if dates else None
        connection.execute(
            sa.text(
                "UPDATE plantings SET growth_mi = :growth, matured_at = :matured"
                " WHERE id = :id"
            ),
            {"growth": growth, "matured": matured, "id": keeper.id},
        )
        connection.execute(
            sa.text("DELETE FROM plantings WHERE id = :id"),
            [{"id": row.id} for row in folded],
        )


def _tidy_satchel(connection) -> None:
    """Turn every unused seed the plot has no room for into water."""
    planted = {
        (user_id, species)
        for user_id, species in connection.execute(
            sa.text("SELECT DISTINCT user_id, species FROM plantings")
        ).all()
    }
    rows = connection.execute(
        sa.text(
            "SELECT id, user_id, species FROM satchel_items"
            " WHERE kind = 'seed' AND used_at IS NULL AND species IS NOT NULL"
            " ORDER BY user_id, species, acquired_at, id"
        )
    ).all()

    groups: dict[tuple[int, str], list] = {}
    for row in rows:
        groups.setdefault((row.user_id, row.species), []).append(row)

    for key, group in groups.items():
        # Nothing of it in the ground yet, so the oldest seed of it is still
        # worth planting; everything after that one is a duplicate.
        spare = group if key in planted else group[1:]
        if not spare:
            continue
        connection.execute(
            # The rarity stays: what the slot was worth is what the water is
            # worth, and nothing here re-rolls a chest that is long since open.
            sa.text(
                "UPDATE satchel_items SET kind = 'water', species = NULL WHERE id = :id"
            ),
            [{"id": row.id} for row in spare],
        )


def downgrade() -> None:
    """Nothing to undo.

    The duplicate plantings were added into their keepers and deleted, and the
    spare seeds became water; neither can be worked back out of what is left.
    A release that has to go back goes back to the restore point taken before
    this ran, which is the only thing that ever held the old rows.
    """
