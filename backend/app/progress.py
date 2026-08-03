"""The pipeline: real workouts become experience, levels, chests, and badges.

Everything is server side and idempotent per workout: every path funnels
through process_user, and a credited workout is never credited again. Every
roll comes from a generator seeded on (user id, workout id), so replays are
deterministic.
"""

import datetime as dt
import math
import random

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import achievements, models, world
from app.activity import converted_miles
from app.config import (
    BORDER_LEVELS,
    CHEST_SPACING_MI,
    LEVEL_STEP_XP,
    SERVER_TZ,
    UNOWNED_CARD_WEIGHT,
    WALK_BONUS_CHEST_CHANCE,
    XP_PER_MILE,
    XP_PER_MINUTE,
)
from app.models import ACTIVITIES
from app.security import now_utc

# Distances are floats; "reached the next chest" means within rounding error.
_EPSILON = 1e-9


# --------------------------------------------------------------------------
# Experience and levels
# --------------------------------------------------------------------------


def workout_xp(activity: str, distance_mi: float, duration_s: int) -> int:
    """What one workout is worth. Distance and time both count; rounded once
    at the end so the stored total is always whole."""
    miles = converted_miles(activity, distance_mi)
    return round(miles * XP_PER_MILE + (duration_s / 60.0) * XP_PER_MINUTE)


