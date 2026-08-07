"""titles, posts, and photos on a workout

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-07

Two nullable columns on workouts and one new table. Purely additive, so it runs
the same on a database that has been live since 0001 as on a fresh one, and
every workout that existed before it keeps working with both columns empty.

Nothing here can change what a workout was. Distance, duration, and start time
stay exactly as they arrived: what this migration adds is the words and the
pictures around them, which is the only part a person is allowed to author.

The photo table holds no file name. A picture lives at
<PHOTO_DIR>/<workout_id>-<id>.webp, built from the two ids, so moving the
directory is a config change rather than an UPDATE over every row, and nothing
an uploader sent ever reaches a path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workouts", sa.Column("title", sa.String(100), nullable=True))
    op.add_column("workouts", sa.Column("post", sa.String(2000), nullable=True))

    op.create_table(
        "workout_photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Deleting the workout takes its pictures' rows with it. The files
        # themselves are removed by the endpoint that deletes them; an orphaned
        # file is a tidy-up, an orphaned row would be a broken page.
        sa.Column(
            "workout_id",
            sa.Integer(),
            sa.ForeignKey("workouts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drops every title, post, and photo row. The files under PHOTO_DIR are
    left alone: nothing here should delete somebody's pictures."""
    op.drop_table("workout_photos")
    op.drop_column("workouts", "post")
    op.drop_column("workouts", "title")
