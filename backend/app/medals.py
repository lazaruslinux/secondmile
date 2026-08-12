"""The medals: the catalogue, the rules that earn them, and their awarding.

Eleven medals in three families, and every one of them repeatable. That is the
whole system: there is no second kind of thing earned once and ticked off, so
nothing here has to say whether a medal can come again. A marathon next month
is another Marathon, a big week in October is another 25-mile week.

Two tables hold the earns, split by what earns them rather than by family.
badge_earns is one row per workout per medal, for the families a single session
earns (race and time). weekly_badge_earns is one row per week per family, for
the family a week earns, which is what lets a week upgrade its medal in place
as the miles add up.

Every threshold is raw miles, never converted Miles: a 5K is a distance on the
ground and a 25-mile week is twenty-five miles walked, run, ridden, or swum. No
conversion rate has any business changing what either of them is.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.activity import week_start
from app.config import SERVER_TZ

# Tolerance: distances are floats summed from floats, and a total that has
# exactly paid for a medal has to clear it.
_EPSILON = 1e-9


@dataclass(frozen=True)
class Medal:
    id: str
    # Which family the medal belongs to, which is how the profile groups them
    # and how a rule finds its own rows.
    family: str
    # The label the API serves. Ids are the stable part: they are in the
    # database and in the badge slots, and a name is only ever printed.
    name: str
    # Raw miles the medal is earned at: one workout's distance for the race
    # family, one week's total for the weekly family, and nothing at all for
    # the time family, which is earned by a clock.
    distance_mi: float | None = None


# Catalogue order, which is the order the profile serves them in. Within the
# race and weekly families the thresholds ascend, which is what makes "the
# highest one this qualifies for" a single pass.
CATALOG: tuple[Medal, ...] = (
    # Every race threshold sits a hair under the metric truth on purpose,
    # because a GPS trace of a measured 5K rarely reads 3.107.
    Medal("race_5k", "race", "5K", 3.1),
    Medal("race_10k", "race", "10K", 6.2),
    Medal("race_half", "race", "Half", 13.1),
    Medal("race_marathon", "race", "Marathon", 26.2),
    Medal("race_ultra", "race", "50K", 31.1),
    Medal("weekly_10", "weekly", "10-mile week", 10.0),
    Medal("weekly_15", "weekly", "15-mile week", 15.0),
    Medal("weekly_25", "weekly", "25-mile week", 25.0),
    Medal("weekly_40", "weekly", "40-mile week", 40.0),
    Medal("early_riser", "time", "Early Riser"),
    Medal("night_owl", "time", "Night Owl"),
)

BY_ID: dict[str, Medal] = {row.id: row for row in CATALOG}

RACE_MEDALS: tuple[Medal, ...] = tuple(row for row in CATALOG if row.family == "race")
WEEKLY_MEDALS: tuple[Medal, ...] = tuple(row for row in CATALOG if row.family == "weekly")

# Which table a family's earns live in. The split is the one thing about a
# family that is not data: a week cannot be keyed by a workout.
WORKOUT_FAMILIES = ("race", "time")
WEEK_FAMILIES = ("weekly",)

# A time medal wants a 5K on the ground, the same distance the smallest race
# medal is measured at. Anything shorter is a stroll at an odd hour.
MIN_TIME_MEDAL_MI = RACE_MEDALS[0].distance_mi

# Local hours, read in the instance timezone. Early Riser is the two hours
# before six; Night Owl is everything from eight in the evening until it.
EARLY_RISER_FROM = 4
EARLY_RISER_UNTIL = 6
NIGHT_OWL_FROM = 20


# --------------------------------------------------------------------------
# What one workout earns
# --------------------------------------------------------------------------


def _eligible(workout: models.Workout) -> bool:
    """Whether a workout can earn a per-workout medal at all.

    Running only, and never a workout the pace flag has already called
    impossible: a distance nobody covered is not a distance worth a medal.
    """
    if workout.activity != "run":
        return False
    return not (workout.flags or {}).get("impossible_pace")


def _race_medal_for(workout: models.Workout) -> Medal | None:
    """The race medal one workout earns, or None. The highest one only: a
    marathon is a marathon, not also a 5K and a 10K and a half."""
    if not _eligible(workout):
        return None
    best = None
    for medal in RACE_MEDALS:
        if workout.distance_mi + _EPSILON >= medal.distance_mi:
            best = medal
    return best


def _time_medal_for(workout: models.Workout) -> Medal | None:
    """The time-of-day medal one workout earns, or None.

    Read in the instance timezone, because the hour of the day is the whole
    point: a run stored at 12:44 UTC was a quarter to six in the morning to
    whoever ran it, and that is the only reading that means anything.
    """
    if not _eligible(workout) or workout.distance_mi + _EPSILON < MIN_TIME_MEDAL_MI:
        return None
    hour = workout.start_ts.astimezone(SERVER_TZ).hour
    if EARLY_RISER_FROM <= hour < EARLY_RISER_UNTIL:
        return BY_ID["early_riser"]
    if hour >= NIGHT_OWL_FROM or hour < EARLY_RISER_FROM:
        return BY_ID["night_owl"]
    return None


# One rule per per-workout family, each returning at most one medal. A workout
# can hold one from each, so a 5K before six earns the 5K and Early Riser both.
_WORKOUT_RULES = (_race_medal_for, _time_medal_for)


def medals_for_workout(workout: models.Workout) -> list[Medal]:
    """Every per-workout medal a workout earns, in catalogue order."""
    found = [rule(workout) for rule in _WORKOUT_RULES]
    return [medal for medal in found if medal is not None]


def award_workout_medals(
    db: Session, user_id: int, workout: models.Workout
) -> list[Medal]:
    """Record what a freshly credited workout earned. Returns the rows written.

    earned_at is the workout's start time rather than the clock, so a rebuild
    from the same history writes the same row. The unique (workout, medal) is
    what makes a replay idempotent even when the marker table has been lost.
    """
    written = []
    for medal in medals_for_workout(workout):
        try:
            with db.begin_nested():
                db.add(
                    models.BadgeEarn(
                        user_id=user_id,
                        badge_id=medal.id,
                        workout_id=workout.id,
                        earned_at=workout.start_ts,
                    )
                )
                db.flush()
        except IntegrityError:
            continue
        written.append(medal)
    return written


# --------------------------------------------------------------------------
# What one week earns
# --------------------------------------------------------------------------


def _week_workouts(db: Session, user_id: int, monday: dt.date) -> list[models.Workout]:
    """One week's credited workouts, oldest first.

    Every activity counts and flagged workouts count too: a flag blocks the
    medal for the workout it is on, and a week is a total rather than a claim
    about any one session. Bounded by the next Monday rather than by adding
    seven days, because the week a clock change falls in is not 168 hours long.

    A deleted workout is not part of the week. It has no marker row either, so
    the join would already leave it out; the test is written down anyway,
    because this is the query that decides what a week's medal is worth.
    """
    start = dt.datetime.combine(monday, dt.time.min, tzinfo=SERVER_TZ)
    end = dt.datetime.combine(monday + dt.timedelta(days=7), dt.time.min, tzinfo=SERVER_TZ)
    return list(
        db.execute(
            select(models.Workout)
            .join(
                models.ProcessedWorkout,
                models.ProcessedWorkout.workout_id == models.Workout.id,
            )
            .where(
                models.Workout.user_id == user_id,
                models.Workout.deleted_at.is_(None),
                models.Workout.start_ts >= start,
                models.Workout.start_ts < end,
            )
            # By id within a timestamp, the same order the pipeline credits in,
            # so which workout crossed a line is not a question of arrival.
            .order_by(models.Workout.start_ts, models.Workout.id)
        ).scalars()
    )


def _crossings(
    db: Session, user_id: int, monday: dt.date
) -> dict[str, tuple[Medal, models.Workout]]:
    """The medal each week family has reached, and the workout that crossed it.

    Walked over the whole week every time rather than added to a running total,
    which is what makes the answer the same whichever order the week's workouts
    arrived in. A history backfilled out of order converges on exactly the rows
    a clean replay would write.

    Workouts and nothing else. Steps are not miles the week counts: they earn
    nothing anywhere, and a week is the work put in on recorded activities.
    """
    total = 0.0
    reached = 0
    found: dict[str, tuple[Medal, models.Workout]] = {}
    for workout in _week_workouts(db, user_id, monday):
        total += workout.distance_mi
        while (
            reached < len(WEEKLY_MEDALS)
            and total + _EPSILON >= WEEKLY_MEDALS[reached].distance_mi
        ):
            found["weekly"] = (WEEKLY_MEDALS[reached], workout)
            reached += 1
    return found


def update_week(db: Session, user_id: int, monday: dt.date) -> None:
    """Bring one week's medals up to what its credited workouts have earned.

    One row per family per week, upgraded in place: a week that reaches 25
    miles keeps the row it earned at 10 and changes what it holds, rather than
    wearing three medals for the same seven days. Nothing is ever taken back
    here, because a week's total only ever grows.

    workout_id is nullable in the schema and is never written null here. Rows
    that carry a null are from the round that let step credit cross a line;
    they are read like any other, and nothing writes another.
    """
    for family, (medal, crossing) in _crossings(db, user_id, monday).items():
        row = db.execute(
            select(models.WeeklyBadgeEarn).where(
                models.WeeklyBadgeEarn.user_id == user_id,
                models.WeeklyBadgeEarn.week_start == monday,
                models.WeeklyBadgeEarn.family == family,
            )
        ).scalar_one_or_none()
        if row is None:
            try:
                with db.begin_nested():
                    db.add(
                        models.WeeklyBadgeEarn(
                            user_id=user_id,
                            week_start=monday,
                            family=family,
                            badge_id=medal.id,
                            workout_id=crossing.id,
                            earned_at=crossing.start_ts,
                        )
                    )
                    db.flush()
                continue
            except IntegrityError:
                # Another request wrote the row between the read and the write.
                # The primary key settled it; this reads back what it settled on
                # and carries on to the upgrade below.
                row = db.execute(
                    select(models.WeeklyBadgeEarn).where(
                        models.WeeklyBadgeEarn.user_id == user_id,
                        models.WeeklyBadgeEarn.week_start == monday,
                        models.WeeklyBadgeEarn.family == family,
                    )
                ).scalar_one_or_none()
                if row is None:
                    continue
        row.badge_id = medal.id
        row.workout_id = crossing.id
        row.earned_at = crossing.start_ts


def update_week_for(db: Session, user_id: int, workout: models.Workout) -> None:
    """The week a workout falls in, brought up to date."""
    update_week(db, user_id, week_start(workout.start_ts))


def clear_earns(db: Session, user_id: int) -> None:
    """Throw away one account's medals, for a rebuild to earn them again."""
    db.execute(delete(models.BadgeEarn).where(models.BadgeEarn.user_id == user_id))
    db.execute(
        delete(models.WeeklyBadgeEarn).where(models.WeeklyBadgeEarn.user_id == user_id)
    )


