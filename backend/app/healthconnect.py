"""A Health Connect export, in the shape the rest of the sync already reads.

Android has no Health Auto Export. What it has is a bridge app that reads Health
Connect and posts a flat envelope of arrays to a webhook: sessions in one list,
heart rate in another, calories and steps and distance in three more. That is a
different description of the same morning, so rather than teach every reader
downstream a second dialect, one is turned into the other here and app.activity
goes on being the only thing that knows what a workout is.

Two things the translation has to do that a field rename would not. The arrays
are independent of the sessions, so each session's detail is the slice of each
array that falls inside its own window. And the arrays arrive at whatever
resolution the phone felt like, while app.samples keeps one row per minute and
takes the first reading it sees for each, so readings are folded into minutes
here instead: summed for distance, steps and energy, and kept as a real low,
mean and high for heart rate. Handing over the raw stream would quietly throw
away every reading after the first in each minute.

No GPS. Health Connect has an exercise route API and the bridge does not export
it, so an Android workout arrives without one and gets no map. Everything else
it earns is the same as any other workout: the two-lane law never learns which
phone a mile came from.
"""

import datetime as dt
from bisect import bisect_left, bisect_right

from app import activity
from app.config import MAX_INGEST_METRIC_POINTS, MAX_INGEST_WORKOUTS

# The session list, and every array this reads beside it. Anything else the
# bridge is configured to send (sleep, weight, blood glucose) is left where it
# is: this app stores four activities and a pedometer.
SESSIONS = "exercise"
_ARRAYS = (SESSIONS, "heart_rate", "active_calories", "steps", "distance")

# Health Connect spells an indoor session in the exercise type rather than in a
# name, so the word app.activity matches on is put there for it. Read as
# fragments for the same reason the name keywords are: the enum has more
# spellings than anyone has written down.
_INDOOR = ("treadmill", "stationary", "elliptical", "indoor")


def looks_like(payload) -> bool:
    """Whether this export is a Health Connect one rather than an Apple one.

    Asked as "the readers we already have cannot see anything in it, and it
    carries an array we recognise", which is the one test that cannot mistake
    an Apple export for this: a payload app.activity can already read is never
    translated, whatever else it happens to carry.
    """
    if not isinstance(payload, dict):
        return False
    if activity.workout_entries(payload) is not None:
        return False
    if activity.metric_entries(payload) is not None:
        return False
    return any(isinstance(payload.get(key), list) for key in _ARRAYS)


def _objects(payload: dict, key: str) -> list[dict]:
    """One array's entries, without whatever else got into the list."""
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _moment(item: dict) -> dt.datetime | None:
    """When a record says it happened.

    Interval records name a start and an instant record names a time, and both
    are read through app.activity's own parser so an offset written the way
    only one exporter writes it is understood in one place.
    """
    raw = item.get("start_time")
    if raw is None:
        raw = item.get("time")
    if raw is None:
        raw = item.get("date")
    return activity.parse_start(raw)


def _in_time_order(items: list[dict]) -> tuple[list[dt.datetime], list[dict]]:
    """The records that name a moment, in order, and their moments beside them.

    Sorted once for the whole export rather than scanned once per session: a
    long backfill is thousands of sessions against tens of thousands of
    readings, and the windows below are found by bisecting this instead.
    """
    dated = []
    for item in items:
        when = _moment(item)
        if when is not None:
            dated.append((when, item))
    dated.sort(key=lambda pair: pair[0])
    return [when for when, _ in dated], [item for _, item in dated]


def _window(
    moments: list[dt.datetime], items: list[dict], start: dt.datetime, end: dt.datetime
) -> list[dict]:
    """The records falling inside one session, ends included."""
    if not moments:
        return []
    return items[bisect_left(moments, start) : bisect_right(moments, end)]


def _number(value) -> float | None:
    """A plain number out of a record, or None. Never a bool, never non-finite."""
    return activity.quantity(value)


