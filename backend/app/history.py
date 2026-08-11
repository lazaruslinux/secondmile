"""What happens to a workout after its owner deletes it.

Two things, and they are the two halves of one promise. For
DELETED_WORKOUT_RETENTION_DAYS the row is only hidden, and the Log's Deleted
section can hand it back whole. After that the pictures, the video, the route
line, the words and everything said about it are purged, and what is left is a
tombstone: the workout row itself, kept forever so the sync dedupe key on it
goes on refusing the same session when the phone offers it again.

The purge runs on the account's own next sync, the way the ingest log is
pruned, so nothing here needs a scheduler to be true.
"""

import datetime as dt

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import models, photos, videos
from app.config import DELETED_WORKOUT_RETENTION_DAYS
from app.security import now_utc

WINDOW = dt.timedelta(days=DELETED_WORKOUT_RETENTION_DAYS)


def cutoff(moment: dt.datetime | None = None) -> dt.datetime:
    """The moment a deletion has to be after to still be undoable."""
    return (moment or now_utc()) - WINDOW


def days_left(deleted_at: dt.datetime, moment: dt.datetime | None = None) -> int:
    """How many whole days are left to change your mind, never below zero.

    Rounded up, so the day somebody is standing in counts: a workout deleted a
    few minutes ago has the whole window rather than one day less than it.
    """
    remaining = (deleted_at + WINDOW) - (moment or now_utc())
    if remaining <= dt.timedelta(0):
        return 0
    return -(-remaining // dt.timedelta(days=1))


def deleted_workouts(db: Session, user_id: int) -> list[models.Workout]:
    """One account's deleted workouts that can still be restored, newest first.

    Bounded by the window rather than by a purged marker on the row. A workout
    past it is gone whether or not the account has synced since, which is what
    the dialog promised, and reading the date is one fewer column than writing
    down that the promise was kept.
    """
    return list(
        db.execute(
            select(models.Workout)
            .where(
                models.Workout.user_id == user_id,
                models.Workout.deleted_at.is_not(None),
                models.Workout.deleted_at > cutoff(),
            )
            # By id within a stamp, the tie-break every other list of workouts
            # uses, so two deleted in one go keep a stable order between reads.
            .order_by(models.Workout.deleted_at.desc(), models.Workout.id.desc())
        ).scalars()
    )


def purge_expired(db: Session, user_id: int) -> int:
    """Throw away what is left of this account's long-deleted workouts.

    The ingest log's prune, one table over: this account's own rows, on this
    account's own sync, in the caller's transaction, so the table stays bounded
    with no scheduled job in the install.

    Everything with a size goes: the pictures and the video with their files,
    the route line, the title and the post, and every cheer and note written on
    it. What stays is the row, which is a couple of dozen bytes and is the only
    thing standing between a catch-up export and importing the whole workout
    again. Renown is not touched: words that were given were given, and the
    total they earned is stored on the giver rather than counted from here.

    Answers with how many workouts it emptied. Does not commit.
    """
    expired = list(
        db.execute(
            select(models.Workout).where(
                models.Workout.user_id == user_id,
                models.Workout.deleted_at.is_not(None),
                models.Workout.deleted_at <= cutoff(),
                # Nothing left to take off a row already purged, and a purged
                # workout keeps neither, so this is what stops the sweep
                # walking the whole tombstone history on every sync.
                (
                    models.Workout.title.is_not(None)
                    | models.Workout.post.is_not(None)
                    | models.Workout.id.in_(select(models.WorkoutPhoto.workout_id))
                    | models.Workout.id.in_(select(models.WorkoutVideo.workout_id))
                    | models.Workout.id.in_(select(models.WorkoutRoute.workout_id))
                    | models.Workout.id.in_(select(models.Encouragement.workout_id))
                ),
            )
        ).scalars()
    )
    for workout in expired:
        for photo_id in db.execute(
            select(models.WorkoutPhoto.id).where(
                models.WorkoutPhoto.workout_id == workout.id
            )
        ).scalars():
            photos.remove(workout.id, photo_id)
        for video_id in db.execute(
            select(models.WorkoutVideo.id).where(
                models.WorkoutVideo.workout_id == workout.id
            )
        ).scalars():
            videos.remove(workout.id, video_id)
        # After the files, and by workout rather than by row: the row is what
        # says a picture exists, so a file that will not go is an admin problem
        # rather than a reason to leave the row behind pointing at it.
        db.execute(
            delete(models.WorkoutPhoto).where(
                models.WorkoutPhoto.workout_id == workout.id
            )
        )
        db.execute(
            delete(models.WorkoutVideo).where(
                models.WorkoutVideo.workout_id == workout.id
            )
        )
        db.execute(
            delete(models.WorkoutRoute).where(
                models.WorkoutRoute.workout_id == workout.id
            )
        )
        db.execute(
            delete(models.Encouragement).where(
                models.Encouragement.workout_id == workout.id
            )
        )
        workout.title = None
        workout.post = None
    return len(expired)
