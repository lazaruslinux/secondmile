"""What an export says about a workout beyond the numbers on its row.

A Health Auto Export workout entry carries an array per minute of the session
and a handful of whole-session summaries beside them: how far and how many steps
in each minute, what the heart was doing, how much the session climbed, and what
the air was like. The workout row keeps six numbers, and everything else an
entry said is read here.

None of it earns anything. Every reading in this file is something to look at on
a screen: no medal, no conversion, no flag and no total reads any of it, which is
the same two-lane law the rest of the app is built on.

Nothing here may raise into an ingest, for the reason the route module says the
same thing about a trace. The detail is decoration on a workout, and a workout
that happened must never fail to import because its arrays were odd. A field
that cannot be read is nothing at all rather than an error, everywhere below,
and the whole of it is guarded once more where the sync calls in.

Why any of it is stored at all: the payload it is read out of is deleted at
INGEST_LOG_RETENTION_DAYS on the account's next sync, so these rows are the only
copy of a session's detail that outlives the log it arrived in.
"""

import datetime as dt
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import bests, models
from app.activity import parse_start, plain_name, quantity, to_kcal, to_miles, unit_of
from app.config import (
    MAX_SAMPLE_DISTANCE_MI,
    MAX_SAMPLE_KCAL,
    MAX_SAMPLE_STEPS,
    MAX_WORKOUT_ELEVATION_FT,
    MAX_WORKOUT_HR,
    MAX_WORKOUT_HUMIDITY_PCT,
    MAX_WORKOUT_SAMPLES,
    MAX_WORKOUT_TEMP_F,
    MIN_WORKOUT_HR,
    MIN_WORKOUT_TEMP_F,
)

log = logging.getLogger("secondmile.samples")

# The per-minute arrays worth reading, and the spellings each has been seen
# under. Matched on a name with everything but its letters and digits taken
# out, exactly as the metrics array is matched, because the export tool writes
# the same measurement as "stepCount" in one version and "step_count" in
# another. Everything else in an entry is left alone.
#
# There is no per-minute cadence array in an export, whatever a watch shows on
# its own screen. Steps in the minute is the reading that stands in for it, and
# for a walk or a run it is the same number.
_PER_MINUTE = {
    "distance": frozenset(
        {"walkingandrunningdistance", "walkingrunningdistance", "distancewalkingrunning"}
    ),
    "steps": frozenset({"stepcount", "steps"}),
    # Only the array. The entry's "heartRate" is a summary object of three
    # numbers for the whole session and is read further down as one.
    "heart": frozenset({"heartratedata"}),
    # Active calories only. An entry carries a basal array beside this one and
    # it is the body ticking over rather than the session, which is the same
    # line the workout row's own calories are drawn on.
    "energy": frozenset({"activeenergy", "activeenergyburned"}),
}

# Everything is stored in feet, and the export declares its own units because
# the phone follows its owner's locale. Unknown units read as feet, the way an
# unknown distance unit reads as miles.
_FEET_PER = {
    "ft": 1.0,
    "foot": 1.0,
    "feet": 1.0,
    "m": 3.28084,
    "meter": 3.28084,
    "meters": 3.28084,
    "metre": 3.28084,
    "metres": 3.28084,
}

# And the one temperature unit that is not what the column stores. Anything
# else, including a reading with no units at all, is already Fahrenheit.
_CELSIUS = frozenset({"degc", "c", "celsius", "centigrade"})


@dataclass
class Sample:
    """One minute of a session, as the export described it.

    Every measurement is optional because the arrays are independent of each
    other: they start and stop at their own moments, and a phone that lost its
    strap sends heart rate for half a walk and distance for all of it.
    """

    minute: int
    distance_mi: float | None = None
    hr_min: int | None = None
    hr_avg: int | None = None
    hr_max: int | None = None
    steps: int | None = None
    active_kcal: float | None = None


@dataclass
class Details:
    """One entry's detail: its minutes, and the summaries for the whole of it."""

    minutes: list[Sample] = field(default_factory=list)
    elevation_gain_ft: float | None = None
    max_hr: int | None = None
    temperature_f: float | None = None
    humidity_pct: float | None = None


