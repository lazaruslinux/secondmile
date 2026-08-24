"""Grove pets: what the harvest draws, and what fruit is fed to.

The third lane. Manna and Miles are the two the TWO-LANE LAW keeps apart; a pet
is in neither. It confers nothing at all: no manna, no experience, no yield, no
chest odds, no renown, ever. Anything in a later release that reads this table
for a bonus is the same design bug the law names, one lane over.

Nothing here counts down. A pet never starves, never leaves and is never lost;
one that has not been fed is resting, and that is the whole of it. There is no
timer, no warning and nothing to keep up with.

Six species, one of each per grove. A stray is drawn after a harvest whenever
there is no half-grown one already, so the first gather always draws one and the
sixth grown pet is the end of it. The time medals lean the draw: somebody who
runs before six is likelier to be found by a dog, a sheep or a rooster, and
somebody who runs after dark by a bat, a cat or a wolf. They lean it and never
gate it, so every species still missing can win any roll.
"""

import datetime as dt
import random
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import PET_STAGE_FRUIT, PET_WEIGHT_CAP

# The six, in the order they are written down anywhere they are listed. Static
# Python for the reason the seed catalogue is: authored content, so a release
# changes it and no migration has to.
SPECIES: tuple[str, ...] = ("bat", "cat", "wolf", "dog", "sheep", "rooster")

# Which medal leans which half of the set. His own split, verbatim: many Night
# Owl badges lean the draw toward a bat, a cat or a wolf, and many Early Riser
# badges toward a dog, a sheep or a rooster.
LEANS: dict[str, str] = {
    "bat": "night_owl",
    "cat": "night_owl",
    "wolf": "night_owl",
    "dog": "early_riser",
    "sheep": "early_riser",
    "rooster": "early_riser",
}

# The longest name somebody may give one, the length a pair of shoes is
# nicknamed at. A name, and names are short.
MAX_NAME = 60

# Control bytes nobody types, taken out for the reason a bug report's are: they
# survive a strip() and this text is read by things that obey them.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean_name(sent: str | None) -> str | None:
    """What somebody typed, or None for a pet that goes by its species word.

    Blank is how a name is taken back off, so an empty box and a missing field
    are the same answer rather than two.
    """
    cleaned = _CONTROL.sub("", sent or "").strip()
    return cleaned[:MAX_NAME] or None


def display_name(row: models.Pet) -> str:
    """What it is called on screen: its name, or the species word."""
    return row.name or row.species


def stage_for(fruit_fed: int) -> int:
    """Which of the three drawings a pet with this much fruit in it stands at.

    Cumulative thresholds, so what has already been fed is never re-earned and
    a retune moves where the next crossing is rather than undoing an old one.
    """
    second, third = PET_STAGE_FRUIT
    if fruit_fed >= third:
        return 3
    return 2 if fruit_fed >= second else 1


# --------------------------------------------------------------------------
# What a grove holds
# --------------------------------------------------------------------------


def owned(db: Session, user_id: int) -> list[models.Pet]:
    """Every pet in one grove, oldest arrival first."""
    return list(
        db.execute(
            select(models.Pet).where(models.Pet.user_id == user_id).order_by(models.Pet.id)
        ).scalars()
    )


def ungrown(db: Session, user_id: int) -> models.Pet | None:
    """The one still growing, or None. At most one exists: an arrival is only
    ever rolled when there is none, which is what makes feeding unambiguous."""
    return db.execute(
        select(models.Pet)
        .where(models.Pet.user_id == user_id, models.Pet.grown_at.is_(None))
        .order_by(models.Pet.id)
    ).scalars().first()


# --------------------------------------------------------------------------
# Arrival
# --------------------------------------------------------------------------


def _time_medal_counts(db: Session, user_id: int) -> dict[str, int]:
    """How many times this account has earned each of the two time medals.

    Read off badge_earns, which is where the per-workout families live and is
    the only table this lane ever reads. Nothing is written to it here: a pet
    reads the medals and no medal ever hears about a pet.
    """
    wanted = set(LEANS.values())
    found = dict.fromkeys(wanted, 0)
    for badge_id, count in db.execute(
        select(models.BadgeEarn.badge_id, func.count())
        .where(models.BadgeEarn.user_id == user_id, models.BadgeEarn.badge_id.in_(wanted))
        .group_by(models.BadgeEarn.badge_id)
    ).all():
        found[badge_id] = int(count)
    return found


def arrival_weights(db: Session, user_id: int) -> dict[str, int]:
    """How the draw leans, by species, over what this grove is still missing.

    Every candidate starts at one, so no medal is a gate and no species is ever
    out of reach: a grove with no medals at all draws evenly among the six. What
    the two time medals add is capped, because a thousand early mornings should
    lean the draw rather than settle it.

    A species already in the grove, at any stage, is not a candidate. That is
    the whole of the no-duplicate rule: it is not rolled and then re-rolled, it
    is simply not in the bag.
    """
    held = {row.species for row in owned(db, user_id)}
    counts = _time_medal_counts(db, user_id)
    return {
        one: 1 + min(counts[LEANS[one]], PET_WEIGHT_CAP)
        for one in SPECIES
        if one not in held
    }


