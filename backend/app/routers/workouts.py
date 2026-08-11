"""The workout history and the weekly totals behind the Almanac.

Nothing here creates a workout. They arrive on the sync path and only there, so
one account has one way in and every row can say where it came from.
"""

import datetime as dt
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Straight from starlette: the multipart parser produces starlette's UploadFile,
# and an isinstance check against fastapi's subclass would refuse every real
# upload.
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from app import activity as activity_rules
from app import (
    fellowship,
    history,
    images,
    medals,
    models,
    photos,
    progress,
    security,
    throttle,
    videos,
)
from app.config import (
    MAX_MEDIA_PER_WORKOUT,
    MAX_PHOTO_BYTES,
    MAX_VIDEO_BYTES,
    MAX_VIDEOS_PER_WORKOUT,
    NOTE_MAX_CHARS,
    WORKOUT_POST_MAX_CHARS,
    WORKOUT_TITLE_MAX_CHARS,
)
from app.db import get_db
from app.models import ACTIVITIES

router = APIRouter(prefix="/workouts", tags=["workouts"])

# High enough that nobody paging through a real history notices, low enough that
# a single request cannot ask the server to serialise everything at once.
MAX_LIMIT = 200
MAX_WEEKS = 52

PHOTO_TOO_LARGE = (
    "That photo is too large. "
    f"The limit is {MAX_PHOTO_BYTES // (1024 * 1024)} MB."
)
VIDEO_TOO_LARGE = (
    "That video is too large. "
    f"The limit is {MAX_VIDEO_BYTES // (1024 * 1024)} MB."
)
# One sentence for the shared cap, because a photo and a video fill the same
# slot and being told about photos while adding a video would be a lie.
MEDIA_FULL = f"A workout can hold {MAX_MEDIA_PER_WORKOUT} photos and videos."
VIDEOS_FULL = "A workout can hold one video."
NO_SUCH_WORKOUT = "No such workout."
NO_SUCH_PHOTO = "No such photo."
NO_SUCH_VIDEO = "No such video."

# What the history can be ordered by, and which way. Date is the default and the
# one the weekly groups are built on; the other three are the dashboard's, for
# finding the shortest walk or the hardest run in a year of them.
WORKOUT_SORTS = ("date", "distance", "pace", "avg_hr")
SORT_ORDERS = ("asc", "desc")
# The two that can have nothing in them: a workout with no distance has no pace,
# and plenty of rows never carried a heart rate.
NULLABLE_SORTS = ("pace", "avg_hr")


def _serialize(
    workout: models.Workout,
    person: dict,
    encouragement: dict,
    medal_ids: list[str] | None = None,
    has_route: bool = False,
    photo_ids: list[int] | None = None,
    video_ids: list[int] | None = None,
) -> dict:
    """One row of your own history, in the shape the feed sends a workout in.

    The Activity tab draws the same card the home feed draws, so it is served
    the same row: whoever did the workout, what it earned, and what came back
    for it. Own rows carry everything, so nothing here is ever kept back.

    The flags are the one thing the feed has no use for and the Activity tab
    does. They are the server's own doubts about the numbers, said to nobody but
    the person whose numbers they are, which is why they are added here rather
    than in feed_row.

    The route itself is not here, only whether there is one: a list has a couple
    of hundred coordinate pairs on it, and a page of history would be mostly
    route for a view that draws none of them until it is scrolled to.
    """
    return {
        **fellowship.feed_row(
            workout,
            person,
            True,
            medal_ids or [],
            has_route,
            photo_ids or [],
            video_ids or [],
            encouragement,
        ),
        "flags": workout.flags or {},
    }


def routes_for(db: Session, workouts: list[models.Workout]) -> set[int]:
    """Which of these workouts have a stored route line. One query for the page."""
    ids = [row.id for row in workouts]
    if not ids:
        return set()
    return set(
        db.execute(
            select(models.WorkoutRoute.workout_id).where(models.WorkoutRoute.workout_id.in_(ids))
        ).scalars()
    )


def photos_for(db: Session, workouts: list[models.Workout]) -> dict[int, list[int]]:
    """The photo ids on each of these workouts, oldest first. One query for the
    page, like the two above. Ordered by id, which is the order they were added
    in, so a card lays them out the same way twice."""
    ids = [row.id for row in workouts]
    if not ids:
        return {}
    found: dict[int, list[int]] = {}
    for workout_id, photo_id in db.execute(
        select(models.WorkoutPhoto.workout_id, models.WorkoutPhoto.id)
        .where(models.WorkoutPhoto.workout_id.in_(ids))
        .order_by(models.WorkoutPhoto.id)
    ):
        found.setdefault(workout_id, []).append(photo_id)
    return found