def _name(raw) -> str:
    """The exercise type, written the way app.activity reads a workout name.

    Underscores become spaces so the keyword table sees whole words, and an
    indoor type is said to be indoor in the one word is_indoor looks for. The
    result is only ever read back as an activity and an indoor flag, so a type
    the enum grows tomorrow still arrives as something rather than nothing.
    """
    text = str(raw or "").replace("_", " ").strip()
    if not text:
        return ""
    lowered = text.lower()
    readable = text.title()
    return f"Indoor {readable}" if any(word in lowered for word in _INDOOR) else readable


def _minute_of(when: dt.datetime, first: dt.datetime) -> int:
    return int((when - first).total_seconds() // 60)


def _folded(records: list[dict], read, combine: str) -> list[dict]:
    """One reading per minute, out of however many the phone sent for it.

    app.samples keeps one row per minute and takes the first reading it finds
    for each, so summing here is what keeps a phone that reports every fifteen
    seconds from having three quarters of its session dropped. Heart rate is
    not a total, so it comes back as the real low, mean and high of the minute
    instead.
    """
    if not records:
        return []
    first = _moment(records[0])
    if first is None:
        return []
    buckets: dict[int, list[float]] = {}
    for item in records:
        when = _moment(item)
        value = read(item)
        if when is None or value is None:
            continue
        buckets.setdefault(_minute_of(when, first), []).append(value)

    folded = []
    for minute in sorted(buckets):
        values = buckets[minute]
        stamp = (first + dt.timedelta(minutes=minute)).isoformat()
        if combine == "sum":
            folded.append({"date": stamp, "qty": sum(values)})
        else:
            folded.append(
                {
                    "date": stamp,
                    "min": min(values),
                    "avg": sum(values) / len(values),
                    "max": max(values),
                }
            )
    return folded


def _session(
    entry: dict,
    hr: tuple[list[dt.datetime], list[dict]],
    energy: tuple[list[dt.datetime], list[dict]],
    steps: tuple[list[dt.datetime], list[dict]],
    distance: tuple[list[dt.datetime], list[dict]],
) -> dict:
    """One exercise session as a workout entry, detail and all.

    An entry whose start or end cannot be read is handed over with its name and
    whatever it did say, so app.activity refuses it by its own rules and names
    the reason in the ingest log. Deciding here which entries are worth passing
    on would put a second, quieter set of refusal rules in the codebase.
    """
    workout: dict = {"name": _name(entry.get("type"))}
    start = _moment(entry)
    end = activity.parse_start(entry.get("end_time"))
    if start is None or end is None or end < start:
        workout["start"] = entry.get("start_time")
        return workout

    seconds = _number(entry.get("duration_seconds"))
    workout["start"] = start.isoformat()
    workout["duration"] = seconds if seconds is not None else (end - start).total_seconds()

    meters = _number(entry.get("distance_meters"))
    if meters is not None:
        workout["distance"] = {"qty": meters, "units": "m"}

    beats = [
        value
        for value in (_number(item.get("bpm")) for item in _window(*hr, start, end))
        if value is not None
    ]
    if beats:
        # Both readings the detail wants: quantity() takes the average off this
        # object for the workout row, and app.samples takes the high off it for
        # the summary the details screen prints.
        workout["heartRate"] = {
            "min": min(beats),
            "avg": sum(beats) / len(beats),
            "max": max(beats),
        }

    burned = _window(*energy, start, end)
    calories = [value for value in (_number(item.get("calories")) for item in burned) if value]
    if calories:
        # The session's own total, which is the number manna is drawn from. The
        # bridge sends active calories, so this is the active line already.
        #
        # Two sessions that overlap, which is what two fitness apps both watching
        # one walk look like, would each claim the whole overlap's calories. Left
        # as it is: sessions describing the same moments with the same start and
        # length are already one workout by the time this matters, the earning
        # lane reads each session's own distance rather than this pool, and manna
        # is the giving lane, which by law reaches nothing that is earned.
        workout["activeEnergyBurned"] = {"qty": sum(calories), "units": "kcal"}
        workout["activeEnergy"] = [
            {**point, "units": "kcal"}
            for point in _folded(burned, lambda item: _number(item.get("calories")), "sum")
        ]

    heart_minutes = _folded(_window(*hr, start, end), lambda item: _number(item.get("bpm")), "avg")
    if heart_minutes:
        workout["heartRateData"] = heart_minutes

    step_minutes = _folded(
        _window(*steps, start, end), lambda item: _number(item.get("count")), "sum"
    )
    if step_minutes:
        workout["stepCount"] = step_minutes

    covered = _folded(
        _window(*distance, start, end), lambda item: _number(item.get("meters")), "sum"
    )
    if covered:
        workout["walkingAndRunningDistance"] = [{**point, "units": "m"} for point in covered]

    return workout


def _wheeled_and_swum(sessions: list[dict]) -> list[tuple[dt.datetime, dt.datetime]]:
    """When this export's rides and swims happened.

    Health Connect keeps one distance record type for every activity, while the
    day figure this app stores and prints is the walking and running one. A ride
    would otherwise be added to it and read as miles somebody walked, so the
    windows come back here and the readings inside them are left out below.
    """
    windows = []
    for entry in sessions:
        if activity.classify(_name(entry.get("type"))) not in {"cycle", "swim"}:
            continue
        start = _moment(entry)
        end = activity.parse_start(entry.get("end_time"))
        if start is not None and end is not None and end >= start:
            windows.append((start, end))
    return windows


def _day_metric(
    name: str,
    records: list[dict],
    field: str,
    units: str | None,
    skip: list[tuple[dt.datetime, dt.datetime]] | None = None,
) -> dict | None:
    """One of the two pedometer readings this app keeps, as a metrics entry."""
    points = []
    for item in records:
        when = _moment(item)
        value = _number(item.get(field))
        if when is None or value is None or value < 0:
            continue
        if skip and any(start <= when <= end for start, end in skip):
            continue
        points.append({"date": when.isoformat(), "qty": value})
    if not points:
        return None
    entry: dict = {"name": name, "data": points}
    if units is not None:
        entry["units"] = units
    return entry


def translate(payload: dict) -> dict:
    """The export, rewritten as the workouts and metrics app.activity reads.

    Oversized exports are cut to the caps the sync endpoint enforces rather than
    translated whole and rejected afterwards. The endpoint still refuses them:
    the point of the cut is that a payload claiming a million readings costs a
    slice here instead of a million pairings, and it is cut one past each cap so
    what the endpoint counts is still over it.
    """
    sessions = _objects(payload, SESSIONS)[: MAX_INGEST_WORKOUTS + 1]
    heart = _in_time_order(_objects(payload, "heart_rate")[: MAX_INGEST_METRIC_POINTS + 1])
    energy = _in_time_order(_objects(payload, "active_calories")[: MAX_INGEST_METRIC_POINTS + 1])
    steps = _objects(payload, "steps")[: MAX_INGEST_METRIC_POINTS + 1]
    distance = _objects(payload, "distance")[: MAX_INGEST_METRIC_POINTS + 1]
    step_windows = _in_time_order(steps)
    distance_windows = _in_time_order(distance)

    workouts = [
        _session(entry, heart, energy, step_windows, distance_windows) for entry in sessions
    ]

    metrics = [
        entry
        for entry in (
            # The pedometer counts what it counts, on a ride like any other day,
            # so the step reading is taken whole and only the distance is sifted.
            _day_metric("step_count", steps, "count", None),
            _day_metric(
                "walking_running_distance",
                distance,
                "meters",
                "m",
                skip=_wheeled_and_swum(sessions),
            ),
        )
        if entry is not None
    ]

    return {"data": {"workouts": workouts, "metrics": metrics}}