def xp_to_reach(level: int) -> int:
    """Total experience needed to stand at `level`. Level n costs
    LEVEL_STEP_XP * n beyond n - 1, so the total is triangular, less the
    level-one step nobody pays."""
    if level <= 1:
        return 0
    return LEVEL_STEP_XP * (level * (level + 1) // 2 - 1)


def level_for_xp(xp: int) -> int:
    """The level a total of experience stands at. Endless by design.

    xp_to_reach is triangular, so this inverts it rather than counting up to it.
    Same answer for every total, in one step instead of one step per level: the
    curve is endless, and a scan over an absurd total would hold a request open
    for as long as the total is large. Integer arithmetic throughout, because a
    square root in floating point lands on the wrong side of an exact boundary.

    level(level + 1) * LEVEL_STEP_XP <= 2 * (xp + LEVEL_STEP_XP) is the same
    condition the loop tested; isqrt solves it for level.
    """
    if xp < LEVEL_STEP_XP * 2:  # the cost of level two, and the whole of level one
        return 1
    room = (2 * xp + 2 * LEVEL_STEP_XP) // LEVEL_STEP_XP
    return (math.isqrt(4 * room + 1) - 1) // 2


def level_bounds(xp: int) -> tuple[int, int, int]:
    """(level, experience into this level, experience this level is worth)."""
    level = level_for_xp(xp)
    floor = xp_to_reach(level)
    ceiling = xp_to_reach(level + 1)
    return level, xp - floor, ceiling - floor


def border_tier(level: int) -> int:
    """Which avatar border a level has earned, from 1 to len(BORDER_LEVELS)."""
    return sum(1 for threshold in BORDER_LEVELS if level >= threshold) or 1


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------


def ensure_progress(db: Session, user_id: int) -> models.UserProgress:
    """The account's progress row, created empty if it has none. Lazy so an
    account that predates the table is never left without one."""
    row = db.get(models.UserProgress, user_id)
    if row is not None:
        return row
    row = models.UserProgress(
        user_id=user_id,
        xp=0,
        level=1,
        chest_progress_mi=0.0,
        next_chest_gap_mi=None,
        last_ack_at=None,
        updated_at=now_utc(),
    )
    db.add(row)
    db.flush()
    return row


def process_user(db: Session, user_id: int) -> models.UserProgress:
    """Credit every workout this account has not been credited for, oldest first."""
    progress = ensure_progress(db, user_id)
    pending = (
        db.execute(
            select(models.Workout)
            .where(
                models.Workout.user_id == user_id,
                models.Workout.id.not_in(select(models.ProcessedWorkout.workout_id)),
            )
            # By id within a timestamp so simultaneous workouts credit in a
            # stable order.
            .order_by(models.Workout.start_ts, models.Workout.id)
        )
        .scalars()
        .all()
    )
    credited = 0
    for workout in pending:
        if not _claim(db, workout.id):
            continue
        _credit(db, progress, workout)
        credited += 1
    if credited:
        progress.updated_at = now_utc()
    # Runs even on a quiet sweep: the evaluator is aggregate-based, so history
    # that predates a release earns its badges on the first read.
    achievements.evaluate(db, user_id)
    db.commit()
    return progress


def _claim(db: Session, workout_id: int) -> bool:
    """Write the processed marker before the work it stands for. The primary
    key decides which of two concurrent requests owns the workout."""
    try:
        with db.begin_nested():
            db.add(models.ProcessedWorkout(workout_id=workout_id))
            db.flush()
    except IntegrityError:
        return False
    return True


def _credit(db: Session, progress: models.UserProgress, workout: models.Workout) -> None:
    rng = random.Random(f"{progress.user_id}:{workout.id}")
    progress.xp += workout_xp(workout.activity, workout.distance_mi, workout.duration_s)
    progress.level = level_for_xp(progress.xp)
    _advance_chests(
        db, progress, rng, converted_miles(workout.activity, workout.distance_mi)
    )

    # Walking's gathering role: per completed walked mile, a bonus chest roll
    # on top of whatever the distance already earned.
    if workout.activity == "walk":
        for _ in range(int(workout.distance_mi)):
            if rng.random() < WALK_BONUS_CHEST_CHANCE:
                _drop_chest(db, progress.user_id, rng)


def _advance_chests(
    db: Session, progress: models.UserProgress, rng: random.Random, miles: float
) -> None:
    """Bank converted Miles toward the next chest and drop what falls out.
    The accumulator carries between workouts, so a short leftover is picked up
    by the next workout rather than lost."""
    remaining = miles
    while True:
        if progress.next_chest_gap_mi is None:
            progress.next_chest_gap_mi = rng.uniform(*CHEST_SPACING_MI)
            progress.chest_progress_mi = 0.0
        room = progress.next_chest_gap_mi - progress.chest_progress_mi
        if remaining < room - _EPSILON:
            progress.chest_progress_mi += remaining
            return
        remaining -= room
        progress.next_chest_gap_mi = None
        progress.chest_progress_mi = 0.0
        _drop_chest(db, progress.user_id, rng)


def choose_set(rng: random.Random) -> world.CardSet:
    """Pick which set a chest draws from, by the catalogue's own weights.
    Per chest, not per activity: scarce sets are scarce for everybody."""
    sets = tuple(world.CARD_SETS.values())
    return rng.choices(sets, weights=[row.weight for row in sets], k=1)[0]


def choose_card(
    cards: tuple[world.Card, ...], owned: set[str], rng: random.Random
) -> world.Card:
    """Pick one card, leaning toward unowned plates. A lean, not a rule:
    duplicates stay possible, and duplicates are what gifting is built on."""
    weights = [1.0 if card.id in owned else UNOWNED_CARD_WEIGHT for card in cards]
    return rng.choices(cards, weights=weights, k=1)[0]


def _drop_chest(db: Session, user_id: int, rng: random.Random) -> models.Chest:
    """Drop one chest carrying one card. The card is chosen at drop time, not
    open time: opening is a reveal, never a roll, because outcomes must not
    depend on when the player opens the app."""
    owned = set(
        db.execute(
            select(models.UserCard.card_id).where(models.UserCard.user_id == user_id)
        ).scalars()
    )
    card_set = choose_set(rng)
    card = choose_card(world.CARDS_BY_SET[card_set.id], owned, rng)
    chest = models.Chest(
        user_id=user_id, card_id=card.id, dropped_at=now_utc(), opened_at=None
    )
    db.add(chest)
    db.flush()
    return chest


def recompute(db: Session, user_id: int) -> models.UserProgress:
    """Throw away one account's derived progress and rebuild it from the
    workouts. Workouts are never touched. Earned achievements stay: they are
    never revoked, and the evaluator re-awards on top of them, so a badge
    keeps the day it was first earned."""
    for table in (models.Chest, models.UserCard):
        db.execute(delete(table).where(table.user_id == user_id))
    # processed_workouts is keyed by workout; the workout is what has an owner.
    db.execute(
        delete(models.ProcessedWorkout).where(
            models.ProcessedWorkout.workout_id.in_(
                select(models.Workout.id).where(models.Workout.user_id == user_id)
            )
        )
    )
    row = db.get(models.UserProgress, user_id)
    if row is not None:
        row.xp = 0
        row.level = 1
        row.chest_progress_mi = 0.0
        row.next_chest_gap_mi = None
    db.commit()
    return process_user(db, user_id)


# --------------------------------------------------------------------------
# Reading the state back
# --------------------------------------------------------------------------


def _totals(
    db: Session, user_id: int, since: dt.datetime | None = None
) -> dict[str, dict]:
    """Per-activity distance, energy, and count, in the Almanac's shape:
    absent activities are missing keys, same as the weekly endpoint."""
    stmt = select(
        models.Workout.activity,
        func.coalesce(func.sum(models.Workout.distance_mi), 0.0),
        func.coalesce(func.sum(models.Workout.active_kcal), 0.0),
        func.count(),
    ).where(models.Workout.user_id == user_id)
    if since is not None:
        stmt = stmt.where(models.Workout.start_ts >= since)
    rows = db.execute(stmt.group_by(models.Workout.activity)).all()
    found = {row[0]: row for row in rows}
    return {
        name: {
            "distance_mi": round(float(found[name][1]), 2),
            "converted_mi": round(converted_miles(name, float(found[name][1])), 2),
            "active_kcal": round(float(found[name][2]), 1),
            "workouts": int(found[name][3]),
        }
        for name in ACTIVITIES
        if name in found
    }


def lifetime_totals(db: Session, user_id: int) -> dict[str, dict]:
    return _totals(db, user_id)


def week_totals(db: Session, user_id: int, week_start_date: dt.date) -> dict[str, dict]:
    """Totals since the given Monday, server timezone: the same Monday the
    Almanac uses, so the two screens can never disagree."""
    cutoff = dt.datetime.combine(week_start_date, dt.time.min, tzinfo=SERVER_TZ)
    return _totals(db, user_id, since=cutoff)


def owned_card_count(db: Session, user_id: int) -> int:
    """Distinct plates in the album, counted against the catalogue."""
    return achievements.card_counts(db, user_id)[0]