def videos_for(db: Session, workouts: list[models.Workout]) -> dict[int, list[int]]:
    """The video ids on each of these workouts, one query for the page.

    A list rather than a single id even though a workout holds one video: it is
    the photo shape, so the rows, the payloads, and the strip all count media
    the same way, and the one-per-workout rule lives in the upload endpoint
    where it can be read.
    """
    ids = [row.id for row in workouts]
    if not ids:
        return {}
    found: dict[int, list[int]] = {}
    for workout_id, video_id in db.execute(
        select(models.WorkoutVideo.workout_id, models.WorkoutVideo.id)
        .where(models.WorkoutVideo.workout_id.in_(ids))
        .order_by(models.WorkoutVideo.id)
    ):
        found.setdefault(workout_id, []).append(video_id)
    return found


def _media_held(db: Session, workout_id: int) -> int:
    """How many of the workout's media slots are already spent, photos and
    videos together. Both tables, because the cap is one number over the two."""
    return (
        db.execute(
            select(func.count())
            .select_from(models.WorkoutPhoto)
            .where(models.WorkoutPhoto.workout_id == workout_id)
        ).scalar_one()
        + db.execute(
            select(func.count())
            .select_from(models.WorkoutVideo)
            .where(models.WorkoutVideo.workout_id == workout_id)
        ).scalar_one()
    )


def parse_cursor(before: str) -> dt.datetime:
    """The paging cursor, which is the start_ts of the last row of the page.

    The second attempt exists because a timestamp carrying a "+00:00" offset has
    to be percent-encoded in a query string, and a client that forgets receives
    the offset back as a space. That is one of the easiest integration mistakes
    to make and one of the most confusing to diagnose, since it only ever breaks
    the second page.
    """
    for candidate in (before, before.replace(" ", "+")):
        try:
            return activity_rules.ensure_aware(dt.datetime.fromisoformat(candidate))
        except ValueError:
            continue
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "before must be an ISO timestamp.")


def sort_key(sort: str):
    """What one of the four sorts actually orders on.

    Pace is the only one that is not a column. It is time over distance, and a
    workout that covered no distance has no pace at all rather than an infinite
    one, so the guard answers null instead of dividing: the same reading the
    cards give when they print a dash.
    """
    if sort == "distance":
        return models.Workout.distance_mi
    if sort == "avg_hr":
        return models.Workout.avg_hr
    if sort == "pace":
        return case(
            (
                models.Workout.distance_mi > 0,
                models.Workout.duration_s / models.Workout.distance_mi,
            ),
            else_=None,
        )
    return models.Workout.start_ts


@router.get("")
def list_workouts(
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    sort: str = "date",
    order: str = "desc",
    activity: str | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """Your own history, newest first unless it is asked for another way.

    Paged by offset rather than by a cursor, which the feed next door uses. A
    cursor has to be a value the ordering key is monotonic in, and three of the
    four sorts here are ordered by something that repeats and can be nothing at
    all: two workouts of the same distance, or a page of rows with no heart
    rate, have no such value between them. Four cursor shapes, two of them
    null-aware and spelled differently on SQLite and Postgres, is a great deal
    of machinery for a personal history: an offset skips at most a few thousand
    of one account's own indexed rows. What offset costs is the honest wobble
    of any offset: a workout deleted while somebody is paging shifts everything
    after it up by one, so the next page can repeat a row or step over one. The
    Activity tab drops repeats by id; a page that skipped one is a refresh away
    from the truth.

    Deleted workouts are never in it whatever it is sorted or filtered by; they
    are in the Deleted section, which is the endpoint under this one.
    """
    if sort not in WORKOUT_SORTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"sort must be one of {', '.join(WORKOUT_SORTS)}."
        )
    if order not in SORT_ORDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "order must be asc or desc.")
    if activity is not None and activity not in ACTIVITIES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"activity must be one of {', '.join(ACTIVITIES)}."
        )

    stmt = select(models.Workout).where(
        models.Workout.user_id == user.id, models.Workout.deleted_at.is_(None)
    )
    if activity is not None:
        stmt = stmt.where(models.Workout.activity == activity)

    key = sort_key(sort)
    ordering = []
    if sort in NULLABLE_SORTS:
        # Nothing sorts last whichever way the list is pointed, written as an
        # ordering key rather than as NULLS LAST: the clause is spelled
        # differently from one database to the next, and false before true is
        # the same answer in Postgres and in SQLite.
        ordering.append(key.is_(None))
    ordering.append(key.asc() if order == "asc" else key.desc())
    # Ordered by id last so that two workouts sharing a start time, a distance
    # or a heart rate keep a stable order between pages; without it, paging can
    # show one twice and skip another.
    stmt = stmt.order_by(*ordering, models.Workout.id.desc()).offset(offset).limit(limit)
    rows = list(db.execute(stmt).scalars())
    earned = medals.medals_for(db, rows)
    routed = routes_for(db, rows)
    pictures = photos_for(db, rows)
    clips = videos_for(db, rows)
    # One card for the whole page: every row here is this account's own.
    person = fellowship.people(db, {user.id})[user.id]
    given = fellowship.counts(db, [row.id for row in rows], user.id)
    return [
        _serialize(
            row,
            person,
            given[row.id],
            earned.get(row.id),
            row.id in routed,
            pictures.get(row.id),
            clips.get(row.id),
        )
        for row in rows
    ]


