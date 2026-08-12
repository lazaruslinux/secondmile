"""bug reports: a dropbox for what went wrong

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-12

One table, and deliberately the plainest one in the schema. No status column
and no read flag: a report is a thing somebody typed, the answer to it is a
release, and a column saying "seen" would be a promise the app never made to
whoever sent it.

The three stamped fields are here rather than left to the client: the account
comes from the session, the moment comes from the server's clock, and the
browser string comes from the request's own header. Only the text and the
screen name arrive in the body, which is what the Settings card discloses.

Additive, so it runs on a live database without touching a row of it, and the
downgrade takes the whole table away because nothing else refers to it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bug_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.String(length=2000), nullable=False),
        sa.Column("view", sa.String(length=32), nullable=False),
        # Nullable: a request may carry no User-Agent at all, and inventing a
        # string for one would be the row telling a small lie.
        sa.Column("user_agent", sa.String(length=300), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("bug_reports")