def _keyed(item: dict) -> dict:
    """One object's fields under one spelling of each name.

    The heart rate samples arrive with capital initials, "Min", "Avg" and
    "Max", and other exports write them in lower case. Normalising the keys
    once means the readers below ask for a field rather than for a spelling.
    """
    return {plain_name(str(key)): value for key, value in item.items()}


def _bounded(value, low: float, high: float) -> float | None:
    """One reading, or None when there is no usable number between those two.

    Out of range is dropped to nothing rather than clamped, on the terms the
    workout parse drops a bad measurement: a number this far out is not
    describing what it claims to, and a plausible value invented for it would
    be a fact about a minute that nobody lived.
    """
    number = quantity(value)
    if number is None or number < low or number > high:
        return None
    return number


def _when(item: dict) -> dt.datetime | None:
    """The moment one sample says it covers, or None if it cannot be read."""
    return parse_start(item.get("date") or item.get("start") or item.get("startDate"))


def _arrays(entry: dict) -> dict[str, list]:
    """The per-minute arrays this entry carries, under the names above."""
    found: dict[str, list] = {}
    for key, value in entry.items():
        if not isinstance(value, list):
            continue
        plain = plain_name(str(key))
        for name, spellings in _PER_MINUTE.items():
            if plain in spellings:
                found.setdefault(name, value)
    return found


def _sample_distance(item: dict) -> float | None:
    """How far one minute covered, in miles, or None if it did not say."""
    qty = quantity(item)
    if qty is None or qty < 0:
        return None
    miles = to_miles(item)
    return miles if miles <= MAX_SAMPLE_DISTANCE_MI else None


def _sample_energy(item: dict) -> float | None:
    """The active calories one minute burned, or None if it did not say.

    The phone declares its own units here the way it does everywhere else, and
    a locale that counts in kilojoules is converted on the way in.
    """
    qty = quantity(item)
    if qty is None or qty < 0:
        return None
    kcal = to_kcal(item)
    return kcal if kcal <= MAX_SAMPLE_KCAL else None


def _heart_rate(fields: dict, name: str) -> int | None:
    """One of a heart rate sample's three numbers, rounded to a whole beat."""
    reading = _bounded(fields.get(name), MIN_WORKOUT_HR, MAX_WORKOUT_HR)
    return round(reading) if reading is not None else None


