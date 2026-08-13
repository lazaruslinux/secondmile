"""The harvest and the four things manna is spent on.

One button gathers, and everything else here is a way of spending what was
gathered: on your own grove quietly, or on somebody else's, which is the half
that pays. Manna never buys a mile, a level, a chest, growth or a medal, and no
endpoint in this file may ever be taught to (TWO-LANE LAW).

Every verb is friend-gated where it acts on somebody else, and a stranger's
plant, a stranger's account and a thing that never existed are all the same 404:
whose plot an id belongs to is not something to learn by asking.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session

from app import fellowship, grove, harvest, models, progress, security, throttle
from app.config import (
    FEED_COST,
    FEED_MAX_BANKED,
    FRUIT_SEASON_MI,
    RENOWN_FEED,
    RENOWN_FRUIT_GIFT,
    RENOWN_MANNA_GIFT,
)
from app.db import get_db

router = APIRouter(tags=["harvest"])

NO_SUCH_PLANT = "No such planting."
NO_SUCH_FRIEND = "No such friend."
NO_SUCH_FRUIT = "No such fruit."
NOT_ENOUGH = "You have not gathered enough manna for that."
TOO_MANY_SPENDS = "Too many spends just now. Wait a minute."


class GatherBody(BaseModel):
    # How much of the pending pile to bring in. None is none of it, which is a
    # gather of the fruit alone: a pile worth a year of calories is not
    # something to hand somebody by accident, and everything gathered starts a
    # seven day clock. The fruit is not asked about, because a harvest comes in
    # whole.
    manna: int | None = None


class FeedBody(BaseModel):
    planting_id: int
    # How many extra fruit to buy at once, at FEED_COST each. One by default,
    # because that is what the button on a plant does.
    bonus: int = 1


class MannaGiftBody(BaseModel):
    user_id: int
    amount: int


class FruitGiftBody(BaseModel):
    user_id: int
    fruit_id: int


def _spending(user: models.User) -> None:
    """The allowance every spend below shares. Four verbs, one budget, exactly
    as the satchel's four share theirs."""
    if throttle.harvest_spend_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_SPENDS)


def _state(db: Session, user: models.User) -> dict:
    """Everything the grove screen needs about a harvest, in one answer.

    Own account only. What somebody has gathered and what they have to give is
    theirs to know, exactly as their pending pile is: no friend payload carries
    a word of it.
    """
    row = progress.ensure_progress(db, user.id)
    borne = harvest.on_the_plant(db, user.id)
    basket = harvest.in_the_basket(db, user.id)
    return {
        # Gathered and spendable, then what is still waiting on the plants and
        # in the pile. Two numbers because they are two things: only the first
        # buys anything, and only the first is ever at risk.
        "manna": harvest.gathered_manna(db, user.id),
        "manna_pending": row.manna_pending,
        "borne": [harvest.serialize_batch(one) for one in borne],
        "basket": [harvest.serialize_batch(one) for one in basket],
        # Whether the one button has anything to do. Said by the server so the
        # screen never has to work out what counts as ready.
        "ready": bool(borne) or row.manna_pending > 0,
        # What a feeding costs and how much a plant can hold, so the button can
        # say the price rather than a copy of it being kept on the client.
        "feed_cost": FEED_COST,
        "feed_cap": FEED_MAX_BANKED,
        # How far the meter has come toward the next bearing, in converted
        # Miles, and how long a season is. Earned, like everything beside it.
        "season_mi": FRUIT_SEASON_MI,
        "season_progress_mi": round(row.fruit_progress_mi, 2),
    }


@router.get("/harvest")
def read_harvest(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    """What is on the plants, what is in the basket, and what there is to spend.

    Swept before it is read, like every other own screen, so a sync that landed
    a moment ago has already borne and anything gathered too long ago has
    already gone back to the soil.
    """
    if throttle.harvest_read_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, throttle.TOO_MANY_READS)
    progress.process_user(db, user.id)
    return _state(db, user)


