"""a video on a workout

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-11

One new table, shaped like the photo table 0011 added and for the same
reasons. Purely additive, so it runs on a database that has been live since
0001 exactly as it runs on a fresh one, and every workout that existed before
it keeps working with nothing attached.

The row holds no file name, no duration, and no size. A video lives at
<VIDEO_DIR>/<workout_id>-<id>.mp4 with its poster frame beside it as
<workout_id>-<id>.jpg, both built from the two ids, so moving the directory is
a config change rather than an UPDATE over every row, and nothing an uploader
sent ever reaches a path. What the file is, is the file's business.

One video per workout is the application's rule and is not written here as a
unique constraint: the six-slot media cap it sits inside is a count across two
tables that no constraint can express either, so both live in the upload
endpoint where they can be read together.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workout_videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Deleting the workout takes its video's row with it, as it does the
        # pictures'. The files are removed by the endpoint that deletes them;
        # an orphaned file is a tidy-up, an orphaned row would be a broken page.
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
    """Drops every video row. The files under VIDEO_DIR are left alone: nothing
    here should delete somebody's videos."""
    op.drop_table("workout_videos")
