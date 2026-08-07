"""route lines for workouts

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-07

One new table. Health Auto Export can attach a GPS trace to every workout it
sends, and the feed draws it as a plain line on the card. What is stored is
never the trace as it arrived: both ends are trimmed away and the rest is
thinned to at most two hundred points before it reaches this table, so a route
here cannot say where its owner lives. app/routemaps.py holds that work.

Routes already sitting in the ingest log are NOT backfilled here: replaying
them means parsing stored payloads, which is a command rather than a schema
change. Do it per account with

    docker compose exec backend python manage.py backfill-routes theirname
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workout_routes",
        # The workout id is the key: one line per workout, and deleting the
        # workout takes the line with it.
        sa.Column(
            "workout_id",
            sa.Integer(),
            sa.ForeignKey("workouts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # JSON rather than JSONB, as everywhere else here: SQLite runs this file
        # too, and nothing ever queries inside the array.
        sa.Column("points", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    """Drops every stored line. They are rebuildable from the ingest log with
    backfill-routes after an upgrade, so nothing is lost that cannot come back."""
    op.drop_table("workout_routes")
