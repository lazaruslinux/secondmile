"""The medals: the catalogue, the rules that earn them, and their awarding.

Thirty-two medals in eight families. Five of the eight repeat: a marathon next
month is another Marathon, a big week in October is another 25-mile week. The
other three are the lifetime ladders, and they are the things here earned once
and ticked off, because a hundredth mile only ever happens once. Every rule that
follows says which of the two it is.

Two tables hold the earns, split by what earns them rather than by family.
badge_earns is one row per workout per medal: the four families a single session
earns (race, cycle, swim and time), and the lifetime ladders, whose rows hang on
the workout whose credit carried a total over the line. weekly_badge_earns is
one row per week per family, for the family a week earns, which is what lets a
week upgrade its medal in place as the miles add up.

Every threshold here is raw miles, never converted Miles. A 5K is a distance on
the ground, a 25-mile week is twenty-five miles walked, run, ridden, or swum,
and a lifetime ladder is every mile the body actually covered; no conversion
rate has any business changing what any of them is.
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
    # Miles the medal is earned at: one workout's distance for the race, cycle
    # and swim families, one week's total for the weekly family, and the
    # account's lifetime total for a lifetime ladder. Raw miles in every case.
    # Nothing at all for the time family, which is earned by a clock.
    distance_mi: float | None = None


# Catalogue order, which is the order the profile serves them in. Within every
# family that has thresholds they ascend, which is what makes "the highest one
# this qualifies for" a single pass.
CATALOG: tuple[Medal, ...] = (
    # The two the app is named for, and the humblest medals there are: one mile
    # covered, and the second one gone with it (Matthew 5:41). The names are the
    # owner's own and never change.
    Medal("race_1mi", "race", "First Mile", 1.0),
    Medal("race_2mi", "race", "Second Mile", 2.0),
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
    # One ride, at its own distances: Century is the classic hundred-mile club
    # ride, and raw distance on the road as every single-session medal is.
    Medal("cycle_10", "cycle", "10 Mile Ride", 10.0),
    Medal("cycle_25", "cycle", "25 Mile Ride", 25.0),
    Medal("cycle_50", "cycle", "50 Mile Ride", 50.0),
    Medal("cycle_100", "cycle", "Century", 100.0),
    Medal("swim_half", "swim", "Half Mile Swim", 0.5),
    Medal("swim_1", "swim", "Mile Swim", 1.0),
    Medal("swim_2", "swim", "2 Mile Swim", 2.0),
    # The three lifetime ladders, earned once each and read in raw miles: see
    # the section below. The odometer counts everything; the two sport ladders
    # count their own sport, because in one shared total a rider's miles vanish
    # into everybody's foot miles.
    Medal("lifetime_100", "lifetime", "100 Miles", 100.0),
    Medal("lifetime_250", "lifetime", "250 Miles", 250.0),
    Medal("lifetime_500", "lifetime", "500 Miles", 500.0),
    Medal("lifetime_1000", "lifetime", "1000 Miles", 1000.0),
    Medal("cycle_lifetime_100", "cycle_lifetime", "100 Miles Ridden", 100.0),
    Medal("cycle_lifetime_250", "cycle_lifetime", "250 Miles Ridden", 250.0),
    Medal("cycle_lifetime_500", "cycle_lifetime", "500 Miles Ridden", 500.0),
    Medal("cycle_lifetime_1000", "cycle_lifetime", "1000 Miles Ridden", 1000.0),
    # Shorter rungs, because a mile swum is not a mile ridden: fifty miles in
    # the water is a season's work where fifty on the road is a Saturday.
    Medal("swim_lifetime_10", "swim_lifetime", "10 Miles Swum", 10.0),
    Medal("swim_lifetime_25", "swim_lifetime", "25 Miles Swum", 25.0),
    Medal("swim_lifetime_50", "swim_lifetime", "50 Miles Swum", 50.0),
    Medal("swim_lifetime_100", "swim_lifetime", "100 Miles Swum", 100.0),
)

BY_ID: dict[str, Medal] = {row.id: row for row in CATALOG}


def _family(name: str) -> tuple[Medal, ...]:
    """One family in catalogue order, which is ascending by threshold."""
    return tuple(row for row in CATALOG if row.family == name)


RACE_MEDALS: tuple[Medal, ...] = _family("race")
WEEKLY_MEDALS: tuple[Medal, ...] = _family("weekly")
CYCLE_MEDALS: tuple[Medal, ...] = _family("cycle")
SWIM_MEDALS: tuple[Medal, ...] = _family("swim")
LIFETIME_MEDALS: tuple[Medal, ...] = _family("lifetime")
CYCLE_LIFETIME_MEDALS: tuple[Medal, ...] = _family("cycle_lifetime")
SWIM_LIFETIME_MEDALS: tuple[Medal, ...] = _family("swim_lifetime")


@dataclass(frozen=True)
class Ladder:
    """One lifetime ladder: the family it awards from, the activities whose raw
    miles climb it, and its rungs in ascending order."""

    family: str
    activities: tuple[str, ...]
    medals: tuple[Medal, ...]


# The three ladders climbed by a lifetime total rather than by one session. The
# odometer takes every mile from every activity; each sport ladder takes its own
# sport and nothing else, so a walk never moves the cycling one. Steps are not
# workouts and reach none of them.
LIFETIME_LADDERS: tuple[Ladder, ...] = (
    Ladder("lifetime", models.ACTIVITIES, LIFETIME_MEDALS),
    Ladder("cycle_lifetime", ("cycle",), CYCLE_LIFETIME_MEDALS),
    Ladder("swim_lifetime", ("swim",), SWIM_LIFETIME_MEDALS),
)

LIFETIME_FAMILIES = tuple(ladder.family for ladder in LIFETIME_LADDERS)

# Which table a family's earns live in. The split is the one thing about a
# family that is not data: a week cannot be keyed by a workout.
WORKOUT_FAMILIES = ("race", "time", "cycle", "swim") + LIFETIME_FAMILIES
WEEK_FAMILIES = ("weekly",)

# Feet are feet. A mile covered on foot is a mile, so the race family and the
# time family are earned by a walk exactly as by a run: one rule for both, and
# the pace flag still blocks either. The single-sport families below each read
# their own activity and nothing else.
FEET_ACTIVITIES = ("walk", "run")

# A time medal wants the smallest race medal's distance on the ground. Anything
# shorter is a stroll at an odd hour, and the line follows the race family down
# rather than being written out again.
MIN_TIME_MEDAL_MI = RACE_MEDALS[0].distance_mi

# Local hours, read in the instance timezone. Early Riser is the two hours
# before six; Night Owl is everything from eight in the evening until it.
EARLY_RISER_FROM = 4
EARLY_RISER_UNTIL = 6
NIGHT_OWL_FROM = 20


# --------------------------------------------------------------------------
# What one workout earns
# --------------------------------------------------------------------------


def _believable(workout: models.Workout) -> bool:
    """Whether the numbers on a workout are worth a medal at all.

    Never a workout the pace flag has already called impossible: a distance
    nobody covered is not a distance worth a medal.
    """
    return not (workout.flags or {}).get("impossible_pace")


def _eligible(workout: models.Workout) -> bool:
    """Whether a workout can earn one of the two on-foot families.

    On foot, walked or run, and believable. A ride and a swim are neither: each
    has a family of its own, at its own distances.
    """
    return workout.activity in FEET_ACTIVITIES and _believable(workout)


def _highest(
    workout: models.Workout, family: tuple[Medal, ...], activities: tuple[str, ...]
) -> Medal | None:
    """The highest medal of one family this workout's distance qualifies for.

    The highest one only, which is every distance family's rule: a marathon is a
    marathon, not also a 5K and a 10K and a half. Raw miles, one session's worth.
    """
    if workout.activity not in activities or not _believable(workout):
        return None
    best = None
    for medal in family:
        if workout.distance_mi + _EPSILON >= medal.distance_mi:
            best = medal
    return best


def _race_medal_for(workout: models.Workout) -> Medal | None:
    """The race medal one workout earns, or None. Walked or run, either way."""
    return _highest(workout, RACE_MEDALS, FEET_ACTIVITIES)


def _cycle_medal_for(workout: models.Workout) -> Medal | None:
    """The cycling medal one ride earns, or None. Rides only: the distances are
    a bike's, and nothing covered on foot reaches them the same way."""
    return _highest(workout, CYCLE_MEDALS, ("cycle",))


