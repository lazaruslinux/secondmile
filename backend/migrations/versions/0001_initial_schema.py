"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-30

Everything M1 needs, in one migration. Types are chosen to run unchanged on
both databases this project meets: Postgres in production, SQLite under the
test suite. That rules out JSONB and native enum types, neither of which SQLite
has, in exchange for portability that costs nothing at this size.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# native_enum off renders as VARCHAR plus a check constraint on both databases.
# A real Postgres enum type would be tidier to read and a chore to alter later.
_activity = sa.Enum("walk", "run", "cycle", "swim", name="activity", native_enum=False)
_source = sa.Enum("sync", "manual", name="workout_source", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(32), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("units", sa.String(16), nullable=False, server_default="imperial"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("used_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ingest_tokens",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, index=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("activity", _activity, nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("distance_mi", sa.Float(), nullable=False, server_default="0"),
        sa.Column("active_kcal", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_hr", sa.Float(), nullable=True),
        sa.Column("source", _source, nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # The idempotency key. Enforced by the database rather than by a lookup
        # before each insert, because a lookup loses the race against a second
        # sync arriving at the same moment.
        sa.UniqueConstraint("user_id", "start_ts", "duration_s", name="uq_workout"),
    )
    op.create_table(
        "ingest_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ingest_log")
    op.drop_table("workouts")
    op.drop_table("ingest_tokens")
    op.drop_table("sessions")
    op.drop_table("invites")
    op.drop_table("users")