def _deleted_row(workout: models.Workout) -> dict:
    """One row of the Deleted section: enough to recognise the workout, and how
    long is left to change your mind.

    Deliberately not the feed's row. Nothing here is a card: no medals, no
    encouragement, no pictures and no route, because a deleted workout's media
    endpoints answer 404 to everybody, its owner included, and a row that
    tried to draw a photograph would draw a broken one. What it is, when it
    was, how far it went, and the way back.
    """
    return {
        "workout_id": workout.id,
        "activity": workout.activity,
        "start_ts": workout.start_ts.isoformat(),
        "distance_mi": round(workout.distance_mi, 3),
        "duration_s": workout.duration_s,
        "title": workout.title,
        "deleted_at": workout.deleted_at.isoformat(),
        "days_left": history.days_left(workout.deleted_at),
    }


@router.get("/deleted")
def list_deleted(
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """Your own deleted workouts that can still be got back, newest first.

    Only ever your own: there is no such thing as reading anybody else's, which
    is why this takes no id and has no friend-shaped twin. A workout past the
    window is not here whether or not the purge has swept it yet, because the
    window is what was promised and the sweep is only how it is kept.

    No limiter, the same as the history above it: the Activity tab asks for
    both on every visit, and one of them is not the read to start counting.
    """
    return [_deleted_row(row) for row in history.deleted_workouts(db, user.id)]


@router.get("/{workout_id}/route")
def workout_route(
    workout_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """The stored line for your own workout, or an accepted friend's.

    Fetched on its own rather than with the history because a card only needs it
    once it is on screen. A route is a map of where somebody has been, so the
    reach is exactly the feed's: yours, and the people you have both agreed to,
    minus whoever has said their friends may not see one. The same 404 answers a
    workout with no line, a workout that does not exist, a stranger's, and a
    friend's that is being kept back. Nothing here says which of the four it was.
    A deleted workout is a fifth way to the same sentence, its owner included:
    a friend holding an old address gets nothing, and so does the person who
    deleted it, because the Deleted section draws no map.

    The owner's list is read in the same query as the line, so this cannot be
    answered from the line alone by a later edit that forgets to ask.
    """
    row = db.execute(
        select(
            models.WorkoutRoute.points,
            models.Workout.user_id,
            models.User.hidden_from_friends,
        )
        .join(models.Workout, models.Workout.id == models.WorkoutRoute.workout_id)
        .join(models.User, models.User.id == models.Workout.user_id)
        .where(
            models.WorkoutRoute.workout_id == workout_id,
            models.Workout.deleted_at.is_(None),
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No route for that workout.")
    points, owner_id, kept_back = row
    if owner_id != user.id and (
        "route" in (kept_back or []) or not fellowship.are_friends(db, user.id, owner_id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No route for that workout.")
    return {"points": points}


def _owned(
    db: Session, workout_id: int, user_id: int, *, deleted_too: bool = False
) -> models.Workout:
    """One of your own workouts, or the same 404 a workout that does not exist
    gets. Whose history an id belongs to is not something a caller learns by
    asking for it.

    A deleted one is the same 404 as well, everywhere but the two endpoints
    that are about being deleted: it is hidden from its owner too, so titling
    it or hanging a photograph on it is not a thing to do to it.
    """
    workout = db.get(models.Workout, workout_id)
    if workout is None or workout.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_WORKOUT)
    if workout.deleted_at is not None and not deleted_too:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_WORKOUT)
    return workout


@router.delete("/{workout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workout(
    workout_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Take one of your own workouts out of the game.

    Hidden from everybody at once: your feed, your friends' feeds, your
    profile, the letter, the streak, and every total. What the miles earned is
    worked out again without them, both ways, by rebuild_from_surviving, which
    is where the rule lives about what a deletion may and may not take back.

    Idempotent: deleting a workout that is already deleted answers the same 204
    and leaves the first deletion's date alone, because the window is counted
    from when it was deleted rather than from the last time somebody asked.
    """
    if throttle.workout_delete_limiter.hit(throttle.user_key(user)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many changes just now. Wait a minute."
        )
    workout = _owned(db, workout_id, user.id, deleted_too=True)
    if workout.deleted_at is None:
        workout.deleted_at = security.now_utc()
        db.commit()
        progress.rebuild_from_surviving(db, user.id)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


class DeleteBatch(BaseModel):
    """Which workouts the Select mode had ticked when Delete was pressed."""

    ids: list[int]


# One press deletes what one page of the list can hold several times over. The
# ceiling is here so a batch is a batch rather than an unbounded transaction,
# and it is well past anything the Select mode can put on screen.
MAX_DELETE_BATCH = 200


@router.post("/delete")
def delete_workouts(
    body: DeleteBatch,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """Take several of your own workouts out of the game in one act.

    All of them or none of them. An id that is not yours, does not exist, or is
    already deleted answers the same 404 the single delete answers, for the
    whole call, and nothing is written: a batch that quietly deleted the rows it
    recognised would be a way of asking whether a stranger's id exists.

    One transaction and one rebuild for the batch. Rebuilding per workout would
    be the same arithmetic run n times over the same history and would leave a
    half-deleted account behind if it stopped in the middle.

    Every one of them is individually restorable afterwards, on the same
    thirty-day window and through the same endpoint: this is the single delete
    n times, not a different kind of deletion.

    Answers with the Deleted rows it just made, newest first, so the tab can
    move them into its Deleted list and count them without asking again.
    """
    # One hit for the call, not one per id. The cap is ten of these a minute,
    # which is ten batches rather than ten workouts.
    if throttle.workout_delete_limiter.hit(throttle.user_key(user)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many changes just now. Wait a minute."
        )
    # Ticking the same row twice is the caller's business and not an error; it
    # is one workout either way.
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No workouts were chosen.")
    if len(ids) > MAX_DELETE_BATCH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"That is more than {MAX_DELETE_BATCH} workouts at once.",
        )

    found = list(
        db.execute(
            select(models.Workout).where(
                models.Workout.id.in_(ids),
                models.Workout.user_id == user.id,
                models.Workout.deleted_at.is_(None),
            )
        ).scalars()
    )
    if len(found) != len(ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_WORKOUT)

    moment = security.now_utc()
    for workout in found:
        workout.deleted_at = moment
    db.commit()
    progress.rebuild_from_surviving(db, user.id)
    # The order the Deleted list itself is in: newest deletion first, and these
    # share a moment, so the id settles it exactly as it does there.
    found.sort(key=lambda row: row.id, reverse=True)
    return [_deleted_row(row) for row in found]


@router.post("/{workout_id}/restore")
def restore_workout(
    workout_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Put a deleted workout back, as though it had never gone.

    Everything it earned is earned again by the same rebuild the deletion ran:
    the experience, the level, the medals on it and on its week, the streak.
    The one thing that does not come back is the growth in the plot, because
    the deletion never took it; see rebuild_from_surviving.

    The letter does not re-report it. Its arrival stamp is the day it synced,
    which is behind the last acknowledgement for anything old enough to have
    been deleted and read about already.

    Answers with the whole row in the shape the history sends it, so the
    Activity tab can put the card back without asking for the page again. A workout past the
    window, or one nobody deleted, is the same 404 as a workout that never
    existed.
    """
    if throttle.workout_delete_limiter.hit(throttle.user_key(user)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many changes just now. Wait a minute."
        )
    workout = _owned(db, workout_id, user.id, deleted_too=True)
    # Past the window it is not restorable, whether or not the purge has
    # already been round: what the window promised is what this answers to.
    if workout.deleted_at is None or workout.deleted_at <= history.cutoff():
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_WORKOUT)
    workout.deleted_at = None
    db.commit()
    progress.rebuild_from_surviving(db, user.id)
    return _serialize(
        workout,
        fellowship.people(db, {user.id})[user.id],
        fellowship.counts(db, [workout.id], user.id)[workout.id],
        medals.medals_for(db, [workout]).get(workout.id),
        workout.id in routes_for(db, [workout]),
        photos_for(db, [workout]).get(workout.id),
        videos_for(db, [workout]).get(workout.id),
    )


def _clean_words(sent: str | None, limit: int, what: str) -> str | None:
    """One optional text field: trimmed, length checked, and blank means clear.

    A field somebody has emptied and one they never filled in are the same
    thing, so an empty string is stored as null rather than as an empty string
    every reader would then have to treat as null anyway.
    """
    if sent is None:
        return None
    cleaned = sent.strip()
    if len(cleaned) > limit:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{what} must be at most {limit} characters."
        )
    return cleaned or None


class WorkoutWords(BaseModel):
    """A patch: only the fields that are sent are changed, and an explicit null
    clears one.

    There is no distance, duration, or start time here, and there never will be.
    What happened is not editable; the words around it are the only part a
    person authored.
    """

    title: str | None = None
    post: str | None = None


@router.patch("/{workout_id}")
def update_workout(
    workout_id: int,
    body: WorkoutWords,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Title your own workout and write on it."""
    if throttle.workout_edit_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many edits just now. Wait a minute.")
    workout = _owned(db, workout_id, user.id)
    # Read from the field set rather than the value: a sent null is somebody
    # deleting their post, an omitted field is somebody saving only the title.
    if "title" in body.model_fields_set:
        workout.title = _clean_words(body.title, WORKOUT_TITLE_MAX_CHARS, "A title")
    if "post" in body.model_fields_set:
        workout.post = _clean_words(body.post, WORKOUT_POST_MAX_CHARS, "A post")
    db.commit()
    # The whole row comes back, in the same shape the history sends it, so the
    # card that sent the edit redraws from this without asking again.
    return _serialize(
        workout,
        fellowship.people(db, {user.id})[user.id],
        fellowship.counts(db, [workout.id], user.id)[workout.id],
        medals.medals_for(db, [workout]).get(workout.id),
        workout.id in routes_for(db, [workout]),
        photos_for(db, [workout]).get(workout.id),
        videos_for(db, [workout]).get(workout.id),
    )


@router.post("/{workout_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(
    workout_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Attach a picture to your own workout (app/photos.py stores it).

    The form is parsed by hand so the size cap sits in the parser itself: an
    oversized body is abandoned mid-stream, not spooled to disk and measured
    afterwards (an UploadFile parameter would spool first).
    """
    if throttle.photo_limiter.hit(throttle.client_address(request)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many uploads just now. Wait a minute."
        )
    workout = _owned(db, workout_id, user.id)
    if _media_held(db, workout.id) >= MAX_MEDIA_PER_WORKOUT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, MEDIA_FULL)

    # Content-Length is a claim, checked first to refuse the obvious case
    # cheaply; the parser below enforces the same cap on the actual bytes.
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_PHOTO_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, PHOTO_TOO_LARGE)

    try:
        form = await request.form(max_files=1, max_fields=0, max_part_size=MAX_PHOTO_BYTES)
    except MultiPartException:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, PHOTO_TOO_LARGE) from None
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No photo was uploaded.")
        raw = await upload.read()
    finally:
        await form.close()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No photo was uploaded.")

    # Encoded before the row exists, so something this server will not store
    # never burns an id.
    try:
        encoded = photos.encode(raw)
    except images.RejectedImage as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    photo = models.WorkoutPhoto(workout_id=workout.id, created_at=security.now_utc())
    db.add(photo)
    db.flush()
    try:
        photos.store(workout.id, photo.id, encoded)
    except OSError:
        # No row for a picture that is not on the disk: an id in the list with
        # nothing behind it is a broken card on every later read.
        db.rollback()
        raise
    db.commit()
    return {"id": photo.id}


@router.delete(
    "/{workout_id}/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_photo(
    workout_id: int,
    photo_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Take one of your own pictures back off a workout."""
    if throttle.delete_media_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many changes just now. Wait a minute.")
    _owned(db, workout_id, user.id)
    photo = db.get(models.WorkoutPhoto, photo_id)
    if photo is None or photo.workout_id != workout_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_PHOTO)
    db.delete(photo)
    db.commit()
    # After the row, and never a failure: the row is what says a photo exists,
    # so a file that will not go is an admin problem rather than the caller's.
    photos.remove(workout_id, photo_id)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/{workout_id}/photos/{photo_id}")
def read_photo(
    workout_id: int,
    photo_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> FileResponse:
    """One stored picture, to its owner or to an accepted friend.

    The reach is the feed's, the same as a route line: yours, and the people you
    have both agreed to. A post is a deliberate share, so a friend sees all of
    it. The same 404 answers a photo that does not exist, a stranger's, one on a
    deleted workout, and one the disk has lost; nothing here says which of the
    four it was.
    """
    owner_id = db.execute(
        select(models.Workout.user_id)
        .join(models.WorkoutPhoto, models.WorkoutPhoto.workout_id == models.Workout.id)
        .where(
            models.WorkoutPhoto.id == photo_id,
            models.WorkoutPhoto.workout_id == workout_id,
            models.Workout.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if owner_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_PHOTO)
    if owner_id != user.id and not fellowship.are_friends(db, user.id, owner_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_PHOTO)
    stored = photos.path_for(workout_id, photo_id)
    if not os.path.isfile(stored):
        # The row says there is a picture and the disk disagrees, which is what
        # a lost or unmounted volume looks like. Handing that to FileResponse
        # raises inside the response and answers 500.
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_PHOTO)
    return FileResponse(
        stored,
        media_type=photos.MEDIA_TYPE,
        headers={
            # Private, because a shared cache must never hand one person's
            # photograph to another request. Immutable and a year long because a
            # photo is only ever written once: editing one is not a thing, and
            # replacing it means a new id and a new URL.
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


# How much of an upload is read at a time on its way to the disk. Big enough
# that a hundred megabytes is not a hundred thousand calls, small enough that
# the bytes in flight are never the size of the file.
_UPLOAD_CHUNK = 1024 * 1024


@router.post("/{workout_id}/videos", status_code=status.HTTP_201_CREATED)
async def upload_video(
    workout_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Attach a short video to your own workout (app/videos.py stores it).

    The photo endpoint's shape throughout, with the two differences the size of
    the thing forces. The part is written straight to a file rather than read
    into memory, because a hundred megabytes per request is a different
    proposition from ten. And the re-encode happens here, inside the request,
    which is what makes the answer honest: a minute of 720p is a couple of
    seconds of work, and a job queue for that would be a system to run rather
    than a feature to have.
    """
    if throttle.video_limiter.hit(throttle.client_address(request)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many uploads just now. Wait a minute."
        )
    workout = _owned(db, workout_id, user.id)
    holds = db.execute(
        select(func.count())
        .select_from(models.WorkoutVideo)
        .where(models.WorkoutVideo.workout_id == workout.id)
    ).scalar_one()
    if holds >= MAX_VIDEOS_PER_WORKOUT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, VIDEOS_FULL)
    if _media_held(db, workout.id) >= MAX_MEDIA_PER_WORKOUT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, MEDIA_FULL)

    # Content-Length is a claim, checked first to refuse the obvious case
    # cheaply; the parser below enforces the same cap on the actual bytes.
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_VIDEO_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, VIDEO_TOO_LARGE)

    try:
        form = await request.form(max_files=1, max_fields=0, max_part_size=MAX_VIDEO_BYTES)
    except MultiPartException:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, VIDEO_TOO_LARGE) from None
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No video was uploaded.")
        with videos.workspace() as work:
            source = os.path.join(work, "upload")
            written = 0
            with open(source, "wb") as out:
                while chunk := await upload.read(_UPLOAD_CHUNK):
                    written += len(chunk)
                    out.write(chunk)
            if written == 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "No video was uploaded.")
            # Probed and encoded before the row exists, so something this server
            # will not store never burns an id.
            #
            # In a worker thread, not here. This request waits for the encode
            # either way, which is the point; what it must not do is hold the
            # event loop for the couple of seconds it takes, because that is
            # every other request on the server waiting for one upload.
            try:
                seconds = await run_in_threadpool(videos.inspect, source)
                encoded, poster = await run_in_threadpool(videos.encode, source, seconds)
            except videos.RejectedVideo as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    finally:
        await form.close()

    video = models.WorkoutVideo(workout_id=workout.id, created_at=security.now_utc())
    db.add(video)
    db.flush()
    try:
        videos.store(workout.id, video.id, encoded, poster)
    except OSError:
        # No row for a video that is not on the disk: an id in the list with
        # nothing behind it is a broken card on every later read.
        db.rollback()
        raise
    db.commit()
    return {"id": video.id}


