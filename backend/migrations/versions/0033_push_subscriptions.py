"""push: where a phone asked to be told, and whether an account wants telling

Revision ID: 0033
Revises: 0032

One new table and one new switch, both additive; nothing existing is read or
rewritten.

push_subscriptions holds what one browser handed over when its owner turned
notifications on for that device: the push service URL it minted for the
device, and the key pair payloads must be encrypted to. The endpoint is unique
across accounts because the push service mints it per device, so two rows with
one endpoint would be one phone notified twice.

notify_workout_arrival is the account-wide off switch, on by default because a
device only ever subscribes by its owner's own hand and rows without the
switch predate the feature: they should behave like everyone else the moment
one of their devices subscribes.

Stepping back drops both, which forgets the subscriptions: every device would
have to be turned back on by hand. Nothing else is lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(255), nullable=False),
        sa.Column("auth", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column(
        "users",
        sa.Column(
            "notify_workout_arrival",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notify_workout_arrival")
    op.drop_table("push_subscriptions")