def roll_arrival(rng: random.Random, weights: dict[str, int]) -> str | None:
    """Which stray is drawn, or None when a grove already holds all six.

    The generator is passed in and seeded by the caller, the way a chest's roll
    is, so the same account and the same harvest agree about what was drawn.
    """
    if not weights:
        return None
    return rng.choices(list(weights), weights=list(weights.values()), k=1)[0]


def maybe_arrive(db: Session, user_id: int, moment: dt.datetime) -> models.Pet | None:
    """Draw a stray to this grove, if there is one to draw.

    Rolled after a harvest and only when nothing is half-grown, so the first
    gather always draws one, a pet is never replaced while it is still growing,
    and the sixth grown pet ends arrivals for good.

    Flushes but never commits: the caller owns the transaction.
    """
    if ungrown(db, user_id) is not None:
        return None
    weights = arrival_weights(db, user_id)
    # Seeded on the account and on how full the grove already is, so a replay of
    # the same harvest draws the same stray.
    drawn = roll_arrival(random.Random(f"{user_id}:pet:{len(SPECIES) - len(weights)}"), weights)
    if drawn is None:
        return None
    row = models.Pet(
        user_id=user_id,
        species=drawn,
        name=None,
        stage=1,
        fruit_fed=0,
        arrived_at=moment,
        staged_at=None,
        grown_at=None,
    )
    db.add(row)
    db.flush()
    return row


# --------------------------------------------------------------------------
# Feeding
# --------------------------------------------------------------------------


def feed(db: Session, pet: models.Pet, count: int, moment: dt.datetime) -> None:
    """Put this many fruit into one pet.

    Every fruit is worth exactly one, whatever it grew on. Golden fruit is worth
    one as well: the finer name earns a different word on the screen and nothing
    else, which is the same bargain gilding already makes with the harvest.

    The fruit itself has already left the basket by the time this is called;
    what happens here is the growing.

    Flushes but never commits: the caller owns the transaction.
    """
    pet.fruit_fed += count
    reached = stage_for(pet.fruit_fed)
    if reached > pet.stage:
        pet.stage = reached
        pet.staged_at = moment
        if reached == 3:
            pet.grown_at = moment
    db.flush()


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------


def serialize(row: models.Pet) -> dict:
    """One pet, on its owner's own screen."""
    second, third = PET_STAGE_FRUIT
    return {
        "id": row.id,
        "species": row.species,
        "name": row.name,
        # Composed here rather than on the client for the reason a fruit's label
        # is: a phrase built in two places is a phrase that disagrees with
        # itself the first time an unnamed pet is drawn.
        "display_name": display_name(row),
        "stage": row.stage,
        "fruit_fed": row.fruit_fed,
        # What the quiet bar on the card is drawn from. A fraction of the way to
        # the next drawing, never a number of fruit still owed: there is nothing
        # to be late for and nothing counts down.
        "next_fruit": None if row.grown_at is not None else (second if row.stage == 1 else third),
        "grown": row.grown_at is not None,
        "arrived_at": row.arrived_at.isoformat(),
    }


def serialize_for_friend(row: models.Pet) -> dict:
    """What somebody else sees of a grove's pets: that they are there.

    Presence and nothing else. No fruit, no progress and no dates: how much
    somebody has fed their own pet is a record of their own weeks, and a friend
    looking over the fence sees an animal in a garden.
    """
    return {
        "species": row.species,
        "name": display_name(row),
        "stage": row.stage,
        "grown": row.grown_at is not None,
    }


def since(db: Session, user_id: int, moment: dt.datetime | None) -> list[dict]:
    """What the pets did since the letter was last put down, oldest first.

    Three things happen to a pet and each is one sentence: one arrived, one grew,
    one finished growing. Read off the stamps on the row rather than out of an
    events table, the way every other line of the letter is.
    """
    events: list[tuple[dt.datetime, dict]] = []
    for row in owned(db, user_id):
        said = {"species": row.species, "name": display_name(row), "stage": row.stage}
        if moment is None or row.arrived_at > moment:
            events.append((row.arrived_at, {**said, "event": "arrived"}))
        if row.grown_at is not None and (moment is None or row.grown_at > moment):
            events.append((row.grown_at, {**said, "event": "grown"}))
        elif row.staged_at is not None and (moment is None or row.staged_at > moment):
            # Only while it is still growing. A pet that crossed both lines in
            # one window says it finished and leaves the middle step unsaid,
            # because two sentences about one animal read as two animals.
            events.append((row.staged_at, {**said, "event": "grew"}))
    events.sort(key=lambda one: one[0])
    return [said for _, said in events]