def _swim_medal_for(workout: models.Workout) -> Medal | None:
    """The swimming medal one swim earns, or None. Swims only, for the reason
    the cycling family is rides only, turned the other way up."""
    return _highest(workout, SWIM_MEDALS, ("swim",))


def _time_medal_for(workout: models.Workout) -> Medal | None:
    """The time-of-day medal one workout earns, or None.

    Read in the instance timezone, because the hour of the day is the whole
    point: a run stored at 12:44 UTC was a quarter to six in the morning to
    whoever ran it, and that is the only reading that means anything. Walked or
    run, either way: being out before six is the thing being marked.
    """
    if not _eligible(workout) or workout.distance_mi + _EPSILON < MIN_TIME_MEDAL_MI:
        return None
    hour = workout.start_ts.astimezone(SERVER_TZ).hour
    if EARLY_RISER_FROM <= hour < EARLY_RISER_UNTIL:
        return BY_ID["early_riser"]
    if hour >= NIGHT_OWL_FROM or hour < EARLY_RISER_FROM:
        return BY_ID["night_owl"]
    return None


# One rule per per-workout family, in catalogue order, each returning at most
# one medal. A workout can hold one from each, so a 5K before six earns the 5K
# and Early Riser both. The three distance families are gated to their own
# activities, so no workout ever comes away with two of them.
_WORKOUT_RULES = (_race_medal_for, _time_medal_for, _cycle_medal_for, _swim_medal_for)


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
# What the lifetime ladders earn
# --------------------------------------------------------------------------


