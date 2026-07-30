"""email signups and verification

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-30

Purely additive, because this runs on databases that already hold real
accounts: two new nullable-or-defaulted columns on users and one new table.
Nothing existing is rewritten or dropped, so the upgrade is the same short
statement list on a fresh database and on one that has been live since 0001.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # A unique index rather than a unique constraint: SQLite cannot add a
    # constraint to an existing table, and both databases leave NULLs out of a
    # unique index, which is what lets every command-line account keep having no
    # address at all.
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    # Accounts that existed before this migration were created by invite or from
    # the command line, which is a stronger check than an email round trip. They
    # are marked verified so an upgrade does not lock out the people already
    # using the instance. On a fresh database this touches nothing.
    op.execute(sa.text("UPDATE users SET email_verified = true"))
    op.create_table(
        "email_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("purpose", sa.String(16), nullable=False, server_default="verify"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("email_tokens")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "email")
