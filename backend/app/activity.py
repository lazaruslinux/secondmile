"""Everything the server knows about a workout before it becomes a row.

Which of the four activities an export name means, how to get its numbers into
miles and kilocalories, how to read the several shapes a start time arrives in,
and which soft flags it earns. Shared by the sync path and the manual entry
form so the two can never drift apart on what counts as suspicious.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import (
    MAX_CYCLE_SPEED_MPH,
    MAX_SWIM_SPEED_MPH,
    MIN_PACE_MIN_PER_MI,
    SERVER_TZ,
    daily_cap_mi,
)

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


def classify(name: str | None) -> str | None:
    """The activity an export name means, or None if it is not one of the four."""
    lowered = (name or "").lower()
    for keyword, activity in _NAME_KEYWORDS:
        if keyword in lowered:
            return activity
    return None


def _quantity(value) -> float | None:
    """The number out of a measurement, which may be bare or wrapped in a dict."""
    if isinstance(value, dict):
        for key in ("qty", "quantity", "value", "average", "avg"):
            if key in value:
                return _quantity(value[key])
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


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
    such as the manual entry form's datetime input, so local time is the only
    reading that does not silently move the workout by several hours.
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
    data = payload.get("data")
    # Some export versions put the list at the top level instead of under
    # "data", and there is no cost to accepting both.
    workouts = None
    if isinstance(data, dict):
        workouts = data.get("workouts")
    if workouts is None:
        workouts = payload.get("workouts")
    if not isinstance(workouts, list):
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
        parsed.append(
            ParsedWorkout(
                activity=activity,
                start_ts=start,
                duration_s=duration_s,
                distance_mi=to_miles(entry.get("distance")),
                active_kcal=to_kcal(
                    entry.get("activeEnergyBurned") or entry.get("activeEnergy")
                ),
                avg_hr=avg_hr if avg_hr and avg_hr > 0 else None,
            )
        )
    return parsed, ignored


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


def local_day_bounds(moment: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """The UTC instants a workout's local calendar day starts and ends at.

    Built from the next calendar date rather than by adding 24 hours, because
    the day a clock change falls on is 23 or 25 hours long and adding a fixed
    day would put an evening workout in the wrong bucket twice a year.
    """
    local = moment.astimezone(SERVER_TZ)
    start = dt.datetime.combine(local.date(), dt.time.min, tzinfo=SERVER_TZ)
    end = dt.datetime.combine(local.date() + dt.timedelta(days=1), dt.time.min, tzinfo=SERVER_TZ)
    return start, end


def over_daily_cap(db: Session, user_id: int, activity: str, start_ts: dt.datetime) -> bool:
    """Whether this activity's stored total for the workout's local day is past
    the configured cap.

    Called after the row is written, so the workout that crosses the line is the
    first one flagged, and everything added to that day afterwards is flagged
    too. Earlier workouts on the same day keep their unflagged state: they were
    plausible when they arrived, and the flag is a marker on the entry that made
    the day implausible, not a verdict on the day.
    """
    day_start, day_end = local_day_bounds(start_ts)
    total = db.execute(
        select(func.coalesce(func.sum(models.Workout.distance_mi), 0.0)).where(
            models.Workout.user_id == user_id,
            models.Workout.activity == activity,
            models.Workout.start_ts >= day_start,
            models.Workout.start_ts < day_end,
        )
    ).scalar_one()
    return float(total) > daily_cap_mi(activity)


def week_start(moment: dt.datetime) -> dt.date:
    """The Monday of the local week a moment falls in."""
    local = moment.astimezone(SERVER_TZ).date()
    return local - dt.timedelta(days=local.weekday())


def serialize(workout: models.Workout) -> dict:
    """One workout in the shape every endpoint returns it in."""
    return {
        "id": workout.id,
        "activity": workout.activity,
        "start_ts": workout.start_ts.isoformat(),
        "duration_s": workout.duration_s,
        "distance_mi": round(workout.distance_mi, 3),
        "active_kcal": round(workout.active_kcal, 1),
        "avg_hr": round(workout.avg_hr, 1) if workout.avg_hr is not None else None,
        "source": workout.source,
        "flags": workout.flags or {},
    }