def zero_lifetime() -> dict[str, float]:
    """A lifetime reading of nothing, one running total per ladder. Where a
    replay of a whole history starts."""
    return {ladder.family: 0.0 for ladder in LIFETIME_LADDERS}


def lifetime_so_far(db: Session, user_id: int) -> dict[str, float]:
    """What this account's already credited workouts come to, per ladder.

    Raw miles, added up from the workouts rather than read off the progress row:
    that row holds converted Miles, which is not what these ladders climb, and
    nothing stores this total. A deleted workout is out of it, so a credit
    landing after a deletion reads the same total a clean rebuild would.
    """
    totals = zero_lifetime()
    rows = db.execute(
        select(models.Workout.activity, func.sum(models.Workout.distance_mi))
        .join(
            models.ProcessedWorkout,
            models.ProcessedWorkout.workout_id == models.Workout.id,
        )
        .where(models.Workout.user_id == user_id, models.Workout.deleted_at.is_(None))
        .group_by(models.Workout.activity)
    ).all()
    for activity, miles in rows:
        for ladder in LIFETIME_LADDERS:
            if activity in ladder.activities:
                totals[ladder.family] += miles or 0.0
    return totals


def _crossed(ladder: Ladder, total_before: float, total_after: float) -> list[Medal]:
    """The rungs one credit carries a ladder's total past.

    Two totals rather than one, because the medal belongs to the crossing: a
    credit that takes an account from 98 miles to 260 earns both the hundred and
    the two hundred and fifty, and a credit that starts past a line earns
    nothing from it.
    """
    return [
        medal
        for medal in ladder.medals
        if total_before + _EPSILON < medal.distance_mi <= total_after + _EPSILON
    ]


def _held_lifetime_ids(db: Session, user_id: int) -> set[str]:
    """Which lifetime medals this account already has. One query, because the
    ladders are earned once each and the check is what enforces it."""
    ids = [medal.id for ladder in LIFETIME_LADDERS for medal in ladder.medals]
    return set(
        db.execute(
            select(models.BadgeEarn.badge_id).where(
                models.BadgeEarn.user_id == user_id,
                models.BadgeEarn.badge_id.in_(ids),
            )
        ).scalars()
    )


def award_lifetime_medals(
    db: Session,
    user_id: int,
    workout: models.Workout,
    totals: dict[str, float],
) -> list[Medal]:
    """Add one credit's raw miles to the lifetime totals and record every line
    the addition crossed. Returns the rows written.

    `totals` is the caller's running reading, advanced here: the walk carries it
    workout by workout rather than asking the database for it each time, which
    is what keeps a sweep of a hundred workouts one query.

    Earned once each, which is the one place this file departs from everything
    around it: a second hundredth mile is not a thing that happens. The held
    check is what says so, since the unique key next door only refuses the same
    medal on the same workout.

    The row hangs on the workout whose credit crossed the line and carries that
    workout's start time, so a rebuild writes the same row: the replay walks the
    history oldest first from a total of nothing, which is the same walk in the
    same order, so the same workout crosses the same threshold.

    The pace flag does not block these, and deliberately. A ladder counts a
    total rather than a claim about one session, and a flagged workout's miles
    are in that total either way; refusing the crossing would lose the medal
    outright rather than move it, because a line is only ever crossed once.
    """
    crossed: list[Medal] = []
    for ladder in LIFETIME_LADDERS:
        if workout.activity not in ladder.activities:
            continue
        before = totals[ladder.family]
        totals[ladder.family] = before + workout.distance_mi
        crossed.extend(_crossed(ladder, before, totals[ladder.family]))
    if not crossed:
        return []
    held = _held_lifetime_ids(db, user_id)
    written = []
    for medal in crossed:
        if medal.id in held:
            continue
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