@router.delete("/{workout_id}/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video(
    workout_id: int,
    video_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Take your own video back off a workout, poster and all."""
    if throttle.delete_media_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many changes just now. Wait a minute.")
    _owned(db, workout_id, user.id)
    video = db.get(models.WorkoutVideo, video_id)
    if video is None or video.workout_id != workout_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_VIDEO)
    db.delete(video)
    db.commit()
    # After the row, and never a failure, for the reason a photo's file is
    # removed after its row.
    videos.remove(workout_id, video_id)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


def _may_watch(db: Session, workout_id: int, video_id: int, user: models.User) -> None:
    """The photo endpoint's reach, said once for the video and its poster.

    Yours, and the people you have both agreed to. The same 404 answers a video
    that does not exist, a stranger's, one on a deleted workout, and one the
    disk has lost; nothing here says which of the four it was.
    """
    owner_id = db.execute(
        select(models.Workout.user_id)
        .join(models.WorkoutVideo, models.WorkoutVideo.workout_id == models.Workout.id)
        .where(
            models.WorkoutVideo.id == video_id,
            models.WorkoutVideo.workout_id == workout_id,
            models.Workout.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if owner_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_VIDEO)
    if owner_id != user.id and not fellowship.are_friends(db, user.id, owner_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_VIDEO)


def _served(stored: str, media_type: str) -> FileResponse:
    if not os.path.isfile(stored):
        # The row says there is a file and the disk disagrees, which is what a
        # lost or unmounted volume looks like. Handing that to FileResponse
        # raises inside the response and answers 500.
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_VIDEO)
    return FileResponse(
        stored,
        media_type=media_type,
        headers={
            # The photos' terms: private so a shared cache cannot hand one
            # person's video to another request, and a year because a stored
            # video is written once and replacing it means a new id.
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{workout_id}/videos/{video_id}")
def read_video(
    workout_id: int,
    video_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> FileResponse:
    """One stored video, to its owner or to an accepted friend.

    FileResponse answers a Range request with 206 and the bytes asked for, and
    that is a requirement rather than a nicety: iOS Safari refuses to play a
    video at all from a URL that answers a range request with the whole file,
    and a phone is what this app is read on.
    """
    _may_watch(db, workout_id, video_id, user)
    return _served(videos.path_for(workout_id, video_id), videos.MEDIA_TYPE)


@router.get("/{workout_id}/videos/{video_id}/poster")
def read_video_poster(
    workout_id: int,
    video_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> FileResponse:
    """The frame the strip shows before anybody presses play, gated exactly as
    the video is: a poster is a picture of the video, so it cannot be the
    looser of the two."""
    _may_watch(db, workout_id, video_id, user)
    return _served(videos.poster_path_for(workout_id, video_id), videos.POSTER_MEDIA_TYPE)


class EncourageBody(BaseModel):
    kind: str
    body: str | None = None


@router.post("/{workout_id}/encourage", status_code=status.HTTP_201_CREATED)
def encourage(
    workout_id: int,
    body: EncourageBody,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Cheer a friend's workout, or write them a note about it.

    Only a friend's, and never your own: this is the one place the game asks
    something of a person rather than of their miles, and applauding yourself
    is not it. A cheer is wordless on purpose and a note is typed by whoever
    sends it. Nothing here suggests either one.
    """
    if throttle.encourage_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many cheers just now. Wait a minute.")
    if body.kind not in ("cheer", "note"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kind must be cheer or note.")

    workout = db.get(models.Workout, workout_id)
    # A deleted workout takes the same branch as one that never existed: it is
    # off the feed, so nothing is left to say a word about.
    if workout is None or workout.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such workout.")
    if workout.user_id == user.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You cannot encourage your own workout."
        )
    if not fellowship.are_friends(db, user.id, workout.user_id):
        # The same answer a workout that does not exist gets: whose feed an id
        # belongs to is not something a stranger gets to learn by asking.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such workout.")

    note = None
    if body.kind == "note":
        note = (body.body or "").strip()
        if not note:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A note needs something in it.")
        if len(note) > NOTE_MAX_CHARS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"A note can be at most {NOTE_MAX_CHARS} characters.",
            )

    try:
        fellowship.give(db, user.id, workout, body.kind, note)
    except IntegrityError:
        # The partial unique index. One cheer each, and the second one is told
        # so rather than quietly counted again.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You have already cheered that workout."
        ) from None

    return {
        "workout_id": workout.id,
        "kind": body.kind,
        # Handed back so the card can settle without fetching the page again.
        "encouragement": fellowship.counts(db, [workout.id], user.id)[workout.id],
    }