@router.post("/harvest/gather")
def gather_all(
    body: GatherBody | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Bring in the harvest, and as much manna as was asked for.

    One button on one screen. The fruit comes in whole, because a harvest is a
    harvest; the manna comes in by the amount somebody names, because a pile
    built out of a year of calories is worth far more than a week of giving
    spends and everything gathered starts its seven days at once.

    Nothing is refused when there is nothing to bring in: the answer is that
    none of it moved, which is also what a second press a moment later gets.
    """
    _spending(user)
    row = progress.process_user(db, user.id)
    wanted = 0 if body is None or body.manna is None else body.manna
    if wanted < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That is not an amount of manna.")
    if wanted > row.manna_pending:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That is more manna than you have waiting."
        )
    taken = harvest.gather(db, row, security.now_utc(), wanted)
    db.commit()
    return {**_state(db, user), **taken}


@router.post("/harvest/feed")
def feed_plant(
    body: FeedBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Feed gathered manna to a grown plant, yours or a friend's.

    What it buys is fruit on that plant's next bearing and nothing else: not a
    mile of growth, not a level, not a chest (TWO-LANE LAW). It banks on the
    plant and is spent the moment the plant bears.

    A friend's plant is the same act with a name on it, and it is the one that
    pays renown. Your own is the quiet option, worth nothing to anybody's
    standing, because giving to yourself is not giving; it is here so somebody
    with no friends yet still has somewhere for their calories to go.
    """
    _spending(user)
    progress.process_user(db, user.id)
    planting = db.get(models.Planting, body.planting_id)
    own = planting is not None and planting.user_id == user.id
    if planting is None or (
        not own and not fellowship.are_friends(db, user.id, planting.user_id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_PLANT)
    if not grove.is_mature(planting):
        # Nothing bears before it is grown, so feeding one would be paying for
        # a harvest that cannot happen. Refused rather than banked.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That one is not grown yet.")
    if body.bonus < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A feeding is at least one fruit.")
    if planting.fed_bonus + body.bonus > FEED_MAX_BANKED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A plant holds {FEED_MAX_BANKED} extra fruit at most before it bears.",
        )
    cost = FEED_COST * body.bonus
    if not harvest.spend_manna(db, user.id, cost):
        # The one statement that reads the pile and takes from it, so two
        # requests cannot both spend the same manna.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_ENOUGH)

    now = security.now_utc()
    planting.fed_bonus += body.bonus
    earned = fellowship.feed_earns_renown(db, user.id, planting.user_id, now)
    db.add(
        models.PlantFeeding(
            from_user_id=user.id,
            to_user_id=planting.user_id,
            planting_id=planting.id,
            manna_spent=cost,
            bonus=body.bonus,
            created_at=now,
            earned_renown=earned,
        )
    )
    if earned:
        fellowship.pay_renown(db, user.id, RENOWN_FEED)
    db.commit()
    # A friend's plant comes back in the shape a friend is allowed to see, the
    # same way a pour answers.
    return grove.serialize_planting(planting) if own else grove.serialize_for_friend(planting)


@router.post("/harvest/manna", status_code=status.HTTP_201_CREATED)
def give_manna(
    body: MannaGiftBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Hand a friend raw manna out of your own gathered pile.

    It joins their pending pile rather than their gathered one, so it is safe
    until they gather it themselves: a gift must never arrive already ageing.
    They are told in their letter, which is where every gift in this app is
    attributed.
    """
    _spending(user)
    progress.process_user(db, user.id)
    if body.user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot give to yourself.")
    if not fellowship.are_friends(db, user.id, body.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_FRIEND)
    if body.amount < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A gift is at least 1 manna.")
    if not harvest.spend_manna(db, user.id, body.amount):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_ENOUGH)

    now = security.now_utc()
    earned = fellowship.manna_gift_earns_renown(db, user.id, body.user_id, now)
    db.add(
        models.MannaGift(
            from_user_id=user.id,
            to_user_id=body.user_id,
            amount=body.amount,
            created_at=now,
            earned_renown=earned,
        )
    )
    progress.ensure_progress(db, body.user_id).manna_pending += body.amount
    if earned:
        fellowship.pay_renown(db, user.id, RENOWN_MANNA_GIFT)
    db.commit()
    return {"amount": body.amount, **_state(db, user)}


@router.post("/harvest/fruit", status_code=status.HTTP_201_CREATED)
def give_fruit(
    body: FruitGiftBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Give a friend something out of your basket.

    The top of the giving ladder, and the only thing in the game that carries
    where it came from: the miles that grew it and the month it came in travel
    with it as a sentence, frozen at the moment of the gift.

    What it becomes on the other side is a keepsake and nothing else. It buys
    them nothing, feeds nothing, and spoils never; it is a record that somebody
    grew something and gave it away.
    """
    _spending(user)
    progress.process_user(db, user.id)
    if body.user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot give to yourself.")
    if not fellowship.are_friends(db, user.id, body.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_FRIEND)

    now = security.now_utc()
    # Claimed with a conditional update rather than by writing to a row read a
    # moment ago: two requests carrying the same batch would otherwise both go
    # on to mint a keepsake out of fruit that only exists once. Somebody else's
    # fruit, fruit still on the plant, and fruit already given or composted are
    # one answer, the way a spent satchel item is.
    claimed = db.execute(
        update(models.FruitBatch)
        .where(
            models.FruitBatch.id == body.fruit_id,
            models.FruitBatch.user_id == user.id,
            models.FruitBatch.gathered_at.is_not(None),
            models.FruitBatch.composted_at.is_(None),
            models.FruitBatch.given_at.is_(None),
        )
        .values(given_at=now, given_to_user_id=body.user_id)
    )
    if claimed.rowcount != 1:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_FRUIT)
    batch = db.get(models.FruitBatch, body.fruit_id)
    db.refresh(batch)

    earned = fellowship.fruit_gift_earns_renown(db, user.id, body.user_id, now)
    batch.earned_renown = earned
    db.add(
        models.FruitKeepsake(
            user_id=body.user_id,
            from_user_id=user.id,
            from_username=user.username,
            species=batch.species,
            golden=batch.golden,
            count=batch.count,
            provenance=harvest.provenance(batch),
            received_at=now,
        )
    )
    if earned:
        fellowship.pay_renown(db, user.id, RENOWN_FRUIT_GIFT)
    db.commit()
    return {"given": harvest.serialize_batch(batch), **_state(db, user)}


@router.get("/basket")
def read_basket(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> list[dict]:
    """Everything this account has ever been given, newest first.

    Own screen only, and permanent: nothing composts a keepsake and nothing
    spends one. It is on the You screen because that is where the things
    somebody has been given already live.
    """
    if throttle.harvest_read_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, throttle.TOO_MANY_READS)
    return [harvest.serialize_keepsake(row) for row in harvest.keepsakes(db, user.id)]
