"""gear: the shoes a walk or a run was done in

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-13

One table and one column, both additive, so this runs on a database that has
been live since 0001 exactly as it runs on a fresh one. Nothing already stored
is read or rewritten: every workout arrives wearing nothing, which is the truth
about a history recorded before there was anywhere to say otherwise. Whatever
gear anybody wants recorded against their old activities is theirs to enter and
assign afterwards, and no migration invents it for them.

There is no mileage column anywhere here, deliberately. What a pair has covered
is starting_mi plus the raw distance of the workouts still assigned to it,
summed on every read, so a deleted workout takes its miles back off the shoe and
a restored one brings them back with nothing to keep in step.

The workouts column is nullable and its key is ON DELETE SET NULL: deleting a
pair of shoes must never delete a workout. The key is added on Postgres and left
off on SQLite, which cannot alter a constraint; the column itself is identical
on both, and the model metadata the test suite builds from declares the key.

Nothing in the game is touched. No experience, chest, medal, grove, renown,
manna or fruit reads a row in this table, and stepping back drops both the
column and the table without any number anywhere moving.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gear",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Only "shoes" is written today; the column is here so bikes need no
        # migration that reshapes what is already stored.
        sa.Column(
            "kind", sa.String(length=16), nullable=False, server_default="shoes"
        ),
        # "mens" or "womens", which is what the size and width lists are offered
        # against rather than a statement about anybody.
        sa.Column("style", sa.String(length=6), nullable=False),
        sa.Column("brand", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("nickname", sa.String(length=60), nullable=True),
        # US sizing runs in half steps, so a float rather than an integer.
        sa.Column("size", sa.Float(), nullable=False),
        sa.Column("width", sa.String(length=2), nullable=False),
        # Wear the app never saw, added to what the assigned workouts come to.
        sa.Column(
            "starting_mi", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("replace_around_mi", sa.Float(), nullable=True),
        # At most one per account, enforced in the router: setting one clears
        # the rest in the same statement.
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column("workouts", sa.Column("gear_id", sa.Integer(), nullable=True))
    # The key itself, on the databases that can be told about one after the
    # fact. SQLite cannot alter constraints at all, and rebuilding the workouts
    # table to add one would mean recreating every unnamed check constraint the
    # activity and source columns carry; the tests are the only place SQLite
    # ever runs a migration, and the model metadata they build from declares the
    # key, so nothing goes untested by leaving it off here.
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_workouts_gear_id",
            "workouts",
            "gear",
            ["gear_id"],
            ["id"],
            ondelete="SET NULL",
        )
    # The mileage on a pair is summed off this column on every profile read.
    op.create_index("ix_workouts_gear_id", "workouts", ["gear_id"])


def downgrade() -> None:
    op.drop_index("ix_workouts_gear_id", table_name="workouts")
    op.drop_column("workouts", "gear_id")
    op.drop_table("gear")