@router.get("/{workout_id}/notes")
def workout_notes(
    workout_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """The words written on your own workout, oldest first.

    The owner and nobody else. A friend sees that words were written, because
    the count is on their card too, and never what they said: a note is a word
    to the runner rather than a comment on a thread, so there is no audience for
    it beyond the person it was written to. The same 404 answers a friend, a
    stranger, and a workout that does not exist, so an id says nothing about
    whose history it belongs to.

    Fetched only when somebody opens the counts, which is why the feed carries
    totals rather than bodies. It spends the feed's own read allowance: opening
    the words under a card is part of reading the feed, and giving it a budget
    of its own would only mean one more limiter guarding the same screen.
    """
    if throttle.feed_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, throttle.TOO_MANY_READS)
    _owned(db, workout_id, user.id)
    rows = db.execute(
        select(
            models.Encouragement.body,
            models.Encouragement.created_at,
            models.User.username,
            models.User.first_name,
            models.User.last_name,
        )
        .join(models.User, models.User.id == models.Encouragement.from_user_id)
        .where(
            models.Encouragement.workout_id == workout_id,
            models.Encouragement.kind == "note",
        )
        # By id as well, because two notes can share a timestamp and the order
        # they were written in is the order they should be read in.
        .order_by(models.Encouragement.created_at, models.Encouragement.id)
    ).all()
    return [
        {
            # The name they go by, falling back to the username, the same way
            # every other card names a person.
            "from": fellowship.display_name(first_name, last_name) or username,
            "body": body or "",
            "created_at": created_at.isoformat(),
        }
        for body, created_at, username, first_name, last_name in rows
    ]