def _minutes(entry: dict) -> list[Sample]:
    """The entry's arrays merged into one row per minute.

    The three arrays are read against each other rather than side by side. They
    can start at different moments, skip minutes the phone was not recording,
    and be different lengths, so each sample is placed by the moment it says it
    covers, counted in whole minutes from the earliest moment any of them
    names. Only when a sample carries no readable date at all does its position
    in its own array stand in, which is the best a malformed export can be
    asked for and still says something true about the shape of the session.

    A minute already described is left as it was found. One reading per minute
    is what an export sends; a second is the export repeating itself, and the
    first of them is as good an answer as the last.
    """
    arrays = _arrays(entry)
    if not arrays:
        return []

    earliest: dt.datetime | None = None
    for items in arrays.values():
        for item in items:
            if not isinstance(item, dict):
                continue
            when = _when(item)
            if when is not None and (earliest is None or when < earliest):
                earliest = when

    rows: dict[int, Sample] = {}
    for name, items in arrays.items():
        for order, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            when = _when(item)
            if when is None or earliest is None:
                minute = order
            else:
                minute = int((when - earliest).total_seconds() // 60)
            if minute < 0:
                continue
            row = rows.setdefault(minute, Sample(minute=minute))
            if name == "distance":
                if row.distance_mi is None:
                    row.distance_mi = _sample_distance(item)
            elif name == "steps":
                if row.steps is None:
                    steps = _bounded(item, 0.0, MAX_SAMPLE_STEPS)
                    row.steps = round(steps) if steps is not None else None
            elif name == "energy":
                if row.active_kcal is None:
                    row.active_kcal = _sample_energy(item)
            elif row.hr_avg is None and row.hr_min is None and row.hr_max is None:
                fields = _keyed(item)
                row.hr_min = _heart_rate(fields, "min")
                row.hr_avg = _heart_rate(fields, "avg")
                row.hr_max = _heart_rate(fields, "max")

    # Sorted so a details screen reads the rows in the order the session
    # happened, and cut to the cap so an export whose arrays repeat themselves
    # costs one slice rather than a table of rows nobody will ever draw.
    ordered = sorted(rows.values(), key=lambda row: row.minute)
    return ordered[:MAX_WORKOUT_SAMPLES]


def _elevation(value) -> float | None:
    """How much a session climbed, in feet. Negative is not a climb."""
    qty = quantity(value)
    if qty is None or qty < 0:
        return None
    feet = qty * _FEET_PER.get(plain_name(unit_of(value, "ft")), 1.0)
    return feet if feet <= MAX_WORKOUT_ELEVATION_FT else None


def _max_hr(fields: dict) -> int | None:
    """The highest beat the session saw.

    An entry says this twice: once as its own summary and once inside the
    heart rate object beside it. The summary is read first and the duplicate is
    the fallback, because an export that carries only the object is still an
    export that knows the answer.
    """
    reading = _bounded(fields.get("maxheartrate"), MIN_WORKOUT_HR, MAX_WORKOUT_HR)
    if reading is None:
        heart = fields.get("heartrate")
        if isinstance(heart, dict):
            reading = _bounded(_keyed(heart).get("max"), MIN_WORKOUT_HR, MAX_WORKOUT_HR)
    return round(reading) if reading is not None else None


def _temperature(value) -> float | None:
    """The air the session happened in, in Fahrenheit."""
    qty = quantity(value)
    if qty is None:
        return None
    if plain_name(unit_of(value, "degf")) in _CELSIUS:
        qty = qty * 9.0 / 5.0 + 32.0
    return qty if MIN_WORKOUT_TEMP_F <= qty <= MAX_WORKOUT_TEMP_F else None


def parse(entry) -> Details:
    """Read one export entry's detail. Never raises and never refuses.

    Anything absent, malformed, or past what a body and a day produce comes
    back as nothing, field by field. An entry with none of it, which is what a
    workout from an older export or another phone looks like, reads as empty
    detail rather than as a problem.
    """
    if not isinstance(entry, dict):
        return Details()
    fields = _keyed(entry)
    return Details(
        minutes=_minutes(entry),
        elevation_gain_ft=_elevation(fields.get("elevationup")),
        max_hr=_max_hr(fields),
        temperature_f=_temperature(fields.get("temperature")),
        humidity_pct=_bounded(fields.get("humidity"), 0.0, MAX_WORKOUT_HUMIDITY_PCT),
    )


def store(db: Session, workout_id: int, minutes: list[Sample]) -> int:
    """Write one workout's per-minute rows. Returns how many were written.

    Only ever called for a workout that has none. The unique key on the table
    is what makes that a rule rather than a hope: a second sync of a session
    already described is refused by the database.

    The workout's best efforts are read off the same minutes and written here
    too. Here rather than beside each caller because this is the one place
    minutes reach the database, and two call sites deriving the same numbers is
    two places for them to drift apart.
    """
    if not minutes:
        return 0
    db.add_all(
        [
            models.WorkoutSample(
                workout_id=workout_id,
                minute=row.minute,
                distance_mi=row.distance_mi,
                hr_min=row.hr_min,
                hr_avg=row.hr_avg,
                hr_max=row.hr_max,
                steps=row.steps,
                active_kcal=row.active_kcal,
            )
            for row in minutes
        ]
    )
    db.flush()
    bests.store(db, workout_id, [(row.minute, row.distance_mi) for row in minutes])
    return len(minutes)


def record(db: Session, workout: models.Workout, entry) -> int:
    """Everything a newly imported workout's entry said beyond its own numbers.

    The summaries go onto the workout row and the minutes into their own table.
    Returns how many minutes were written, for the sync's own log.

    Never raises. Everything is caught, including the write, because this runs
    inside the sync loop and the detail is not worth losing a workout over. The
    savepoint means a refused row rolls back the minutes alone, and the four
    summary columns are set before it: they are read off the entry rather than
    out of the database, so they cannot be what the write objected to.
    """
    try:
        details = parse(entry)
        workout.elevation_gain_ft = details.elevation_gain_ft
        workout.max_hr = details.max_hr
        workout.temperature_f = details.temperature_f
        workout.humidity_pct = details.humidity_pct
        if not details.minutes:
            return 0
        with db.begin_nested():
            return store(db, workout.id, details.minutes)
    except Exception:
        log.warning("Could not read the detail on workout %s", workout.id, exc_info=True)
        return 0