# --------------------------------------------------------------------------
# Reading them back
# --------------------------------------------------------------------------


def _counts(db: Session, user_id: int) -> dict[str, tuple[int, dt.datetime, dt.datetime]]:
    """(count, first, last) per medal id, over both tables."""
    found: dict[str, tuple[int, dt.datetime, dt.datetime]] = {}
    for table in (models.BadgeEarn, models.WeeklyBadgeEarn):
        for medal_id, count, first, last in db.execute(
            select(table.badge_id, func.count(), func.min(table.earned_at), func.max(table.earned_at))
            .where(table.user_id == user_id)
            .group_by(table.badge_id)
        ).all():
            found[medal_id] = (int(count), first, last)
    return found


def medal_summary(db: Session, user_id: int) -> list[dict]:
    """The whole catalogue with how many times this account has earned each.

    Zeroes included: the strip on the profile shows what is still to come as
    much as what has been done, and the client draws the stars from the count.
    """
    held = _counts(db, user_id)
    out = []
    for medal in CATALOG:
        count, first, last = held.get(medal.id, (0, None, None))
        out.append(
            {
                "id": medal.id,
                "family": medal.family,
                "name": medal.name,
                "count": count,
                "first_earned_at": first.isoformat() if first is not None else None,
                "last_earned_at": last.isoformat() if last is not None else None,
            }
        )
    return out


def earned_medal_ids(db: Session, user_id: int) -> set[str]:
    """The medals this account has earned at least once, any family."""
    return set(_counts(db, user_id))


def medals_for(db: Session, workouts: list[models.Workout]) -> dict[int, list[str]]:
    """The per-workout medals on each of these workouts, keyed by workout id.

    One query for the page. Weekly medals are not here and never will be: they
    belong to seven days rather than to the run that happened to cross a line,
    and putting one on a feed row would say the wrong thing about the run.
    """
    ids = [row.id for row in workouts]
    if not ids:
        return {}
    order = {medal.id: index for index, medal in enumerate(CATALOG)}
    found: dict[int, list[str]] = {}
    for workout_id, medal_id in db.execute(
        select(models.BadgeEarn.workout_id, models.BadgeEarn.badge_id).where(
            models.BadgeEarn.workout_id.in_(ids)
        )
    ):
        found.setdefault(workout_id, []).append(medal_id)
    for row in found.values():
        row.sort(key=lambda medal_id: order.get(medal_id, len(order)))
    return found
