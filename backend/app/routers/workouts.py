"""Manual entry, the workout history, and the weekly totals behind the Almanac."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import activity as activity_rules
from app import models, progress, security, throttle
from app.config import (
    MAX_WORKOUT_DISTANCE_MI,
    MAX_WORKOUT_DURATION_S,
    MAX_WORKOUT_HR,
    MAX_WORKOUT_KCAL,
    MIN_WORKOUT_HR,
)
from app.db import get_db
from app.models import ACTIVITIES

router = APIRouter(prefix="/workouts", tags=["workouts"])

# High enough that nobody paging through a real history notices, low enough that
# a single request cannot ask the server to serialise everything at once.
MAX_LIMIT = 200
MAX_WEEKS = 52


def _serialize(workout: models.Workout, race_badge: str | None = None) -> dict:
    """One workout plus what it was worth, which the history shows on each row.

    The experience is the converted distance the pipeline credited, computed
    from the same function rather than a copy of it, so a row can never claim a
    number the account was not given. The race badge is read from the table
    instead, because earning one is a fact about what happened rather than a
    number that can be recomputed from the row.
    """
    return {
        **activity_rules.serialize(workout),
        "xp": round(activity_rules.converted_miles(workout.activity, workout.distance_mi), 2),
        "race_badge": race_badge,
    }


def _race_badges(db: Session, workouts: list[models.Workout]) -> dict[int, str]:
    """Which of these workouts earned a race badge, keyed by workout id."""
    ids = [row.id for row in workouts]
    if not ids:
        return {}
    return dict(
        db.execute(
            select(models.BadgeEarn.workout_id, models.BadgeEarn.badge_id).where(
                models.BadgeEarn.workout_id.in_(ids)
            )
        ).all()
    )


class ManualWorkout(BaseModel):
    activity: str
    start_ts: dt.datetime
    duration_s: int
    # allow_inf_nan is the load-bearing part. A float field takes a NaN happily,
    # JSON is allowed to write one as a bare literal, and a NaN passes every
    # bound below because it compares false against all of them. Stored on a
    # workout it breaks every later read of that account's progress, so it is
    # refused at the door instead.
    distance_mi: float = Field(allow_inf_nan=False)
    active_kcal: float = Field(0.0, allow_inf_nan=False)
    avg_hr: float | None = Field(None, allow_inf_nan=False)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_workout(
    body: ManualWorkout,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    if throttle.workout_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many entries. Wait a minute.")
    if body.activity not in ACTIVITIES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Activity must be one of: {', '.join(ACTIVITIES)}."
        )
    if body.duration_s <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Duration must be more than zero.")
    if body.duration_s > MAX_WORKOUT_DURATION_S:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Duration cannot be longer than {MAX_WORKOUT_DURATION_S // 3600} hours.",
        )
    if body.distance_mi < 0 or body.active_kcal < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Distance and energy cannot be negative.")
    if body.distance_mi > MAX_WORKOUT_DISTANCE_MI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Distance cannot be more than {MAX_WORKOUT_DISTANCE_MI:.0f} miles.",
        )
    if body.active_kcal > MAX_WORKOUT_KCAL:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Energy cannot be more than {MAX_WORKOUT_KCAL:.0f} kcal.",
        )
    if body.avg_hr is not None and not MIN_WORKOUT_HR <= body.avg_hr <= MAX_WORKOUT_HR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Heart rate must be between {MIN_WORKOUT_HR:.0f} and {MAX_WORKOUT_HR:.0f}.",
        )

    start_ts = activity_rules.ensure_aware(body.start_ts)
    flags = {}
    if activity_rules.impossible_pace(body.activity, body.duration_s, body.distance_mi):
        flags["impossible_pace"] = True

    workout = models.Workout(
        user_id=user.id,
        activity=body.activity,
        start_ts=start_ts,
        duration_s=body.duration_s,
        distance_mi=body.distance_mi,
        active_kcal=body.active_kcal,
        avg_hr=body.avg_hr,
        # The marker exists so a future public version can treat entries nobody
        # can verify differently. Today they count exactly the same.
        source="manual",
        flags=flags,
        created_at=security.now_utc(),
    )
    try:
        with db.begin_nested():
            db.add(workout)
            db.flush()
    except IntegrityError:
        # The same dedupe key the sync path uses. Someone typing in a workout
        # their watch already sent should be told, not quietly given a second
        # copy of it.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A workout with that start time and duration already exists."
        ) from None

    if activity_rules.over_daily_cap(db, user.id, body.activity, start_ts):
        workout.flags = {**flags, "daily_cap": True}
    db.commit()

    # A workout typed in by hand counts exactly as much as one from a watch,
    # so it goes through the same pipeline on the same terms, race badge
    # included.
    progress.process_user(db, user.id)
    return _serialize(workout, _race_badges(db, [workout]).get(workout.id))


def _parse_cursor(before: str) -> dt.datetime:
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
        cutoff = _parse_cursor(before)
        stmt = stmt.where(models.Workout.start_ts < cutoff)
    # Ordered by id as well as time so that two workouts sharing a start time
    # keep a stable order between pages; without it, paging can show one twice
    # and skip another.
    stmt = stmt.order_by(models.Workout.start_ts.desc(), models.Workout.id.desc()).limit(limit)
    rows = list(db.execute(stmt).scalars())
    badges = _race_badges(db, rows)
    return [_serialize(row, badges.get(row.id)) for row in rows]


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
