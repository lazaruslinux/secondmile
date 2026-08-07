"""The badges: the achievements catalogue, the race badges, and their awarding.

Two kinds of thing live here. Achievements are aggregate-based and awarded once
ever: the evaluator is stateless, so it is idempotent, safe on every sweep, and
self-healing for history that predates a release, and an achievement is never
revoked. Race badges are the opposite: one run earns one, and running the same
distance next month earns another. Both are data-driven, and the ids are the
stable part because they appear in the database and in the badge slots.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.activity import converted_miles, week_start
from app.security import now_utc

# The kinds the frontend groups by. One today: the collection achievements went
# when the cards did, and the plot has not grown any of its own yet.
KINDS = ("week-distance",)


@dataclass(frozen=True)
class Achievement:
    id: str
    kind: str
    name: str
    detail: str
    # Miles for the counted kinds; an activity name for the rest.
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


CATALOG: tuple[Achievement, ...] = (
    _week(10),
    _week(15),
    _week(25),
    _week(40),
)

BY_ID: dict[str, Achievement] = {row.id: row for row in CATALOG}


def best_week_mi(db: Session, user_id: int) -> float:
    """The most converted Miles this account has ever covered inside one week.

    The best week ever rather than the current one: a weekly badge stays
    happened, and a quiet fortnight does not take it back.
    """
    rows = db.execute(
        select(models.Workout.activity, models.Workout.start_ts, models.Workout.distance_mi)
        .where(models.Workout.user_id == user_id)
    ).all()
    weeks: dict[dt.date, float] = {}
    for activity, start_ts, distance_mi in rows:
        monday = week_start(start_ts)
        weeks[monday] = weeks.get(monday, 0.0) + converted_miles(activity, distance_mi)
    return max(weeks.values(), default=0.0)


def _state(db: Session, user_id: int) -> dict[str, tuple[bool, bool]]:
    """(earned, gilded) for every achievement in the catalogue."""
    reached = best_week_mi(db, user_id)
    out: dict[str, tuple[bool, bool]] = {}
    for row in CATALOG:
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
    and an unearned one says what it would take."""
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


# --------------------------------------------------------------------------
# Badges
#
# Repeatable, unlike the achievements above: one workout earns one, and doing
# it again next month earns another. The race family is the only one today.
# Adding a family is catalogue rows and one awarding rule appended to
# _WORKOUT_RULES; it is never a second table or a second pipeline.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Badge:
    id: str
    # Which family the badge belongs to, which is how the profile groups them
    # and how a rule finds its own rows.
    family: str
    name: str
    # Raw miles in a single workout, not converted Miles: a 5K is a distance on
    # the ground, and no conversion rate has any business changing what it is.
    distance_mi: float


# Ascending, which is what makes "the highest one this run qualifies for" a
# single pass. Every threshold sits a hair under the metric truth on purpose,
# because a GPS trace of a measured 5K rarely reads 3.107.
RACE_BADGES: tuple[Badge, ...] = (
    Badge("race_5k", "race", "5K", 3.1),
    Badge("race_10k", "race", "10K", 6.2),
    Badge("race_half", "race", "Half Marathon", 13.1),
    Badge("race_marathon", "race", "Marathon", 26.2),
    Badge("race_ultra", "race", "Ultra", 31.1),
)

# Every family, in the order they are shown. One entry today.
BADGES: tuple[Badge, ...] = RACE_BADGES

BADGES_BY_ID: dict[str, Badge] = {row.id: row for row in BADGES}


def _race_badge_for(workout: models.Workout) -> Badge | None:
    """The race badge one workout earns, or None.

    Running only this round, and the highest one only: a marathon is a
    marathon, not also a 5K and a 10K and a half. A workout the pace flag has
    already called impossible earns nothing at all, because a distance nobody
    covered is not a distance worth a badge.
    """
    if workout.activity != "run":
        return None
    if (workout.flags or {}).get("impossible_pace"):
        return None
    best = None
    for badge in RACE_BADGES:
        # Tolerance: distances are floats, and exactly-the-threshold must pass.
        if workout.distance_mi + 1e-9 >= badge.distance_mi:
            best = badge
    return best


# One rule per family, each returning at most one badge for a workout.
_WORKOUT_RULES = (_race_badge_for,)


def badge_for_workout(workout: models.Workout) -> Badge | None:
    """The badge a workout earns, or None.

    One badge per workout, because badge_earns holds one row per workout. That
    is deliberate while every family is earned in a single session: it is what
    makes a replay idempotent without a second key. The first family that has
    to share a workout with another relaxes the constraint in its own
    migration, and this returns a list on the same day.
    """
    for rule in _WORKOUT_RULES:
        badge = rule(workout)
        if badge is not None:
            return badge
    return None


def award_badge(db: Session, user_id: int, workout: models.Workout) -> Badge | None:
    """Record the badge a freshly credited workout earned, if it earned one.

    earned_at is the workout's start time rather than the clock, so a rebuild
    from the same history writes the same row. The unique workout id is what
    makes a replay idempotent even when the marker table has been lost.
    """
    badge = badge_for_workout(workout)
    if badge is None:
        return None
    try:
        with db.begin_nested():
            db.add(
                models.BadgeEarn(
                    user_id=user_id,
                    badge_id=badge.id,
                    workout_id=workout.id,
                    earned_at=workout.start_ts,
                )
            )
            db.flush()
    except IntegrityError:
        return None
    return badge


def clear_badges(db: Session, user_id: int) -> None:
    """Throw away one account's badges, for the rebuild to earn them again."""
    db.execute(delete(models.BadgeEarn).where(models.BadgeEarn.user_id == user_id))


def badge_summary(db: Session, user_id: int, family: str) -> list[dict]:
    """One family's badges with how many times this account has earned each.

    Every badge in the family, zeroes included: the strip on the profile shows
    what is still to come as much as what has been done, the same way the
    achievements catalogue does.
    """
    rows = {
        badge_id: (count, first, last)
        for badge_id, count, first, last in db.execute(
            select(
                models.BadgeEarn.badge_id,
                func.count(),
                func.min(models.BadgeEarn.earned_at),
                func.max(models.BadgeEarn.earned_at),
            )
            .where(models.BadgeEarn.user_id == user_id)
            .group_by(models.BadgeEarn.badge_id)
        ).all()
    }
    out = []
    for badge in BADGES:
        if badge.family != family:
            continue
        count, first, last = rows.get(badge.id, (0, None, None))
        out.append(
            {
                "id": badge.id,
                "name": badge.name,
                "distance_mi": badge.distance_mi,
                "count": int(count),
                "first_earned_at": first.isoformat() if first is not None else None,
                "last_earned_at": last.isoformat() if last is not None else None,
            }
        )
    return out


def earned_badge_ids(db: Session, user_id: int) -> set[str]:
    """The badges this account has earned at least once, any family."""
    return set(
        db.execute(
            select(models.BadgeEarn.badge_id)
            .where(models.BadgeEarn.user_id == user_id)
            .distinct()
        ).scalars()
    )
