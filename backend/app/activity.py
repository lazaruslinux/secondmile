"""Everything the server knows about a workout before it becomes a row.

Which of the four activities an export name means, how to get its numbers into
miles and kilocalories, how to read the several shapes a start time arrives in,
and which soft flags it earns. The sync path is the only way a workout arrives,
and this is where it is decided what counts as suspicious.
"""

import datetime as dt
import math
import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import (
    MAX_CYCLE_SPEED_MPH,
    MAX_SWIM_SPEED_MPH,
    MAX_WORKOUT_DISTANCE_MI,
    MAX_WORKOUT_DURATION_S,
    MAX_WORKOUT_HR,
    MAX_WORKOUT_KCAL,
    MILES_PER_RAW,
    MIN_PACE_MIN_PER_MI,
    MIN_WORKOUT_HR,
    SERVER_TZ,
    daily_cap_mi,
)

# The key a Health Auto Export entry carries its GPS trace under. Named rather
# than typed out twice, because the strip that keeps traces out of the ingest
# log has to remove exactly what parse_payload below reads.
ROUTE_KEY = "route"

# Matched against the export's workout name, lower-cased, as a substring. Apple
# names the same activity several ways ("Outdoor Walk", "Indoor Walk",
# "Walking"), and third-party apps invent their own, so matching on a fragment
# survives names nobody has written down yet. Anything unmatched is ignored
# rather than guessed at.
_NAME_KEYWORDS = (
    ("swim", "swim"),
    ("walk", "walk"),
    ("hik", "walk"),
    ("run", "run"),
    ("jog", "run"),
    ("cycl", "cycle"),
    ("bik", "cycle"),
)

# Everything is stored in miles. The export declares its own units because the
# phone follows the owner's locale, not ours.
_MILES_PER = {
    "mi": 1.0,
    "mile": 1.0,
    "miles": 1.0,
    "km": 0.621371,
    "kilometer": 0.621371,
    "kilometers": 0.621371,
    "m": 0.000621371,
    "meter": 0.000621371,
    "meters": 0.000621371,
    "yd": 0.000568182,
    "yard": 0.000568182,
    "yards": 0.000568182,
}

# Energy arrives as kilocalories or kilojoules. "cal" is included because Apple
# writes a dietary Calorie with a capital C, which is a kilocalorie; an export
# saying "cal" has never meant a gram calorie in practice.
_KCAL_PER = {
    "kcal": 1.0,
    "cal": 1.0,
    "calories": 1.0,
    "kj": 1.0 / 4.184,
    "kilojoules": 1.0 / 4.184,
}

# The two metrics the pedometer sends that this app has any use for, matched on
# a name with everything but its letters and digits taken out. Apple writes the
# same measurement as "walking_running_distance" in an export and "Walking +
# Running Distance" on a screen, and HealthKit itself calls it
# distanceWalkingRunning, so the fragments are matched rather than the spelling.
# Everything else in the metrics array is ignored and logged, exactly as an
# unmatched workout is.
_STEP_NAMES = frozenset({"stepcount", "steps"})
_STEP_DISTANCE_NAMES = frozenset(
    {
        "walkingrunningdistance",
        "walkingandrunningdistance",
        "walkrundistance",
        "distancewalkingrunning",
    }
)

# Start-time shapes seen in the wild. fromisoformat covers the ISO ones on its
# own; these are for the export that writes the offset after a space, which is
# not ISO and which fromisoformat rejects.
_START_FORMATS = ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S.%f %z", "%Y-%m-%d %H:%M:%S")


@dataclass
class ParsedWorkout:
    activity: str
    start_ts: dt.datetime
    duration_s: int
    distance_mi: float
    active_kcal: float
    avg_hr: float | None
    # The export's GPS trace, exactly as it arrived, or None. Carried rather
    # than parsed here so the pairing of a workout with its own trace is made
    # once, in the one place that reads the export.
    route: object | None = None


