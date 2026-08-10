"""The workout history and the weekly totals behind the Almanac.

Nothing here creates a workout. They arrive on the sync path and only there, so
one account has one way in and every row can say where it came from.
"""

import datetime as dt
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Straight from starlette: the multipart parser produces starlette's UploadFile,
# and an isinstance check against fastapi's subclass would refuse every real
# upload.
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from app import activity as activity_rules
from app import fellowship, images, medals, models, photos, security, throttle
from app.config import (
    MAX_PHOTO_BYTES,
    MAX_PHOTOS_PER_WORKOUT,
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
PHOTOS_FULL = f"A workout can hold {MAX_PHOTOS_PER_WORKOUT} photos."
NO_SUCH_WORKOUT = "No such workout."
NO_SUCH_PHOTO = "No such photo."


def _serialize(
    workout: models.Workout,
    medal_ids: list[str] | None = None,
    has_route: bool = False,
    photo_ids: list[int] | None = None,
) -> dict:
    """One workout plus what it was worth, which the history shows on each row.

    The experience is the converted distance the pipeline credited, computed
    from the same function rather than a copy of it, so a row can never claim a
    number the account was not given. The medals are read from the table
    instead, because earning one is a fact about what happened rather than a
    number that can be recomputed from the row. A workout carries the ones it
    earned itself, which is none, one, or one race medal and one time medal.

    The route itself is not here, only whether there is one: a list has a couple
    of hundred coordinate pairs on it, and a page of history would be mostly
    route for a view that draws none of them until it is scrolled to.
    """
    return {
        **activity_rules.serialize(workout, photo_ids),
        "xp": round(activity_rules.converted_miles(workout.activity, workout.distance_mi), 2),
        "medals": medal_ids or [],
        "has_route": has_route,
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


@router.get("")
def list_workouts(
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    before: str | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    stmt = select(models.Workout).where(models.Workout.user_id == user.id)
    if before:
        cutoff = parse_cursor(before)
        stmt = stmt.where(models.Workout.start_ts < cutoff)
    # Ordered by id as well as time so that two workouts sharing a start time
    # keep a stable order between pages; without it, paging can show one twice
    # and skip another.
    stmt = stmt.order_by(models.Workout.start_ts.desc(), models.Workout.id.desc()).limit(limit)
    rows = list(db.execute(stmt).scalars())
    earned = medals.medals_for(db, rows)
    routed = routes_for(db, rows)
    pictures = photos_for(db, rows)
    return [
        _serialize(row, earned.get(row.id), row.id in routed, pictures.get(row.id))
        for row in rows
    ]


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
        .where(models.WorkoutRoute.workout_id == workout_id)
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No route for that workout.")
    points, owner_id, kept_back = row
    if owner_id != user.id and (
        "route" in (kept_back or []) or not fellowship.are_friends(db, user.id, owner_id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No route for that workout.")
    return {"points": points}


def _owned(db: Session, workout_id: int, user_id: int) -> models.Workout:
    """One of your own workouts, or the same 404 a workout that does not exist
    gets. Whose history an id belongs to is not something a caller learns by
    asking for it."""
    workout = db.get(models.Workout, workout_id)
    if workout is None or workout.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_WORKOUT)
    return workout


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
    return _serialize(
        workout,
        medals.medals_for(db, [workout]).get(workout.id),
        workout.id in routes_for(db, [workout]),
        photos_for(db, [workout]).get(workout.id),
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
    held = db.execute(
        select(func.count())
        .select_from(models.WorkoutPhoto)
        .where(models.WorkoutPhoto.workout_id == workout.id)
    ).scalar_one()
    if held >= MAX_PHOTOS_PER_WORKOUT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, PHOTOS_FULL)

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
    it. The same 404 answers a photo that does not exist, a stranger's, and one
    the disk has lost; nothing here says which of the three it was.
    """
    owner_id = db.execute(
        select(models.Workout.user_id)
        .join(models.WorkoutPhoto, models.WorkoutPhoto.workout_id == models.Workout.id)
        .where(
            models.WorkoutPhoto.id == photo_id,
            models.WorkoutPhoto.workout_id == workout_id,
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
    if workout is None:
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
            models.Workout.user_id == user.id, models.Workout.start_ts >= cutoff
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
