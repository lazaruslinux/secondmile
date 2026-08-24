"""The harvest: what a grown plant bears, and what manna is spent on.

Two lanes meet here and neither crosses. The MILES decide when a grove bears:
the meter beside the chest ladder is fed by converted Miles alone, and at the
top of it every mature plant bears at once. The MANNA decides how much: fed
plants bear more, and manna is the only thing that ever buys that. Nothing in
this file touches experience, a level, a chest, growth or a medal, and a
release that taught it to would be the design bug the TWO-LANE LAW names.

Manna is a permanent bank. Calories earn it, spending it lowers it, and it
never spoils, is never gathered and never counts down.

Spoiling is fruit's alone. Fruit sits on the plant, safe forever; gathering
brings it in, and gathered fruit lives GATHERED_LIFE_DAYS and then quietly goes
back to the soil. Nothing counts down there either: the sweep runs when an
account is already being read or credited, the way every other passive sweep
here does.
"""

import datetime as dt

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import grove, models, species
from app.config import (
    FRUIT_SEASON_MI,
    FRUIT_YIELD,
    GATHERED_LIFE_DAYS,
    GOLDEN_FRUIT_PREFIX,
    MANNA_TO_ONE_PERSON_DAYS,
    SERVER_TZ,
)
from app.db import rows_touched

# Month names written out rather than taken from strftime, which answers in
# whichever locale the container happens to have. A provenance line is content,
# and content does not change because an image was rebuilt.
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

WINDOW = dt.timedelta(days=GATHERED_LIFE_DAYS)


# --------------------------------------------------------------------------
# What a plant bears, and what it is called
# --------------------------------------------------------------------------


def fruit_yield(species_id: str, rarity: str) -> int:
    """How many a plant of this kind bears, before anything it was fed.

    The species is asked first and the rarity second, because the mustard tree
    is filed as a rare for rolling purposes only and what it bears is a decision
    about the mustard tree rather than about rares. An unknown species bears the
    common count rather than nothing: a plant standing in somebody's grove is
    not the place to discover a catalogue gap.
    """
    if species_id in FRUIT_YIELD:
        return FRUIT_YIELD[species_id]
    return FRUIT_YIELD.get(rarity, FRUIT_YIELD["common"])


def fruit_name(species_id: str, golden: bool = False, plural: bool = True) -> str:
    """What one species' harvest is called: bananas, olives, coffee cherries.

    Lower case, because the catalogue authors these as the nouns they are and
    every place they are said is a phrase around them. A fully grown plant's
    harvest takes the finer name and the same count.

    Both numbers, because a rare tree bears exactly one and "1 olives" is not a
    sentence anybody wrote.
    """
    row = species.BY_ID.get(species_id)
    if row is None:
        name = "fruit"
    else:
        name = row.produce if plural else row.produce_one
    return f"{GOLDEN_FRUIT_PREFIX}{name}" if golden else name


def fruit_words(count: int, species_id: str, golden: bool = False) -> str:
    """A count of fruit as it is said: "3 bananas", "1 golden olive"."""
    return f"{count} {fruit_name(species_id, golden, plural=count != 1)}"


def month_of(moment: dt.datetime) -> str:
    """The month a bearing happened in, on the instance's own clock, which is
    the clock every date on screen is read on."""
    return MONTHS[moment.astimezone(SERVER_TZ).month - 1]


def provenance(row: models.FruitBatch) -> str:
    """What a batch says about itself when it is given away.

    Everything in it was written down when the fruit came in, so the sentence a
    gift carries is the same sentence a year later and does not move when a
    constant is retuned.
    """
    miles = int(row.season_mi) if float(row.season_mi).is_integer() else round(row.season_mi, 1)
    return (
        f"{fruit_words(row.count, row.species, row.golden)}, "
        f"grown over {miles} miles in {row.season_month}"
    )


# --------------------------------------------------------------------------
# Bearing
# --------------------------------------------------------------------------


def bear(
    db: Session, user_id: int, moment: dt.datetime, season: int
) -> list[models.FruitBatch]:
    """Every mature plant in one grove bears, at once.

    Grove-wide on purpose: a plot is not a queue, and choosing which plant to
    harvest would be the tending this game does not have. Only plants that have
    come of age bear at all, and whatever they were fed is spent here and reset,
    so feeding is done for one harvest rather than bought once.

    The moment is the caller's, never the clock, so a rebuild that has to bear
    writes what the first pass wrote. The season is which bearing this is,
    counting from one: one workout can cross the meter twice, and both crossings
    carry that workout's own stamp.
    """
    borne = []
    month = month_of(moment)
    for row in db.execute(
        select(models.Planting)
        .where(models.Planting.user_id == user_id)
        .order_by(models.Planting.id)
    ).scalars():
        if not grove.is_mature(row):
            continue
        golden = grove.is_gilded(row)
        batch = models.FruitBatch(
            user_id=user_id,
            planting_id=row.id,
            species=row.species,
            golden=golden,
            count=fruit_yield(row.species, row.rarity) + max(row.fed_bonus, 0),
            season=season,
            season_mi=FRUIT_SEASON_MI,
            season_month=month,
            borne_at=moment,
        )
        # Spent on this harvest, which is what banking it meant.
        row.fed_bonus = 0
        db.add(batch)
        borne.append(batch)
    db.flush()
    return borne