@dataclass
class DayMetrics:
    """One server-timezone day of pedometer readings, as an export claims them.

    Both numbers are what the phone said, and neither of them earns anything:
    steps are stored and shown. What is done with a day is progress.record_steps'
    business, which this side of the parse knows nothing about.
    """

    steps: float = 0.0
    distance_mi: float = 0.0


def classify(name: str | None) -> str | None:
    """The activity an export name means, or None if it is not one of the four."""
    lowered = (name or "").lower()
    for keyword, activity in _NAME_KEYWORDS:
        if keyword in lowered:
            return activity
    return None


def _raw_quantity(value) -> float | None:
    """The number out of a measurement, which may be bare or wrapped in a dict.

    May be non-finite. Deciding what to do about that is _quantity's job and
    _unusable's; this only reads.
    """
    if isinstance(value, dict):
        for key in ("qty", "quantity", "value", "average", "avg"):
            if key in value:
                return _raw_quantity(value[key])
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except OverflowError:
            # JSON integers have no width limit, so a literal too large for a
            # float is reachable. It is an out of range number, not a missing
            # one, so it reads as one.
            return math.inf if value > 0 else -math.inf
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _quantity(value) -> float | None:
    """The number out of a measurement, or None if there is not a usable one.

    Not finite reads as not there. JSON is allowed to write NaN and Infinity as
    bare literals and Python's parser accepts both, a NaN compares false against
    every bound it is tested against, and round() raises on one. A single such
    value stored on a workout is an account that cannot load its progress again.
    """
    number = _raw_quantity(value)
    return number if number is not None and math.isfinite(number) else None


def _unusable(value) -> bool:
    """Whether a measurement carries a number that is not finite.

    Missing does not count: plenty of real sessions record no distance, and
    to_miles already reads an absent one as zero.
    """
    number = _raw_quantity(value)
    return number is not None and not math.isfinite(number)


def _units(value, default: str) -> str:
    if isinstance(value, dict):
        raw = value.get("units") or value.get("unit") or default
        return str(raw).strip().lower()
    return default


def to_miles(value) -> float:
    """A distance measurement in miles. Unknown or missing reads as zero.

    Zero rather than a rejection: a pool swim with no distance recorded is still
    a swim that happened, and the calories from it still count. Dropping the
    whole workout over one absent field would lose more than it protects.
    """
    qty = _quantity(value)
    if qty is None or qty < 0:
        return 0.0
    return qty * _MILES_PER.get(_units(value, "mi"), 1.0)


def to_kcal(value) -> float:
    """An energy measurement in kilocalories. Unknown or missing reads as zero."""
    qty = _quantity(value)
    if qty is None or qty < 0:
        return 0.0
    return qty * _KCAL_PER.get(_units(value, "kcal"), 1.0)


def ensure_aware(value: dt.datetime) -> dt.datetime:
    """Attach the server timezone to a naive timestamp.

    A timestamp without an offset came from something that thinks in local time,
    such as an export that wrote the wall clock and nothing else, so local time
    is the only reading that does not silently move the workout by several
    hours.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=SERVER_TZ)


def parse_start(raw) -> dt.datetime | None:
    """A workout's start time, or None if it cannot be read at all."""
    if isinstance(raw, dt.datetime):
        return ensure_aware(raw)
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        return ensure_aware(dt.datetime.fromisoformat(text))
    except ValueError:
        pass
    for fmt in _START_FORMATS:
        try:
            return ensure_aware(dt.datetime.strptime(text, fmt))
        except ValueError:
            continue
    return None