@router.get("/weeks")
def weekly_totals(
    count: int = Query(8, ge=1, le=MAX_WEEKS),
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """Per-activity totals for the last `count` weeks, newest first.

    Weeks start Monday in the server's timezone, and every week in the range is
    returned whether anything happened in it or not: a rest week is part of the
    rhythm, so it has to be visible rather than missing from the list. Within a
    week, only the activities that actually happened appear.
    """
    this_week = activity_rules.week_start(security.now_utc())
    earliest = this_week - dt.timedelta(weeks=count - 1)
    # One query for the whole range, grouped in Python. The alternative is
    # asking the database to do calendar arithmetic in the server timezone,
    # which is written differently in Postgres and SQLite and would give the
    # tests a different answer from production.
    cutoff = dt.datetime.combine(earliest, dt.time.min, tzinfo=activity_rules.SERVER_TZ)
    rows = db.execute(
        select(models.Workout).where(
            models.Workout.user_id == user.id,
            models.Workout.deleted_at.is_(None),
            models.Workout.start_ts >= cutoff,
        )
    ).scalars()

    # Every week in the range gets an entry; an activity gets one only once it
    # has a workout in that week. An empty map therefore reads as a rest week
    # rather than as four zeroes the caller has to filter out.
    weeks: dict[dt.date, dict[str, dict]] = {
        earliest + dt.timedelta(weeks=offset): {} for offset in range(count)
    }
    for row in rows:
        bucket = weeks.get(activity_rules.week_start(row.start_ts))
        if bucket is None:
            continue
        entry = bucket.setdefault(
            row.activity, {"distance_mi": 0.0, "active_kcal": 0.0, "workouts": 0}
        )
        entry["distance_mi"] += row.distance_mi
        entry["active_kcal"] += row.active_kcal
        entry["workouts"] += 1

    result = []
    for monday in sorted(weeks, reverse=True):
        # Ordered by the activity list rather than by first arrival, so the same
        # week always serialises its activities in the same order.
        activities = {
            name: {
                "distance_mi": round(weeks[monday][name]["distance_mi"], 2),
                "active_kcal": round(weeks[monday][name]["active_kcal"], 1),
                "workouts": weeks[monday][name]["workouts"],
            }
            for name in ACTIVITIES
            if name in weeks[monday]
        }
        result.append(
            {
                "week_start": monday.isoformat(),
                "activities": activities,
                "total_active_kcal": round(
                    sum(totals["active_kcal"] for totals in activities.values()), 1
                ),
            }
        )
    return result