# --------------------------------------------------------------------------
# Gathering, and what happens to what is gathered
# --------------------------------------------------------------------------


def on_the_plant(db: Session, user_id: int) -> list[models.FruitBatch]:
    """Fruit borne and not yet gathered, oldest first. Safe forever."""
    return list(
        db.execute(
            select(models.FruitBatch)
            .where(
                models.FruitBatch.user_id == user_id,
                models.FruitBatch.gathered_at.is_(None),
                models.FruitBatch.composted_at.is_(None),
                models.FruitBatch.given_at.is_(None),
            )
            .order_by(models.FruitBatch.id)
        ).scalars()
    )


def in_the_basket(db: Session, user_id: int) -> list[models.FruitBatch]:
    """Fruit already gathered and still there: not composted, not given away."""
    return list(
        db.execute(
            select(models.FruitBatch)
            .where(
                models.FruitBatch.user_id == user_id,
                models.FruitBatch.gathered_at.is_not(None),
                models.FruitBatch.composted_at.is_(None),
                models.FruitBatch.given_at.is_(None),
            )
            .order_by(models.FruitBatch.id)
        ).scalars()
    )


def gifted_manna_ever(db: Session, user_id: int) -> int:
    """Every raw manna gift this account has been given.

    A gift lands in the bank, so a rebuild of the bank has to add it back: it is
    not a derivation of anybody's workouts, and taking a run back must never
    take away what a friend sent.
    """
    return int(
        db.execute(
            select(func.coalesce(func.sum(models.MannaGift.amount), 0)).where(
                models.MannaGift.to_user_id == user_id
            )
        ).scalar_one()
    )


def spent_manna_ever(db: Session, user_id: int) -> int:
    """Every manna this account has ever spent: fed to a plant, or given away.

    What a rebuild subtracts, because spent stays spent (R31): a workout taken
    back lowers what the surviving history is worth and can never reach into
    what has already gone to a plant or to a friend.

    Feeding your own plot counts. It is a spend like any other; that it bought
    your own fruit is a fact about who it went to, not about whether it left.

    One thing this cannot see: manna that composted under the old gathered-pile
    model, before 0030 folded the piles into one bank. Those rows are dormant
    history and are not read, so a rebuild of an account that lost some would
    hand it back. Bounded, one-off, and named in 0030's own docstring.
    """
    fed = db.execute(
        select(func.coalesce(func.sum(models.PlantFeeding.manna_spent), 0)).where(
            models.PlantFeeding.from_user_id == user_id
        )
    ).scalar_one()
    given = db.execute(
        select(func.coalesce(func.sum(models.MannaGift.amount), 0)).where(
            models.MannaGift.from_user_id == user_id
        )
    ).scalar_one()
    return int(fed) + int(given)


def given_to_lately(
    db: Session, from_user_id: int, to_user_id: int, moment: dt.datetime
) -> int:
    """How much manna has gone from one account into one other person's hands
    inside the window: their plants fed and raw manna sent, added together.

    What the cap is measured against. Both halves count because both are manna
    put into the same person, and a limit one of them could walk around would
    not be one.
    """
    cutoff = moment - dt.timedelta(days=MANNA_TO_ONE_PERSON_DAYS)
    fed = db.execute(
        select(func.coalesce(func.sum(models.PlantFeeding.manna_spent), 0)).where(
            models.PlantFeeding.from_user_id == from_user_id,
            models.PlantFeeding.to_user_id == to_user_id,
            models.PlantFeeding.created_at > cutoff,
        )
    ).scalar_one()
    given = db.execute(
        select(func.coalesce(func.sum(models.MannaGift.amount), 0)).where(
            models.MannaGift.from_user_id == from_user_id,
            models.MannaGift.to_user_id == to_user_id,
            models.MannaGift.created_at > cutoff,
        )
    ).scalar_one()
    return int(fed) + int(given)


def gather(db: Session, user_id: int, moment: dt.datetime) -> dict:
    """Bring in the harvest. Fruit, and nothing else.

    One act on one screen, because a grove is one place, and the fruit comes in
    whole: a harvest is a harvest and there is no sense in leaving half of it
    hanging. Manna is not gathered at all any more; it is banked as it is earned.

    What is gathered starts its seven days here and nowhere earlier. What is
    left on the plant stays safe forever.

    Flushes but never commits: the caller owns the transaction.
    """
    fruit = on_the_plant(db, user_id)
    for row in fruit:
        row.gathered_at = moment
    db.flush()
    return {"fruit": sum(row.count for row in fruit), "batches": len(fruit)}


