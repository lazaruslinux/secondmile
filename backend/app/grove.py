"""The plot: what is growing in it, the satchel beside it, and the oil.

Growth is passive and generous. Every planting grows from every credited
workout at once, there is nothing to tend, nothing withers, and nothing is on a
timer: the miles are the water. Swimming brings extra.

Nothing here is derived from the workouts alone. What somebody planted, what
they poured it on, and who they anointed are choices, so a rebuild replays
growth and never touches the rows themselves.
"""

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, species
from app.config import SWIM_GROWTH_BONUS, WATER_POUR_MI

# The two items one person can spend on another. Seeds are not here: a seed is
# planted in your own plot and never crosses a fence, so it has no other side to
# count.
GIVEN_KINDS = ("oil", "water")

# Three drawings per species: a seedling, something growing, and the grown
# thing. The first third of the way to level one is the seedling; from level one
# on it is drawn grown, however many levels it goes on to put on.
_SEEDLING_FRACTION = 1.0 / 3.0


def level_step_mi(species_id: str) -> float:
    """What one level of a species costs, in converted Miles."""
    row = species.BY_ID.get(species_id)
    return row.level_mi if row is not None else 0.0


def level_for(species_id: str, growth_mi: float) -> int:
    """How many levels that much growth is worth, and never more than the last.

    The miles keep adding up past the cap, which is honest bookkeeping and
    nothing more: a plant at the top is finished and stays there.
    """
    step = level_step_mi(species_id)
    if step <= 0:
        return 0
    # The tolerance is for float addition: fifteen miles arrived in pieces
    # should be level one, not a hair under it.
    return min(species.MAX_LEVEL, int((growth_mi + 1e-9) // step))


def level_of(row: models.Planting) -> int:
    """Which level a planting has reached, counting from zero."""
    return level_for(row.species, row.growth_mi)


def is_mature(row: models.Planting) -> bool:
    """Grown enough to bear fruit, which is level one for everything."""
    return level_of(row) >= species.MATURE_LEVEL


def is_gilded(row: models.Planting) -> bool:
    """Fully grown: the last level, and nothing left to add to it."""
    return level_of(row) >= species.MAX_LEVEL


def growth_fraction(row: models.Planting) -> float:
    """How full the bar is: the way through the level it is in, and full at the
    top, where there is no next level to fill."""
    step = level_step_mi(row.species)
    if step <= 0 or is_gilded(row):
        return 1.0
    return round((row.growth_mi % step) / step, 4)


def stage_for(species_id: str, growth_mi: float) -> int:
    """Which of the three drawings that much growth is at, from 1 to 3.

    Takes the numbers rather than the row, the same way level_for does, because
    the letter asks this of a growth figure written down weeks ago as well as of
    the plant standing in the plot today.
    """
    if level_for(species_id, growth_mi) >= species.MATURE_LEVEL:
        return 3
    step = level_step_mi(species_id)
    if step <= 0:
        return 1
    return 1 if growth_mi < step * _SEEDLING_FRACTION else 2


def stage(row: models.Planting) -> int:
    """Which of the three drawings a planting is at, from 1 to 3."""
    return stage_for(row.species, row.growth_mi)


def growth_amount(miles: float, activity: str) -> float:
    """What one workout's converted Miles are worth to a planting, swimming's
    extra water included."""
    return miles * (1.0 + SWIM_GROWTH_BONUS) if activity == "swim" else miles


def _advance(row: models.Planting, amount: float, moment: dt.datetime) -> None:
    """Add growth and note the day it came of age, once."""
    row.growth_mi += amount
    if row.matured_at is None and is_mature(row):
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
    amount = growth_amount(miles, activity)
    rows = db.execute(
        select(models.Planting).where(
            models.Planting.user_id == user_id,
            models.Planting.planted_at <= moment,
        )
    ).scalars()
    for row in rows:
        _advance(row, amount, moment)


def held_species(db: Session, user_id: int) -> set[str]:
    """Every species an account already has: growing in the plot, or waiting in
    the satchel as a seed nobody has planted yet.

    The plot holds one of each, so this is what a chest roll has to steer around.
    A spent seed is not held: it is the planting it became.
    """
    planted = db.execute(
        select(models.Planting.species).where(models.Planting.user_id == user_id)
    ).scalars()
    waiting = db.execute(
        select(models.SatchelItem.species).where(
            models.SatchelItem.user_id == user_id,
            models.SatchelItem.kind == "seed",
            models.SatchelItem.used_at.is_(None),
        )
    ).scalars()
    return {row for row in (*planted, *waiting) if row}


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
        # Bare ground is level zero, and writing it down now is what lets the
        # letter announce the first level a new plant reaches without waiting
        # for an acknowledgement to record where it started.
        level_at_ack=0,
        # Bare ground on the other measure too, so a seed planted today can be
        # said to have come up when it does.
        growth_at_ack=0.0,
    )
    item.used_at = moment
    db.add(row)
    db.flush()
    return row


def spend_wish(
    db: Session, item: models.SatchelItem, species_id: str | None, moment: dt.datetime
) -> models.SatchelItem:
    """Turn a wish into the seed it named, or into water when it named nothing.

    The wish is spent and what it became is an item of its own, the same way a
    chest hands over an item rather than changing into one. The new seed carries
    its species' own rarity: a wish is how it arrived, not what it is worth. The
    water it falls back to keeps the wish's rarity instead, because what a slot
    was worth is what the water out of it is worth.
    """
    row = species.BY_ID.get(species_id or "")
    made = models.SatchelItem(
        user_id=item.user_id,
        kind="seed" if row is not None else "water",
        species=row.id if row is not None else None,
        rarity=row.rarity if row is not None else item.rarity,
        # The chest the wish came out of is the chest this came out of too.
        chest_id=item.chest_id,
        acquired_at=moment,
        used_at=None,
    )
    item.used_at = moment
    db.add(made)
    db.flush()
    return made


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
    """Everything spent on this account and not yet attached to a chest.

    Oldest first, which is the order they are spent in: one gift lifts one
    chest, and the friend who gave first is the friend the next chest names.
    """
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


def pending_gift_names(db: Session, user_id: int) -> list[str]:
    """Who the gifts still waiting on this account came from, oldest first.

    Names rather than rows, because this is the reading side: the profile says
    which friend's oil is on the chest ahead and which are queued behind it.
    """
    return list(
        db.execute(
            select(models.User.username)
            .join(models.Anointing, models.Anointing.from_user_id == models.User.id)
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
    # A wish is named for what it promises, because it has not been spent on a
    # species yet. Water and oil are named by nothing: they are the same
    # wherever they came from.
    seed_name = species.WISH_NAME if row.kind == "wish" else None
    return {
        "id": row.id,
        "kind": row.kind,
        "species": row.species,
        # Both names on every seed, so nothing on the client composes one: the
        # satchel says the seed and the plot says what it becomes.
        "seed_name": kind.seed_name if kind is not None else seed_name,
        "plant_name": kind.plant_name if kind is not None else None,
        "rarity": row.rarity,
        # The one species with something about it to explain says it here.
        "reveal": kind.reveal or None if kind is not None else None,
        "acquired_at": row.acquired_at.isoformat(),
    }


def serialize_planting(row: models.Planting) -> dict:
    """One thing growing, with how far along it is."""
    kind = species.BY_ID.get(row.species)
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
        # What it has taken in, which keeps counting past the last level.
        "growth_mi": round(row.growth_mi, 2),
        # The bar, already worked out: the way through the level it is in.
        "growth": growth_fraction(row),
        "stage": stage(row),
        # Level one is grown, and the last level is gilded and finished.
        "level": level,
        "level_mi": level_step_mi(row.species),
        "mature": level >= species.MATURE_LEVEL,
        "gilded": level >= species.MAX_LEVEL,
        "matured_at": row.matured_at.isoformat() if row.matured_at is not None else None,
        # How much extra it will bear next time, bought with manna.
        # Fruit and only fruit: none of the numbers above it move when this one
        # does (TWO-LANE LAW).
        "fed": row.fed_bonus,
    }


def serialize_for_friend(row: models.Planting) -> dict:
    """What a friend sees of somebody else's plot.

    Enough to pick one and pour water into it: which plant it is, how far along
    it has come, how many levels it has put on, and whether it is already grown.

    The level is here on his word, and it is the one number that crossed the
    fence. Still never the miles behind it and still never a date: a level says
    how a plant is doing, which is what somebody looking over the fence would
    see anyway, while the miles and the dates are a record of how its owner
    spent their weeks. The first is a garden and the second is a ledger.
    """
    kind = species.BY_ID.get(row.species)
    return {
        "id": row.id,
        "species": row.species,
        "seed_name": kind.seed_name if kind is not None else row.species,
        "plant_name": kind.plant_name if kind is not None else row.species,
        "rarity": row.rarity,
        "growth": growth_fraction(row),
        "level": level_of(row),
        "stage": stage(row),
        "mature": is_mature(row),
        # Finished, so a friend knows there is no point pouring water into it.
        "gilded": is_gilded(row),
        # How much it has already been fed, so a friend can see there is no room
        # left before they spend anything on it. A count of feeding rather than
        # a fact about its owner's weeks, which is why it crosses the fence.
        "fed": row.fed_bonus,
    }


def summary(db: Session, user_id: int) -> dict:
    """What the profile says about the plot: how much of it has been found, and
    how far everything in it has come.

    The seeds found are the twelve, and the mustard tree is not one of them. It
    was given rather than found, and a count it belonged to would read thirteen
    and ask the question the game never answers. The levels are a sum across
    everything in the ground, the mustard among them, because a sum has no
    total to sit under and so no number to give away either.
    """
    rows = db.execute(
        select(models.Planting.species, models.Planting.growth_mi).where(
            models.Planting.user_id == user_id
        )
    ).all()
    found = held_species(db, user_id) - {species.FIRST_CHEST_SPECIES}
    return {
        "seeds_found": len(found),
        # The displayed level, so a plant at the top adds what it shows.
        "plant_levels": sum(
            level_for(species_id, growth_mi) for species_id, growth_mi in rows
        ),
    }


def item_tallies(db: Session, user_id: int) -> dict:
    """How much oil and water an account has spent, and how much of it arrived.

    Counts and nothing else: no names and no dates. A tally says how much giving
    has passed through an account without saying who did any of it or when, so
    it can sit on a friend's screen as readily as on your own.

    Used is a spent item of that kind, whoever it was spent on: water poured
    into your own plot is water used. Received is the other side of a gift and
    so is never your own doing. Water is read off the item itself, which records
    whose plot it went into; oil is read off the anointings it made, and only
    those that have already landed on a chest. A gift still waiting says nothing
    anywhere until then, which is the whole of the oil rule, and a number that
    moved the moment it was given would be the announcement oil never makes.
    """
    used = dict(
        db.execute(
            select(models.SatchelItem.kind, func.count())
            .where(
                models.SatchelItem.user_id == user_id,
                models.SatchelItem.kind.in_(GIVEN_KINDS),
                models.SatchelItem.used_at.is_not(None),
            )
            .group_by(models.SatchelItem.kind)
        ).all()
    )
    water_received = db.execute(
        select(func.count())
        .select_from(models.SatchelItem)
        .where(
            models.SatchelItem.kind == "water",
            # Only ever set when the plot belonged to somebody else, so this
            # never counts a pour into your own ground as a gift to yourself.
            models.SatchelItem.given_to_user_id == user_id,
        )
    ).scalar_one()
    oil_received = db.execute(
        select(func.count())
        .select_from(models.Anointing)
        .where(
            models.Anointing.to_user_id == user_id,
            models.Anointing.consumed_at.is_not(None),
        )
    ).scalar_one()
    return {
        "oil": {"used": used.get("oil", 0), "received": oil_received},
        "water": {"used": used.get("water", 0), "received": water_received},
    }
