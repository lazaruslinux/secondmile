"""One workout, minute by minute: the screen behind a card.

A card says what a session was. This says what it did: how far each minute
went, what the heart was doing while it went there, the air it happened in,
and how much of a body's range the effort sat at. Every reading here is a row
app.samples wrote when the workout was imported, so nothing is worked out and
nothing is stored; the screen is the only reason any of it is kept.

None of it earns anything, which is the same two-lane law the samples module
states about itself. No medal, no conversion, no total reads a single field
below.

Its own module rather than another block of the workout router, because the
zone ceiling is 220 minus an age and the age is read where the profile reads
it: workouts.py cannot import the profile router, since the profile router
imports workouts.py.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import fellowship, models, security, throttle
from app.db import get_db
from app.routers.profile import computed_age
from app.routers.workouts import NO_SUCH_WORKOUT

router = APIRouter(prefix="/workouts", tags=["workouts"])

# The number the age formula counts down from. It is an estimate of the fastest
# a new-born heart could go and it is wrong for any particular person by some
# beats either way, which is why the answer travels with the basis it was read
# from rather than on its own.
AGE_MAX_HR = 220


def _observed_ceiling(db: Session, owner_id: int, own: bool) -> int | None:
    """The highest beat this account has on record, or None if it has none.

    Read from both places a beat is kept: the per-minute rows, which are the
    finer reading, and the whole-session summary on the workout beside them,
    which is the only one an older sync left behind. Whichever is higher is the
    answer, because both are the same claim about the same body.

    Deleted workouts are not read. A session somebody took out of the game is
    out of it, and a ladder drawn from a beat that no longer appears anywhere
    would be a number nothing on screen could account for.

    Workouts the owner took off the feeds are read for the owner's own view and
    for nobody else's. The ceiling a friend is shown is drawn from the sessions
    that friend may see: a number sourced from a hidden one would be that
    session's heart rate said a step removed, out of a workout every other
    friend-facing read answers with a 404.
    """
    seen_by_reader = (
        models.Workout.user_id == owner_id,
        models.Workout.deleted_at.is_(None),
        *(() if own else (models.Workout.hidden_from_feed.is_(False),)),
    )
    highest_minute = db.execute(
        select(func.max(models.WorkoutSample.hr_max))
        .join(models.Workout, models.Workout.id == models.WorkoutSample.workout_id)
        .where(*seen_by_reader)
    ).scalar()
    highest_summary = db.execute(
        select(func.max(models.Workout.max_hr)).where(*seen_by_reader)
    ).scalar()
    readings = [int(seen) for seen in (highest_minute, highest_summary) if seen is not None]
    return max(readings) if readings else None


def zone_ceiling(
    db: Session, owner_id: int, birthdate, own: bool
) -> tuple[int | None, str | None]:
    """The top of the zone ladder for one account, and what it was read from.

    An age is the better answer and a birthdate is the only way to one, so it
    is asked first. Failing that, the highest beat the account has ever
    recorded stands in: it is a floor rather than a ceiling, and the zones it
    draws are conservative, which is the right direction to be wrong in.

    An account with neither gets nothing, and the screen draws no zones at all.
    Zones are read off a ladder, and a ladder with no top is not a reading with
    a caveat on it, it is a picture of nothing.

    The basis rides with the number for the same reason: a friend reading their
    own zones next to somebody else's has to be able to tell an age estimate
    from a measurement.

    own says whose screen this is, and only the measured answer reads it: the
    owner's own ceiling may be drawn from a hidden session, a friend's may not.
    """
    age = computed_age(birthdate)
    if age is not None:
        return AGE_MAX_HR - age, "age"
    observed = _observed_ceiling(db, owner_id, own)
    if observed is not None:
        return observed, "observed"
    return None, None


def _minute_row(sample: models.WorkoutSample, hearts: bool, calories: bool) -> dict:
    """One minute of a session, as the screen receives it.

    The beats are left out altogether rather than sent as nulls when the owner
    keeps them back, which is the rule feed_row states: a null would say the
    minute carried no heart rate, and being asked not to look is a different
    thing. The minute's own calories go the same way, under the toggle that
    already governs the figure on the card: a session's calories said sixty
    times over is the same fact about the same body.

    How far a minute went and how many steps it took are never held back. They
    are the same class of reading as the distance already on the card, and the
    splits are drawn from them.
    """
    row = {
        "minute": sample.minute,
        # Four places because a minute of a slow swim is a hundredth of a mile
        # and the splits are added up out of these.
        "distance_mi": (
            round(sample.distance_mi, 4) if sample.distance_mi is not None else None
        ),
        "steps": sample.steps,
    }
    if hearts:
        row["hr_min"] = sample.hr_min
        row["hr_avg"] = sample.hr_avg
        row["hr_max"] = sample.hr_max
    if calories:
        # One place. A minute of a walk is a few calories and the lane is drawn
        # off these, so a whole number would draw a staircase.
        row["active_kcal"] = (
            round(sample.active_kcal, 1) if sample.active_kcal is not None else None
        )
    return row


@router.get("/{workout_id}/details")
def workout_details(
    workout_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Everything one workout says beyond the six numbers on its card.

    The reach is the feed's, the same as a route line and a photograph: your
    own, and the people you have both agreed to. The same 404 answers a workout
    that does not exist, a stranger's, a deleted one, and one its owner has
    taken off the feeds, so an id still says nothing about whose history it
    belongs to. The owner opens their own hidden workout as they always did:
    it is off their friends' feeds rather than out of their own history.

    What a friend is told is what the owner said they may be told, and the
    rules are feed_row's rather than new ones. The heart rate toggle takes
    every beat with it: the per-minute readings, the session's highest, and
    both zone fields, because a ladder drawn from somebody's age with their
    minutes hung on it is the heart rate said another way. The calories toggle
    takes the per-minute calories for the same reason. The route toggle takes
    the climb, because how much a session went uphill is a fact about the
    ground it crossed. The weather is none of them: what the air was like is a
    fact about the afternoon rather than about a body, and it rides on every
    copy.

    Own copies carry everything whatever the list says, for the reason a card
    does: hiding a number from yourself is not a privacy setting.

    It spends the feed's own read allowance rather than one of its own. Opening
    a card is part of reading the feed, and a second limiter guarding the same
    screen would only be a second thing to keep in step.
    """
    if throttle.feed_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, throttle.TOO_MANY_READS)

    # The owner's list and their birthdate are read in the same query as the
    # workout, so what a friend may see cannot be answered from the workout
    # alone by a later edit that forgets to ask.
    row = db.execute(
        select(models.Workout, models.User.hidden_from_friends, models.User.birthdate)
        .join(models.User, models.User.id == models.Workout.user_id)
        .where(
            models.Workout.id == workout_id,
            models.Workout.deleted_at.is_(None),
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_WORKOUT)
    workout, hidden, birthdate = row
    own = workout.user_id == user.id
    if not own and (
        workout.hidden_from_feed or not fellowship.are_friends(db, user.id, workout.user_id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_WORKOUT)

    kept_back = () if own else tuple(str(field) for field in (hidden or []))
    hearts = "avg_hr" not in kept_back
    calories = "active_kcal" not in kept_back
    minutes = (
        db.execute(
            select(models.WorkoutSample)
            .where(models.WorkoutSample.workout_id == workout.id)
            .order_by(models.WorkoutSample.minute)
        )
        .scalars()
        .all()
    )

    body = {
        "workout_id": workout.id,
        # Empty rather than absent for a workout whose export carried no
        # arrays, which is every workout synced before the table existed. The
        # screen draws its figures and says so in one line.
        "minutes": [_minute_row(sample, hearts, calories) for sample in minutes],
        "temperature_f": (
            round(workout.temperature_f, 1) if workout.temperature_f is not None else None
        ),
        "humidity_pct": (
            round(workout.humidity_pct, 1) if workout.humidity_pct is not None else None
        ),
    }
    if hearts:
        body["max_hr"] = workout.max_hr
        ceiling, basis = zone_ceiling(db, workout.user_id, birthdate, own)
        body["zone_max"] = ceiling
        body["zone_basis"] = basis
    if "route" not in kept_back:
        body["elevation_gain_ft"] = (
            round(workout.elevation_gain_ft, 1)
            if workout.elevation_gain_ft is not None
            else None
        )
    return body