def compost(db: Session, user_id: int, moment: dt.datetime) -> int:
    """Quietly return whatever fruit has been gathered too long to the soil.

    Passive, and run where the account is already being read or credited: this
    app has no scheduler and wants none. Nothing is announced as it happens and
    nothing counts down to it; the letter says one soft line afterwards if there
    is one to say.

    Only gathered fruit ages. Fruit on the plant, fruit already given away, and
    every manna anybody holds are all untouched: the bank does not spoil.

    Answers with how many batches went back, which is almost always none. The
    caller runs on every screen in the app and uses this to decide whether the
    sweep wrote anything worth committing.
    """
    cutoff = moment - WINDOW
    returned = 0
    for row in db.execute(
        select(models.FruitBatch).where(
            models.FruitBatch.user_id == user_id,
            models.FruitBatch.gathered_at.is_not(None),
            models.FruitBatch.gathered_at <= cutoff,
            models.FruitBatch.composted_at.is_(None),
            models.FruitBatch.given_at.is_(None),
        )
    ).scalars():
        row.composted_at = moment
        returned += 1
    db.flush()
    return returned


def composted_since(db: Session, user_id: int, since: dt.datetime | None) -> bool:
    """Whether any fruit went back to the soil since the letter was put down."""
    fruit = select(models.FruitBatch.id).where(
        models.FruitBatch.user_id == user_id, models.FruitBatch.composted_at.is_not(None)
    )
    if since is not None:
        fruit = fruit.where(models.FruitBatch.composted_at > since)
    return db.execute(fruit.limit(1)).first() is not None


# --------------------------------------------------------------------------
# Spending
# --------------------------------------------------------------------------


def spend_manna(db: Session, user_id: int, amount: int) -> bool:
    """Take manna out of the bank. Answers False and takes nothing when the
    bank does not cover it.

    One statement, which reads the balance and lowers it together: two requests
    racing cannot both pass a read taken a moment earlier. The row the caller is
    holding is expired afterwards, so whatever reads the balance next reads what
    this wrote rather than what it loaded.
    """
    if amount <= 0:
        return False
    changed = db.execute(
        update(models.UserProgress)
        .where(
            models.UserProgress.user_id == user_id,
            models.UserProgress.manna >= amount,
        )
        .values(manna=models.UserProgress.manna - amount)
    )
    if rows_touched(changed) != 1:
        return False
    held = db.get(models.UserProgress, user_id)
    if held is not None:
        db.expire(held)
    db.flush()
    return True


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------


def serialize_batch(row: models.FruitBatch) -> dict:
    """One batch of fruit, wherever it is standing."""
    return {
        "id": row.id,
        "planting_id": row.planting_id,
        "species": row.species,
        "name": fruit_name(row.species, row.golden),
        # The count and the name already joined, in the right number. Composed
        # here rather than on the client for the provenance's reason: a phrase
        # built in two places is a phrase that disagrees with itself.
        "label": fruit_words(row.count, row.species, row.golden),
        "count": row.count,
        "golden": row.golden,
        # The whole sentence, composed once on the server: a client that built
        # it would be a second place the format lives.
        "provenance": provenance(row),
        "borne_at": row.borne_at.isoformat(),
        "gathered_at": row.gathered_at.isoformat() if row.gathered_at else None,
    }


def serialize_keepsake(row: models.FruitKeepsake) -> dict:
    """One thing somebody was given, as the basket on the You screen reads it.

    No verb and no number anything spends: a keepsake is a record of a gift.
    """
    return {
        "id": row.id,
        "from": row.from_username,
        "species": row.species,
        "name": fruit_name(row.species, row.golden),
        "label": fruit_words(row.count, row.species, row.golden),
        "count": row.count,
        "golden": row.golden,
        "provenance": row.provenance,
        "received_at": row.received_at.isoformat(),
    }


def keepsakes(db: Session, user_id: int) -> list[models.FruitKeepsake]:
    """Everything this account has ever been given, newest first. Permanent."""
    return list(
        db.execute(
            select(models.FruitKeepsake)
            .where(models.FruitKeepsake.user_id == user_id)
            .order_by(models.FruitKeepsake.received_at.desc(), models.FruitKeepsake.id.desc())
        ).scalars()
    )


def harvest_since(db: Session, user_id: int, since: dt.datetime | None) -> list[dict]:
    """What the grove bore since the letter was last put down, by fruit.

    Piled by name rather than listed by batch, because the letter tells the
    story of a harvest and four banana trees bearing is one sentence. Counted
    whatever became of it afterwards: gathering it, giving it away, or leaving
    it to compost are all things that happened after the news.
    """
    stmt = select(models.FruitBatch).where(models.FruitBatch.user_id == user_id)
    if since is not None:
        stmt = stmt.where(models.FruitBatch.borne_at > since)
    piles: dict[tuple[str, bool], dict] = {}
    for row in db.execute(stmt.order_by(models.FruitBatch.id)).scalars():
        pile = piles.setdefault(
            (row.species, row.golden),
            {"name": fruit_name(row.species, row.golden), "count": 0},
        )
        pile["count"] += row.count
    return [
        {**pile, "label": fruit_words(pile["count"], species_id, golden)}
        for (species_id, golden), pile in piles.items()
    ]
