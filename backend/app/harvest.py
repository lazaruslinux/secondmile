"""The harvest: what a grown plant bears, and what manna is spent on.

Two lanes meet here and neither crosses. The MILES decide when a grove bears:
the meter beside the chest ladder is fed by converted Miles alone, and at the
top of it every mature plant bears at once. The MANNA decides how much: fed
plants bear more, and gathered manna is the only thing that ever buys that.
Nothing in this file touches experience, a level, a chest, growth or a medal,
and a release that taught it to would be the design bug the TWO-LANE LAW names.

Three states, and everything only ever moves forward through them. Fruit sits
on the plant and manna sits in the pending pile, both safe forever. Gathering
brings them in, and gathered goods live GATHERED_LIFE_DAYS and then quietly go
back to the soil. Nothing counts down anywhere: the sweep runs when an account
is already being read or credited, the way every other passive sweep here does.
"""

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import grove, models, species
from app.config import (
    FRUIT_SEASON_MI,
    FRUIT_YIELD,
    GATHERED_LIFE_DAYS,
    GOLDEN_FRUIT_PREFIX,
    SERVER_TZ,
)

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


def gathered_manna(db: Session, user_id: int) -> int:
    """What is in the gathered pile and spendable, across every live batch."""
    return int(
        db.execute(
            select(func.coalesce(func.sum(models.MannaBatch.remaining), 0)).where(
                models.MannaBatch.user_id == user_id,
                models.MannaBatch.composted_at.is_(None),
            )
        ).scalar_one()
    )


def gathered_ever(db: Session, user_id: int) -> int:
    """Everything that has ever left the pending pile by being gathered.

    What a rebuild subtracts. From pending's side gathering is a spend, and
    spent stays spent: a workout taken back may take its calories out of what is
    still waiting, and it can never reach into what was already brought in.
    """
    return int(
        db.execute(
            select(func.coalesce(func.sum(models.MannaBatch.amount), 0)).where(
                models.MannaBatch.user_id == user_id
            )
        ).scalar_one()
    )


def gifted_manna_ever(db: Session, user_id: int) -> int:
    """Every raw manna gift this account has been given.

    A gift joins the pending pile, so a rebuild of that pile has to add it back:
    it is not a derivation of anybody's workouts, and taking a run back must
    never take away what a friend sent.
    """
    return int(
        db.execute(
            select(func.coalesce(func.sum(models.MannaGift.amount), 0)).where(
                models.MannaGift.to_user_id == user_id
            )
        ).scalar_one()
    )


def gather(
    db: Session, progress: models.UserProgress, moment: dt.datetime, manna: int = 0
) -> dict:
    """Bring in the harvest, and as much of the pending manna as was asked for.

    One act on one screen, because a grove is one place. The two halves of it
    are not the same shape, and that is his call: fruit comes in whole, because
    a harvest is a harvest and there is no sense in leaving half of it hanging,
    while manna comes in by the amount somebody chooses. A pile built out of a
    year of calories is far more than any week of giving spends, and gathering
    all of it would be composting most of it seven days later.

    What is gathered starts its seven days here and nowhere earlier. Everything
    left behind, on the plant and in the pending pile, stays safe forever.

    Flushes but never commits: the caller owns the transaction.
    """
    fruit = on_the_plant(db, progress.user_id)
    for row in fruit:
        row.gathered_at = moment
    manna = min(max(manna, 0), max(progress.manna_pending, 0))
    if manna > 0:
        db.add(
            models.MannaBatch(
                user_id=progress.user_id,
                amount=manna,
                remaining=manna,
                gathered_at=moment,
                composted_at=None,
            )
        )
        progress.manna_pending -= manna
    db.flush()
    # Named apart from the balances the caller answers with. "manna" there is
    # what is in the pile; this is what this one act brought in, and one word
    # meaning both would be a note on screen saying the wrong number.
    return {
        "fruit": sum(row.count for row in fruit),
        "batches": len(fruit),
        "gathered_manna": manna,
    }


def compost(db: Session, user_id: int, moment: dt.datetime) -> None:
    """Quietly return whatever has been gathered too long to the soil.

    Passive, and run where the account is already being read or credited: this
    app has no scheduler and wants none. Nothing is announced as it happens and
    nothing counts down to it; the letter says one soft line afterwards if there
    is one to say.

    Only gathered goods age. Fruit on the plant, manna still pending, fruit
    already given away and a batch spent to nothing are all untouched.
    """
    cutoff = moment - WINDOW
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
    for row in db.execute(
        select(models.MannaBatch).where(
            models.MannaBatch.user_id == user_id,
            models.MannaBatch.gathered_at <= cutoff,
            models.MannaBatch.composted_at.is_(None),
            models.MannaBatch.remaining > 0,
        )
    ).scalars():
        row.composted_at = moment
    db.flush()


def composted_since(db: Session, user_id: int, since: dt.datetime | None) -> bool:
    """Whether anything went back to the soil since the letter was put down."""
    fruit = select(models.FruitBatch.id).where(
        models.FruitBatch.user_id == user_id, models.FruitBatch.composted_at.is_not(None)
    )
    manna = select(models.MannaBatch.id).where(
        models.MannaBatch.user_id == user_id, models.MannaBatch.composted_at.is_not(None)
    )
    if since is not None:
        fruit = fruit.where(models.FruitBatch.composted_at > since)
        manna = manna.where(models.MannaBatch.composted_at > since)
    return (
        db.execute(fruit.limit(1)).first() is not None
        or db.execute(manna.limit(1)).first() is not None
    )


# --------------------------------------------------------------------------
# Spending
# --------------------------------------------------------------------------


def spend_manna(db: Session, user_id: int, amount: int) -> bool:
    """Take manna out of the gathered pile, oldest batch first.

    Oldest first so that spending never leaves an old pile to rot behind a new
    one. Answers False and takes nothing when the pile does not cover it, which
    is what makes this the one place a balance is checked and changed together:
    two requests racing on the same pile cannot both pass a read done earlier.

    Only ever the gathered pile. Pending manna is not spendable by anything.
    """
    if amount <= 0:
        return False
    batches = list(
        db.execute(
            select(models.MannaBatch)
            .where(
                models.MannaBatch.user_id == user_id,
                models.MannaBatch.composted_at.is_(None),
                models.MannaBatch.remaining > 0,
            )
            .order_by(models.MannaBatch.gathered_at, models.MannaBatch.id)
            .with_for_update()
        ).scalars()
    )
    if sum(row.remaining for row in batches) < amount:
        return False
    owing = amount
    for row in batches:
        if owing <= 0:
            break
        taken = min(row.remaining, owing)
        row.remaining -= taken
        owing -= taken
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
