"""The achievements catalogue and the evaluator that awards it.

Data-driven: a new achievement is a row in CATALOG and nothing else. Ids are
the stable part; they appear in user_achievements and badge slots. The
evaluator is stateless and aggregate-based, so it is idempotent, safe on every
sweep, and self-healing for history that predates a release. Achievements are
never revoked.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, world
from app.activity import converted_miles, week_start
from app.models import ACTIVITIES
from app.security import now_utc

# The five kinds; the frontend groups by these and each has a fallback badge.
KINDS = (
    "duration-single",
    "week-distance",
    "lifetime-distance",
    "firsts",
    "collection",
)


@dataclass(frozen=True)
class Achievement:
    id: str
    kind: str
    name: str
    detail: str
    # Minutes, Miles, or cards for the counted kinds; an activity name or a
    # card set id for the rest.
    target: float | str
    # The Second Mile rule: reaching this inside the same window gilds the
    # badge in place. Only the weekly kind has one; a lifetime total has no
    # window to double inside.
    gilded_target: float | None = None


def _week(threshold: int) -> Achievement:
    return Achievement(
        id=f"week_{threshold}",
        kind="week-distance",
        name=f"{threshold} Mile Week",
        detail=(
            f"{threshold} Miles inside one week. "
            f"Gilded by going the second mile: {threshold * 2} in the same week."
        ),
        target=float(threshold),
        gilded_target=float(threshold * 2),
    )


_ACTIVITY_NAMES = {"walk": "Walk", "run": "Run", "cycle": "Ride", "swim": "Swim"}


CATALOG: tuple[Achievement, ...] = (
    # The first rung is deliberately low: starting counts.
    Achievement(
        "duration_15", "duration-single", "Quarter Hour",
        "A single workout of fifteen minutes or more.", 15.0,
    ),
    Achievement(
        "duration_30", "duration-single", "Half Hour",
        "A single workout of thirty minutes or more.", 30.0,
    ),
    Achievement(
        "duration_60", "duration-single", "The Full Hour",
        "A single workout of an hour or more.", 60.0,
    ),
    Achievement(
        "duration_90", "duration-single", "Ninety Minutes",
        "A single workout of ninety minutes or more.", 90.0,
    ),
    _week(10),
    _week(15),
    _week(25),
    _week(40),
    Achievement(
        "lifetime_50", "lifetime-distance", "Fifty Miles",
        "Fifty Miles covered, across every activity.", 50.0,
    ),
    Achievement(
        "lifetime_100", "lifetime-distance", "One Hundred Miles",
        "One hundred Miles covered, across every activity.", 100.0,
    ),
    Achievement(
        "lifetime_250", "lifetime-distance", "Two Hundred and Fifty Miles",
        "Two hundred and fifty Miles covered, across every activity.", 250.0,
    ),
    Achievement(
        "lifetime_500", "lifetime-distance", "Five Hundred Miles",
        "Five hundred Miles covered, across every activity.", 500.0,
    ),
    *(
        Achievement(
            f"first_{name}",
            "firsts",
            f"First {_ACTIVITY_NAMES[name]}",
            f"Your first {name} recorded here.",
            name,
        )
        for name in ACTIVITIES
    ),
    Achievement(
        "collection_first_card", "collection", "First Plate",
        "The first card in your guide.", 1.0,
    ),
    *(
        Achievement(
            f"collection_set_{card_set.id}",
            "collection",
            f"{card_set.name} Complete",
            f"Every plate in {card_set.name}.",
            card_set.id,
        )
        for card_set in world.CARD_SETS.values()
    ),
    Achievement(
        "collection_complete", "collection", "The Whole Guide",
        "Every plate in every set.", float(len(world.CARDS)),
    ),
)

BY_ID: dict[str, Achievement] = {row.id: row for row in CATALOG}


@dataclass
class _Totals:
    """Everything the catalogue is measured against, read in one pass."""

    longest_minutes: float = 0.0
    best_week_mi: float = 0.0
    lifetime_mi: float = 0.0
    activities: frozenset[str] = frozenset()


def _totals(db: Session, user_id: int) -> _Totals:
    rows = db.execute(
        select(
            models.Workout.activity,
            models.Workout.start_ts,
            models.Workout.duration_s,
            models.Workout.distance_mi,
        ).where(models.Workout.user_id == user_id)
    ).all()
    if not rows:
        return _Totals()

    weeks: dict[dt.date, float] = {}
    lifetime = 0.0
    longest = 0.0
    seen: set[str] = set()
    for activity, start_ts, duration_s, distance_mi in rows:
        miles = converted_miles(activity, distance_mi)
        lifetime += miles
        longest = max(longest, duration_s / 60.0)
        seen.add(activity)
        monday = week_start(start_ts)
        weeks[monday] = weeks.get(monday, 0.0) + miles
    return _Totals(
        longest_minutes=longest,
        # Best week ever, not the current one: a weekly badge stays happened.
        best_week_mi=max(weeks.values()),
        lifetime_mi=lifetime,
        activities=frozenset(seen),
    )


def card_counts(db: Session, user_id: int) -> tuple[int, dict[str, int]]:
    """(plates owned, plates owned per set), counted against the catalogue so
    a plate from a retired set can never inflate the total. Shared by the
    profile total and the collection badges so they cannot disagree."""
    owned = set(
        db.execute(
            select(models.UserCard.card_id).where(models.UserCard.user_id == user_id)
        ).scalars()
    )
    per_set = {
        set_id: sum(1 for card in cards if card.id in owned)
        for set_id, cards in world.CARDS_BY_SET.items()
    }
    return sum(per_set.values()), per_set


def _state(db: Session, user_id: int) -> dict[str, tuple[bool, bool]]:
    """(earned, gilded) for every achievement in the catalogue."""
    totals = _totals(db, user_id)
    owned_cards, per_set = card_counts(db, user_id)
    out: dict[str, tuple[bool, bool]] = {}
    for row in CATALOG:
        if row.kind == "duration-single":
            reached = totals.longest_minutes
        elif row.kind == "week-distance":
            reached = totals.best_week_mi
        elif row.kind == "lifetime-distance":
            reached = totals.lifetime_mi
        elif row.kind == "firsts":
            out[row.id] = (row.target in totals.activities, False)
            continue
        elif row.id == "collection_first_card":
            reached = float(owned_cards)
        elif row.id == "collection_complete":
            reached = float(owned_cards)
        else:
            set_id = str(row.target)
            out[row.id] = (per_set[set_id] == len(world.CARDS_BY_SET[set_id]), False)
            continue
        target = float(row.target)
        # Tolerance: Miles are summed floats; exactly-the-target must pass.
        earned = reached + 1e-9 >= target
        gilded = (
            row.gilded_target is not None and reached + 1e-9 >= row.gilded_target
        )
        out[row.id] = (earned, gilded)
    return out


def evaluate(db: Session, user_id: int) -> int:
    """Award everything earned and not yet given. Returns rows written.
    Flushes but never commits: the caller owns the transaction."""
    held = {
        row.achievement_id: row
        for row in db.execute(
            select(models.UserAchievement).where(models.UserAchievement.user_id == user_id)
        ).scalars()
    }
    now = now_utc()
    changed = 0
    for achievement_id, (earned, gilded) in _state(db, user_id).items():
        row = held.get(achievement_id)
        if row is None:
            if not earned:
                continue
            db.add(
                models.UserAchievement(
                    user_id=user_id,
                    achievement_id=achievement_id,
                    earned_at=now,
                    gilded=gilded,
                )
            )
            changed += 1
        elif gilded and not row.gilded:
            # Gilds in place; earned_at stays the day it was first earned.
            row.gilded = True
            changed += 1
    if changed:
        db.flush()
    return changed


def earned_count(db: Session, user_id: int) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(models.UserAchievement)
            .where(models.UserAchievement.user_id == user_id)
        ).scalar_one()
    )


def serialize(achievement: Achievement, row: models.UserAchievement | None) -> dict:
    """One catalogue entry with what this account has done about it. The whole
    catalogue is visible, unearned rows included: achievements are targets,
    the opposite of how the album hides an unfound plate."""
    return {
        "id": achievement.id,
        "kind": achievement.kind,
        "name": achievement.name,
        "detail": achievement.detail,
        "gildable": achievement.gilded_target is not None,
        "earned": row is not None,
        "gilded": bool(row is not None and row.gilded),
        "earned_at": row.earned_at.isoformat() if row is not None else None,
    }