def workout_entries(payload) -> list | None:
    """The export's list of workout entries, or None if it does not have one.

    Separate from parse_payload so the sync endpoint can count what arrived
    before it parses any of it.
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    # Some export versions put the list at the top level instead of under
    # "data", and there is no cost to accepting both.
    workouts = data.get("workouts") if isinstance(data, dict) else None
    if workouts is None:
        workouts = payload.get("workouts")
    return workouts if isinstance(workouts, list) else None


def without_routes(payload):
    """The export as it should be stored: everything except the GPS traces.

    The one key parse_payload reads a trace from, removed from every entry. A
    raw trace is the only part of an export that says where its owner lives, and
    by the time this runs the line worth keeping is already drawn into
    workout_routes with both ends trimmed off, so the stored copy keeps
    everything that could ever be replayed and nothing that could not.

    A copy rather than an edit in place: the caller is still holding parsed
    workouts that point at the original arrays, and an ORM column set to the
    object it already holds is not seen as changed. The payload itself comes
    back untouched when there is nothing to strip, which is what makes a second
    pass over an already-stripped row free.
    """
    entries = workout_entries(payload)
    if entries is None:
        return payload
    if not any(isinstance(entry, dict) and ROUTE_KEY in entry for entry in entries):
        return payload
    cleaned = [
        {key: value for key, value in entry.items() if key != ROUTE_KEY}
        if isinstance(entry, dict)
        else entry
        for entry in entries
    ]
    stripped = dict(payload)
    data = stripped.get("data")
    # Put the list back where workout_entries found it, in the same order it
    # looks, or the next reader sees the untouched copy.
    if isinstance(data, dict) and isinstance(data.get("workouts"), list):
        stripped["data"] = {**data, "workouts": cleaned}
    else:
        stripped["workouts"] = cleaned
    return stripped


def parse_payload(payload) -> tuple[list[ParsedWorkout], list[dict]]:
    """Read a Health Auto Export workouts export into workouts and refusals.

    Returns the workouts that could be read and, separately, one record per
    entry that could not be, naming the reason. The refusals go into the ingest
    log rather than into the response, so a self-hoster debugging a sync has
    something specific to look at without the phone learning anything useful.
    """
    parsed: list[ParsedWorkout] = []
    ignored: list[dict] = []

    if not isinstance(payload, dict):
        return parsed, [{"index": 0, "reason": "payload is not an object"}]
    workouts = workout_entries(payload)
    if workouts is None:
        # An export of metrics and nothing else is a whole automation rather
        # than a broken export: the pedometer is set up as its own, and a
        # refusal logged on every one of its syncs would be noise about
        # something that is working. A payload carrying neither list is still
        # the mistake it always was.
        if metric_entries(payload) is not None:
            return parsed, ignored
        return parsed, [{"index": 0, "reason": "no workouts list in payload"}]

    for index, entry in enumerate(workouts):
        if not isinstance(entry, dict):
            ignored.append({"index": index, "reason": "entry is not an object"})
            continue
        name = entry.get("name") or entry.get("workoutActivityType") or entry.get("type")
        activity = classify(name if isinstance(name, str) else None)
        if activity is None:
            ignored.append({"index": index, "name": name, "reason": "unsupported activity"})
            continue
        start = parse_start(entry.get("start") or entry.get("startDate"))
        if start is None:
            ignored.append({"index": index, "name": name, "reason": "unreadable start time"})
            continue
        # Duration arrives in seconds and is often fractional. Rounding to whole
        # seconds is what makes it usable as part of the dedupe key: the same
        # workout re-exported has to produce the same integer every time.
        duration = _quantity(entry.get("duration"))
        duration_s = max(0, round(duration)) if duration is not None else 0
        heart = entry.get("avgHeartRate")
        if heart is None:
            heart = entry.get("heartRate")
        if heart is None:
            heart = entry.get("averageHeartRate")
        avg_hr = _quantity(heart)
        distance = entry.get("distance")
        energy = entry.get("activeEnergyBurned") or entry.get("activeEnergy")
        if any(_unusable(item) for item in (entry.get("duration"), distance, energy, heart)):
            # Dropped whole rather than read as a workout with the bad field
            # missing. Zero is a claim about what happened, and it is not one
            # this entry supports.
            ignored.append({"index": index, "name": name, "reason": "value is not a number"})
            continue
        distance_mi = to_miles(distance)
        active_kcal = to_kcal(energy)
        if (
            duration_s > MAX_WORKOUT_DURATION_S
            or distance_mi > MAX_WORKOUT_DISTANCE_MI
            or active_kcal > MAX_WORKOUT_KCAL
        ):
            # Ignored rather than clamped: a number this far out means the entry
            # is not describing what it claims to, and inventing a plausible
            # value for it would put a workout nobody did into the history.
            ignored.append({"index": index, "name": name, "reason": "numbers out of range"})
            continue
        parsed.append(
            ParsedWorkout(
                activity=activity,
                start_ts=start,
                duration_s=duration_s,
                distance_mi=distance_mi,
                active_kcal=active_kcal,
                # A reading outside what a heart does is dropped on its own
                # rather than taking the workout with it: nothing is scored from
                # it, and the session still happened.
                avg_hr=avg_hr if avg_hr and MIN_WORKOUT_HR <= avg_hr <= MAX_WORKOUT_HR else None,
                route=entry.get(ROUTE_KEY),
            )
        )
    return parsed, ignored


def _metric_key(name: str | None) -> str:
    """A metric's name with everything but its letters and digits taken out.

    One spelling to match against, so "step_count", "Step Count" and "steps"
    are the same question rather than three.
    """
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def metric_entries(payload) -> list | None:
    """The export's list of metrics, or None if it does not carry one.

    Found in both places workout_entries looks, and for the same reason: the
    export tool has put the arrays under "data" and at the top level over its
    versions, and accepting both costs nothing.
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    metrics = data.get("metrics") if isinstance(data, dict) else None
    if metrics is None:
        metrics = payload.get("metrics")
    return metrics if isinstance(metrics, list) else None


