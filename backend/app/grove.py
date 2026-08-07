"""The plot: what is growing in it, the satchel beside it, and the oil.

Growth is passive and generous. Every planting grows from every credited
workout at once, there is nothing to tend, nothing withers, and nothing is on a
timer: the miles are the water. Swimming brings extra.

Nothing here is derived from the workouts alone. What somebody planted, what
they poured it on, and who they anointed are choices, so a rebuild replays
growth and never touches the rows themselves.
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, species
from app.config import SWIM_GROWTH_BONUS, WATER_POUR_MI

# Three drawings per species: a seedling, something growing, and the grown
# thing. The first third of the way is the seedling.
_SEEDLING_FRACTION = 1.0 / 3.0


def maturity_mi(species_id: str) -> float:
    """What one species costs to grow, in converted Miles. Zero for anything
    that never matures."""
    row = species.BY_ID.get(species_id)
    return row.maturity_mi if row is not None else 0.0


def level_step_mi(species_id: str) -> float:
    """What one level costs a species that levels, and zero for the rest."""
    row = species.BY_ID.get(species_id)
    return row.level_mi if row is not None else 0.0


def level_of(row: models.Planting) -> int | None:
    """Which level a levelling planting has reached, counting from zero and
    never stopping. None for everything that matures instead."""
    step = level_step_mi(row.species)
    if step <= 0:
        return None
    return int(row.growth_mi // step)


def growth_fraction(row: models.Planting) -> float:
    """How full the bar is: toward maturity, or through the level it is in."""
    step = level_step_mi(row.species)
    if step > 0:
        return round((row.growth_mi % step) / step, 4)
    target = maturity_mi(row.species)
    if target <= 0:
        return 1.0
    return round(min(row.growth_mi / target, 1.0), 4)


def stage(row: models.Planting) -> int:
    """Which of the three drawings a planting is at, from 1 to 3."""
    level = level_of(row)
    if level is not None:
        # Plant, shrub, tree. It keeps levelling past the last drawing.
        return min(3, level + 1)
    target = maturity_mi(row.species)
    if target <= 0 or row.growth_mi + 1e-9 >= target:
        return 3
    return 1 if row.growth_mi < target * _SEEDLING_FRACTION else 2


def _advance(row: models.Planting, amount: float, moment: dt.datetime) -> None:
    """Add growth and note the day it came to maturity, once."""
    row.growth_mi += amount
    target = maturity_mi(row.species)
    if row.matured_at is None and target > 0 and row.growth_mi + 1e-9 >= target:
        row.matured_at = moment


def grow(
    db: Session, user_id: int, miles: float, activity: str, moment: dt.datetime
) -> None:
    """Grow everything in one account's plot by one workout's converted Miles.

    All of it at once, because a plot is not a queue and choosing what to feed
    would be the tending this game does not have. Swimming adds half again on
    top: the extra water rule, which is the one thing a stroke count is worth
    here that a mile of it is not.

    Only plantings that were already in the ground when the workout arrived
    grow from it. That is what makes a rebuild replay to the same numbers: the
    moment is the workout's own, never the clock.
    """
    if miles <= 0:
        return
    amount = miles * (1.0 + SWIM_GROWTH_BONUS) if activity == "swim" else miles
    rows = db.execute(
        select(models.Planting).where(
            models.Planting.user_id == user_id,
            models.Planting.planted_at <= moment,
        )
    ).scalars()
    for row in rows:
        _advance(row, amount, moment)


def plant(
    db: Session, user_id: int, item: models.SatchelItem, moment: dt.datetime
) -> models.Planting:
    """Put a seed in the ground. The plot has no size limit this round."""
    row = models.Planting(
        user_id=user_id,
        species=item.species or "",
        rarity=item.rarity,
        planted_at=moment,
        growth_mi=0.0,
        matured_at=None,
    )
    item.used_at = moment
    db.add(row)
    db.flush()
    return row


def pour(row: models.Planting, moment: dt.datetime) -> None:
    """Empty one water item into one planting."""
    _advance(row, WATER_POUR_MI, moment)


def reset_growth(db: Session, user_id: int) -> None:
    """Take every planting back to bare ground for a rebuild to replay.

    The plantings themselves stay. What was planted is a choice somebody made;
    only how far it has come is derived from the miles.
    """
    for row in db.execute(
        select(models.Planting).where(models.Planting.user_id == user_id)
    ).scalars():
        row.growth_mi = 0.0
        row.matured_at = None


# --------------------------------------------------------------------------
# Oil
# --------------------------------------------------------------------------


def pending_anointings(db: Session, user_id: int) -> list[models.Anointing]:
    """Everything spent on this account and not yet turned into a chest."""
    return list(
        db.execute(
            select(models.Anointing)
            .where(
                models.Anointing.to_user_id == user_id,
                models.Anointing.consumed_at.is_(None),
            )
            .order_by(models.Anointing.id)
        ).scalars()
    )


def anointing_waits(db: Session, from_user_id: int, to_user_id: int) -> bool:
    """Whether one of these two already has an unspent gift waiting."""
    return (
        db.execute(
            select(models.Anointing.id)
            .where(
                models.Anointing.from_user_id == from_user_id,
                models.Anointing.to_user_id == to_user_id,
                models.Anointing.consumed_at.is_(None),
            )
            .limit(1)
        ).first()
        is not None
    )


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------


def serialize_item(row: models.SatchelItem) -> dict:
    """One thing in the satchel. Its kind is its verb, so the client needs
    nothing else to know what can be done with it."""
    kind = species.BY_ID.get(row.species or "")
    return {
        "id": row.id,
        "kind": row.kind,
        "species": row.species,
        # Both names on every seed, so nothing on the client composes one: the
        # satchel says the seed and the plot says what it becomes. Null for
        # water and oil, which are the same wherever they came from.
        "seed_name": kind.seed_name if kind is not None else None,
        "plant_name": kind.plant_name if kind is not None else None,
        "rarity": row.rarity,
        # The one species with something about it to explain says it here.
        "reveal": kind.reveal or None if kind is not None else None,
        "acquired_at": row.acquired_at.isoformat(),
    }


def serialize_planting(row: models.Planting) -> dict:
    """One thing growing, with how far along it is."""
    kind = species.BY_ID.get(row.species)
    target = maturity_mi(row.species)
    grown = row.matured_at is not None
    level = level_of(row)
    return {
        "id": row.id,
        "species": row.species,
        # The planted form is what a plot is read in, and the seed name rides
        # along so a reveal and a plot row never disagree about one species.
        "seed_name": kind.seed_name if kind is not None else row.species,
        "plant_name": kind.plant_name if kind is not None else row.species,
        "rarity": row.rarity,
        "planted_at": row.planted_at.isoformat(),
        "growth_mi": round(row.growth_mi, 2),
        # Zero for anything that levels rather than maturing.
        "maturity_mi": target,
        # The bar, already worked out, and never past full.
        "growth": growth_fraction(row),
        "stage": stage(row),
        "mature": grown,
        "matured_at": row.matured_at.isoformat() if grown else None,
        # Null for everything that matures. A levelling planting counts levels
        # instead and never reads as grown.
        "level": level,
        "level_mi": level_step_mi(row.species) if level is not None else None,
        # What it will bear when fruit arrives. Nothing bears anything yet.
        "produce": kind.produce if kind is not None else None,
    }


def serialize_for_friend(row: models.Planting) -> dict:
    """What a friend sees of somebody else's plot.

    Enough to pick one and pour water into it: which plant it is, how far along
    it has come, and whether it is already grown. Never the miles behind that
    fraction, and never a date. A garden is something seen over the fence, not
    a page of somebody's statistics.
    """
    kind = species.BY_ID.get(row.species)
    return {
        "id": row.id,
        "species": row.species,
        "seed_name": kind.seed_name if kind is not None else row.species,
        "plant_name": kind.plant_name if kind is not None else row.species,
        "rarity": row.rarity,
        "growth": growth_fraction(row),
        "stage": stage(row),
        "mature": row.matured_at is not None,
    }


def summary(db: Session, user_id: int) -> dict:
    """What the profile says about the plot: how much is in it, how much grown."""
    rows = list(
        db.execute(
            select(models.Planting.matured_at).where(models.Planting.user_id == user_id)
        ).scalars()
    )
    return {
        "planted": len(rows),
        "mature": sum(1 for matured_at in rows if matured_at is not None),
    }
