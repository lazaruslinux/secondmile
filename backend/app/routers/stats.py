"""What this instance has covered altogether, for the welcome page to count up.

Two integers and nothing else: whole miles and how many workouts they came
from, over every account at once. No per-user anything, no timestamps, and no
way to ask about a person, because this is read by whoever opened the front
page and nobody has signed in yet.

The cache is not an optimisation, it is the privacy of the numbers. Live
totals answered on demand would let anybody watching the endpoint see the
moment a member's run lands, and how far it was, without ever being let in. Ten
minutes of the same answer is what makes the pair a fact about the instance
rather than a feed of its members.
"""

import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, throttle
from app.db import get_db

router = APIRouter(tags=["stats"])

# How long one count is served for. Long enough that a workout landing is not
# visible from outside, short enough that the page is not stale for an hour.
CACHE_SECONDS = 600

# The last count and the moment it was taken, or nothing before the first
# request. Module level on purpose: one count per process serves every caller,
# which is the whole point of taking it.
_counted: tuple[dict[str, int], float] | None = None


def reset_cache() -> None:
    """Forget the count, so the next request takes a fresh one.

    For the tests, which share one process the way the limiters do: a count
    taken against one case's database would otherwise be served to the next.
    """
    global _counted
    _counted = None


def _count(db: Session) -> dict[str, int]:
    """Miles, workouts and steps across the instance, deleted ones left out.

    A deletion is a disappearance from every total at once, exactly as it is
    from every feed: the counter must not go on claiming a workout its owner
    took back. Miles are floored rather than rounded, so the number on the page
    is ground that has certainly been covered.

    The steps are the raw count every pedometer on the instance has reported,
    which is a different kind of number from the other two and is named as one
    on the page. Nothing is deleted from it: a day's steps are a reading rather
    than a thing anybody logged, so there is nothing to take back.
    """
    miles, activities = db.execute(
        select(func.coalesce(func.sum(models.Workout.distance_mi), 0.0), func.count())
        .select_from(models.Workout)
        .where(models.Workout.deleted_at.is_(None))
    ).one()
    steps = db.execute(
        select(func.coalesce(func.sum(models.DailySteps.steps), 0))
    ).scalar_one()
    return {"miles": int(miles), "activities": int(activities), "steps": int(steps)}


@router.get("/stats")
def read_stats(request: Request, db: Session = Depends(get_db)) -> dict[str, int]:
    """The instance totals. Public, unauthenticated, and deliberately blunt.

    Recomputed lazily on the first request past the cache's age, so an instance
    nobody is looking at never counts anything. The clock is time.time rather
    than the app's own now_utc, the way the limiters read it: this is an age in
    real seconds, not a moment in anybody's timezone.
    """
    if throttle.stats_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, throttle.TOO_MANY_READS)
    global _counted
    now = time.time()
    if _counted is None or now - _counted[1] > CACHE_SECONDS:
        _counted = (_count(db), now)
    return _counted[0]