def metric_points(payload) -> int:
    """How many samples the export's metrics carry between them.

    Counted before anything is parsed, the way the workout entries are: a
    metric is allowed to arrive at any resolution the phone likes, and an
    export of a million samples should cost one length check rather than a
    million reads.
    """
    total = 0
    for entry in metric_entries(payload) or []:
        points = entry.get("data") if isinstance(entry, dict) else None
        if isinstance(points, list):
            total += len(points)
    return total


def parse_metrics(payload) -> tuple[dict[dt.date, DayMetrics], list[dict]]:
    """Read the export's metrics into one reading per server-timezone day.

    Two of them are read and the rest are ignored and named, exactly as an
    unmatched workout is: the step count and the walking and running distance.
    Both are flavour; nothing in this file or downstream of it earns anything
    from either.

    Summed per day rather than taken as they arrive, because the phone sends
    whatever resolution it feels like: a day may be one sample or twenty-four,
    and the day is what is stored. The date each sample
    carries is read in the instance timezone for the same reason a workout's
    day is: a walk at eleven at night belongs to the day whoever took it says
    it does.
    """
    days: dict[dt.date, DayMetrics] = {}
    ignored: list[dict] = []

    entries = metric_entries(payload)
    if entries is None:
        return days, ignored

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            ignored.append({"metric": index, "reason": "entry is not an object"})
            continue
        name = entry.get("name") or entry.get("identifier")
        key = _metric_key(name if isinstance(name, str) else None)
        if key in _STEP_NAMES:
            counting = True
        elif key in _STEP_DISTANCE_NAMES:
            counting = False
        else:
            ignored.append({"metric": index, "name": name, "reason": "unsupported metric"})
            continue
        points = entry.get("data")
        if not isinstance(points, list):
            ignored.append({"metric": index, "name": name, "reason": "no data points"})
            continue
        # Declared once per metric and allowed to be said again on a sample,
        # because the phone follows its owner's locale and this app stores
        # miles. A count has no units and never reads them.
        units = _units(entry, "mi")
        for point in points:
            if not isinstance(point, dict):
                ignored.append({"metric": index, "name": name, "reason": "sample is not an object"})
                continue
            when = parse_start(point.get("date") or point.get("start") or point.get("startDate"))
            if when is None:
                ignored.append({"metric": index, "name": name, "reason": "unreadable date"})
                continue
            qty = _quantity(point)
            if qty is None or qty < 0:
                # Dropped on its own rather than taking the day with it. The
                # rest of the samples still describe a day that happened.
                ignored.append({"metric": index, "name": name, "reason": "value is not a number"})
                continue
            reading = days.setdefault(when.astimezone(SERVER_TZ).date(), DayMetrics())
            if counting:
                reading.steps += qty
            else:
                reading.distance_mi += qty * _MILES_PER.get(_units(point, units), 1.0)
    return days, ignored


