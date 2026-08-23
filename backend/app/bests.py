"""The fastest stretch of each race distance a workout holds.

A best effort is Strava's reading of a personal record and this app's too: not
what a session averaged, but the quickest the ground under it was ever covered.
You may set a 5K best in the middle of a ten mile run.

It is read out of the per-minute rows, and it is written down once, when those
rows are. The alternative is what this module replaced: every open of the
insights band read every sample row a history held and recomputed every best
from scratch, which at ten years of running is 120,000 rows and six thousand
computations for an answer that had not changed since the workout was imported.

What is stored is only ever the measured answer. A workout whose per-minute
rows do not reach a tier's distance stores nothing for it, and the reader falls
back to projecting the session's own average pace over that distance, exactly
as it did before. Absence therefore means "the samples could not answer", which
is the same question the reader used to ask the samples directly.

One consequence worth having: a workout keeps its measured bests after its
per-minute rows are pruned. The answer was true when it was computed, and the
history it belongs to should not quietly get slower because a payload aged out.
"""

import bisect

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import models
from app.config import PR_TIERS


def track(minutes: list[tuple[int, float | None]]) -> tuple[list[float], list[float]]:
    """One workout's per-minute distances as a line of time against ground covered.

    Answers two lists of the same length: the minute each turn of the line falls
    on, and the miles covered by then. Between two of them the pace is steady,
    which is the only reading a per-minute array supports and is what lets a
    stretch end part way through a minute.

    A minute the export said nothing about covers no ground and still takes its
    minute, and so does a minute missing from the table altogether: a session
    took the time it took whether the phone was recording or not.
    """
    times: list[float] = []
    covered: list[float] = []
    so_far = 0.0
    end: int | None = None
    for minute, distance in minutes:
        if end is None or minute > end:
            # The first turn, or the one that opens a gap. Either way the line
            # starts again here at whatever has been covered so far.
            times.append(float(minute))
            covered.append(so_far)
        so_far += distance or 0.0
        times.append(float(minute + 1))
        covered.append(so_far)
        end = minute + 1
    return times, covered


def best_effort(times: list[float], covered: list[float], distance_mi: float) -> float | None:
    """The shortest time this line covers a distance in, in seconds.

    None where it never covers it at all, which is a workout whose export
    carried only part of the session: the answer then belongs to the caller's
    fallback rather than to a stretch of ground the phone never described.

    Both passes together are the whole of the problem. Pace is steady inside a
    minute, so a stretch that could be shortened by sliding it is shortened
    until one of its ends lands on a minute boundary: every fastest stretch
    therefore starts on one or finishes on one, and the two passes try each.
    """
    if len(covered) < 2 or covered[-1] - covered[0] < distance_mi:
        return None
    best: float | None = None

    # Starting on a boundary: the moment the distance is reached, which is
    # inside the minute that reaches it.
    for index, start_at in enumerate(covered):
        stop = bisect.bisect_left(covered, start_at + distance_mi)
        if stop >= len(covered):
            # Nothing this far along covers it either, the line being ordered.
            break
        # The turn before it is short of the target, or bisect would have
        # stopped there, so the minute between them covers ground to divide.
        part = (start_at + distance_mi - covered[stop - 1]) / (covered[stop] - covered[stop - 1])
        finish = times[stop - 1] + part * (times[stop] - times[stop - 1])
        seconds = (finish - times[index]) * 60.0
        if best is None or seconds < best:
            best = seconds

    # Finishing on a boundary: the moment the stretch would have had to start.
    for index, stop_at in enumerate(covered):
        target = stop_at - distance_mi
        if target < covered[0]:
            continue
        start = bisect.bisect_right(covered, target) - 1
        span = covered[start + 1] - covered[start] if start + 1 < len(covered) else 0.0
        part = (target - covered[start]) / span if span > 0 else 0.0
        began = times[start] + part * (times[start + 1] - times[start]) if span > 0 else times[start]
        seconds = (times[index] - began) * 60.0
        if best is None or seconds < best:
            best = seconds

    return best


def measure(minutes: list[tuple[int, float | None]]) -> dict[str, float]:
    """Every tier this workout's own minutes can answer for, and its time for it.

    A tier the minutes do not reach is left out rather than given a number, so
    what comes back is exactly the set the reader may take as measured.
    """
    line = track(minutes)
    found: dict[str, float] = {}
    for name, floor in PR_TIERS:
        seconds = best_effort(*line, floor)
        if seconds is not None:
            found[name] = seconds
    return found


def store(db: Session, workout_id: int, minutes: list[tuple[int, float | None]]) -> int:
    """Write down what this workout's minutes say its bests are. Returns how many.

    Whatever was there before is cleared first, so a workout whose minutes were
    filled in later by a backfill ends up saying what its minutes now say rather
    than keeping a thinner answer from a thinner export.
    """
    db.execute(
        delete(models.WorkoutBestEffort).where(
            models.WorkoutBestEffort.workout_id == workout_id
        )
    )
    found = measure(minutes)
    db.add_all(
        [
            models.WorkoutBestEffort(workout_id=workout_id, tier=tier, seconds=seconds)
            for tier, seconds in found.items()
        ]
    )
    db.flush()
    return len(found)


def for_user(db: Session, user_id: int) -> dict[tuple[int, str], float]:
    """Every best this account has stored, keyed by the workout and the tier.

    Joined rather than asked for by a list of ids, for the reason the per-minute
    query it replaced was: a long history is more ids than a statement should
    carry. Deleted workouts are left out, so a session somebody took back cannot
    hold a record.
    """
    return {
        (workout_id, tier): seconds
        for workout_id, tier, seconds in db.execute(
            select(
                models.WorkoutBestEffort.workout_id,
                models.WorkoutBestEffort.tier,
                models.WorkoutBestEffort.seconds,
            )
            .join(models.Workout, models.Workout.id == models.WorkoutBestEffort.workout_id)
            .where(
                models.Workout.user_id == user_id,
                models.Workout.deleted_at.is_(None),
            )
        )
    }
