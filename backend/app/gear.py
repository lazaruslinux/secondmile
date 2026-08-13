"""Gear: the shoes a walk or a run was done in, and the miles on them.

Pure utility. Nothing here earns anything and nothing in the game reads it: no
experience, no chest, no medal, no growth, no renown, no manna and no fruit
moves because a workout is wearing shoes. The one number gear owns is a sum of
distances, and it is computed on every read rather than stored, so a deleted
workout takes its miles off the pair and a restored one brings them back with
no rebuild hook anywhere.

Raw miles, never converted Miles: this is wear on a shoe rather than a score.
Steps are not in it either, for the same reason they are in no other total.
"""

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models

# What may wear shoes. A ride and a swim never take a pair, and steps are not an
# activity at all.
GEAR_ACTIVITIES = ("walk", "run")

# Only shoes exist today; models.Gear.kind says why the column is there.
SHOES = "shoes"

STYLES = ("mens", "womens")

# What a pair is stamped on automatically. The last two are the activity names
# themselves, which is what lets `takes` compare one against the other.
APPLIES = ("both", "run", "walk")
DEFAULT_APPLIES = "both"

# US sizes in half steps, and the widths sold against each style. The default
# width is the standard one, because almost nobody knows their width and a form
# that insists on one asks a question most people cannot answer.
_SIZE_RANGE = {"mens": (6.0, 16.0), "womens": (4.0, 14.0)}
WIDTHS = {"mens": ("B", "D", "2E", "4E"), "womens": ("2A", "B", "D", "2E")}
DEFAULT_WIDTH = {"mens": "D", "womens": "B"}

MAX_BRAND = 60
MAX_MODEL = 80
MAX_NICKNAME = 60
# Past any real shoe and any real plan for one, which is all a ceiling is for
# here: the column is a float and nothing downstream reads these numbers.
MAX_MILES = 100000.0


def sizes(style: str) -> tuple[float, ...]:
    """Every size this style is offered in, smallest first."""
    low, high = _SIZE_RANGE[style]
    return tuple(low + step * 0.5 for step in range(int((high - low) * 2) + 1))


def is_size(style: str, size: float) -> bool:
    """Whether a size is one of the half steps this style offers.

    Compared against the list rather than by arithmetic, because the list is
    what the picker on the client draws: a size the form cannot offer is not one
    the server should store.
    """
    return style in STYLES and any(abs(size - offered) < 1e-9 for offered in sizes(style))


def is_width(style: str, width: str) -> bool:
    return style in STYLES and width in WIDTHS[style]


def display_name(row: models.Gear) -> str:
    """What a pair is called: its nickname, or its brand and model."""
    nickname = (row.nickname or "").strip()
    return nickname or f"{row.brand} {row.model}".strip()


def owned(db: Session, user_id: int) -> list[models.Gear]:
    """One account's gear, oldest first. Retired pairs are in it: they still
    carry their miles and still show on the workouts they are on."""
    return list(
        db.execute(
            select(models.Gear)
            .where(models.Gear.user_id == user_id)
            .order_by(models.Gear.id)
        ).scalars()
    )


def mileage(db: Session, rows: Sequence[models.Gear]) -> dict[int, float]:
    """Miles on each of these pairs, keyed by gear id. One query for the list.

    What they came with plus the raw distance of every workout still assigned to
    them. A deleted workout is not one of them, which is the whole of how a
    deletion takes its miles back off a shoe.
    """
    totals = {row.id: row.starting_mi for row in rows}
    if not totals:
        return {}
    for gear_id, covered in db.execute(
        select(models.Workout.gear_id, func.coalesce(func.sum(models.Workout.distance_mi), 0.0))
        .where(
            models.Workout.gear_id.in_(list(totals)),
            models.Workout.deleted_at.is_(None),
        )
        .group_by(models.Workout.gear_id)
    ).all():
        totals[gear_id] += float(covered)
    return totals


def serialize(row: models.Gear, miles: float, *, own: bool) -> dict:
    """One pair, in the shape a profile carries it.

    The size and the width are on a friend's copy deliberately: reading what
    somebody wears is the point of showing gear to a friend at all. Everything
    that is only the owner's business -- what the pair started at, when they
    mean to replace it, and whether it is the one new workouts take -- is added
    by the `own` half and never crosses.
    """
    shown = {
        "id": row.id,
        "style": row.style,
        "brand": row.brand,
        "model": row.model,
        "nickname": row.nickname,
        "size": row.size,
        "width": row.width,
        "miles": round(miles, 1),
        "retired": row.retired_at is not None,
    }
    if own:
        shown["starting_mi"] = round(row.starting_mi, 1)
        shown["replace_around_mi"] = row.replace_around_mi
        shown["is_default"] = row.is_default
        shown["applies_to"] = row.applies_to
    return shown


def gear_list(db: Session, user_id: int, *, own: bool) -> list[dict]:
    """One account's gear with its miles worked out, ready to serve."""
    rows = owned(db, user_id)
    miles = mileage(db, rows)
    return [serialize(row, miles.get(row.id, row.starting_mi), own=own) for row in rows]


def default_pair(db: Session, user_id: int) -> models.Gear | None:
    """The pair new walks and runs are assigned to, or None.

    The row rather than its id, because what it is stamped on is the row's own
    business now. A retired pair is never it: retiring clears the flag, and this
    reads the flag and the retirement both so a row written any other way cannot
    put a put away shoe back on tomorrow's run.
    """
    return db.execute(
        select(models.Gear).where(
            models.Gear.user_id == user_id,
            models.Gear.is_default.is_(True),
            models.Gear.retired_at.is_(None),
        )
    ).scalar_one_or_none()


def takes(row: models.Gear, activity: str) -> bool:
    """Whether a new activity of this kind is stamped with this pair.

    Automatic assignment only. Anybody can put any pair on any walk or run
    themselves, and that choice never reads this: somebody who says a pair is
    for runs is saying where it goes by default, not where it may go.
    """
    return activity in GEAR_ACTIVITIES and row.applies_to in (DEFAULT_APPLIES, activity)


def in_use(db: Session, gear_id: int) -> bool:
    """Whether any workout still names this pair, deleted ones included: a
    deleted workout can be restored, and it would come back wearing shoes that
    no longer exist."""
    return (
        db.execute(
            select(models.Workout.id).where(models.Workout.gear_id == gear_id).limit(1)
        ).first()
        is not None
    )


def retire(row: models.Gear, moment: dt.datetime) -> None:
    """Put a pair away. It stops being the default in the same act, because a
    default that is out of the pickers would still be assigned to tomorrow's
    walk."""
    row.retired_at = moment
    row.is_default = False