def converted_miles(activity: str, distance_mi: float) -> float:
    """What one workout's distance is worth as Miles.

    Effort equivalence rather than distance: an hour of swimming is not an hour
    of cycling, and everything the game counts is counted in effort. Lives here
    rather than in the pipeline because the grove, the chest ladder, and the profile
    totals need the same answer and must never drift from it.
    """
    return distance_mi * MILES_PER_RAW[activity]


def impossible_pace(activity: str, duration_s: int, distance_mi: float) -> bool:
    """Whether the numbers describe something a human body did not do.

    Distance without duration counts, because a workout that covered ground in
    no time is the clearest case of all. Duration without distance does not:
    plenty of real sessions record no distance.
    """
    if distance_mi <= 0:
        return False
    if duration_s <= 0:
        return True
    if activity in ("walk", "run"):
        return (duration_s / 60.0) / distance_mi < MIN_PACE_MIN_PER_MI
    speed_mph = distance_mi / (duration_s / 3600.0)
    if activity == "cycle":
        return speed_mph > MAX_CYCLE_SPEED_MPH
    return speed_mph > MAX_SWIM_SPEED_MPH


def day_bounds(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """The instants one local calendar day starts and ends at.

    Built from the next calendar date rather than by adding 24 hours, because
    the day a clock change falls on is 23 or 25 hours long and adding a fixed
    day would put an evening workout in the wrong bucket twice a year.
    """
    start = dt.datetime.combine(day, dt.time.min, tzinfo=SERVER_TZ)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, tzinfo=SERVER_TZ)
    return start, end


def local_day_bounds(moment: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """The instants a workout's own local calendar day starts and ends at."""
    return day_bounds(moment.astimezone(SERVER_TZ).date())


def over_daily_cap(db: Session, user_id: int, activity: str, start_ts: dt.datetime) -> bool:
    """Whether this activity's stored total for the workout's local day is past
    the configured cap.

    Called after the row is written, so the workout that crosses the line is the
    first one flagged, and everything added to that day afterwards is flagged
    too. Earlier workouts on the same day keep their unflagged state: they were
    plausible when they arrived, and the flag is a marker on the entry that made
    the day implausible, not a verdict on the day.

    A deleted workout is not part of the day's total. Somebody who has already
    taken the bogus hundred-mile ride back should not have the next real one
    flagged by it.
    """
    day_start, day_end = local_day_bounds(start_ts)
    total = db.execute(
        select(func.coalesce(func.sum(models.Workout.distance_mi), 0.0)).where(
            models.Workout.user_id == user_id,
            models.Workout.deleted_at.is_(None),
            models.Workout.activity == activity,
            models.Workout.start_ts >= day_start,
            models.Workout.start_ts < day_end,
        )
    ).scalar_one()
    return float(total) > daily_cap_mi(activity)


def week_of(day: dt.date) -> dt.date:
    """The Monday of the week a local calendar day falls in."""
    return day - dt.timedelta(days=day.weekday())


def week_start(moment: dt.datetime) -> dt.date:
    """The Monday of the local week a moment falls in."""
    return week_of(moment.astimezone(SERVER_TZ).date())
