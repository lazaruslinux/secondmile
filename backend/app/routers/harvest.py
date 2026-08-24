"""The harvest and the four things manna is spent on.

One button gathers the fruit, and everything else here is a way of spending the
bank: on your own grove quietly, or on somebody else's, which is the half that
pays. Manna never buys a mile, a level, a chest, growth or a medal, and no
endpoint in this file may ever be taught to (TWO-LANE LAW).

Every verb is friend-gated where it acts on somebody else, and a stranger's
plant, a stranger's account and a thing that never existed are all the same 404:
whose plot an id belongs to is not something to learn by asking.

Two of them are capped: one account may put only so much manna into one other
person inside the window, feeding and gifts counted together. Server side, where
every rule in this app lives.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import fellowship, grove, harvest, models, pets, progress, security, throttle
from app.config import (
    FEED_COST,
    FEED_MAX_BANKED,
    FRUIT_SEASON_MI,
    MANNA_TO_ONE_PERSON,
    RENOWN_FEED,
    RENOWN_FRUIT_GIFT,
    RENOWN_MANNA_GIFT,
)
from app.db import get_db

router = APIRouter(tags=["harvest"])

NO_SUCH_PLANT = "No such planting."
NO_SUCH_FRIEND = "No such friend."
NOT_ENOUGH = "You do not have enough manna for that."
# Said the same way at both verbs that spend fruit, because they are the same
# event to whoever met one: the basket does not hold that much.
NOT_ENOUGH_FRUIT = "You do not have that much fruit in your basket."
# Said the same way at both verbs it guards. No number of days and no countdown:
# it is a limit, not a timer.
TOO_MUCH_FOR_ONE = "That is more manna than you can give one person just now."
TOO_MANY_SPENDS = "Too many spends just now. Wait a minute."


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
    # How many fruit to hand over. Fruit is one number wherever anybody acts on
    # it: which species leave the basket is the oldest-first rule's business.
    count: int = 1


def _spending(user: models.User) -> None:
    """The allowance every spend below shares. Four verbs, one budget, exactly
    as the satchel's four share theirs."""
    if throttle.harvest_spend_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_SPENDS)


def _within_cap(db: Session, user_id: int, to_user_id: int, amount: int) -> None:
    """Refuse a spend that would put more than the window allows into one person.

    Checked before anything is taken, so a refusal costs nothing. Your own grove
    never asks: a plant holds FEED_MAX_BANKED and that is its own cap.

    The answer says no and says nothing else. Nobody is told how much is left or
    when it comes back, because a countdown is exactly what this is not.
    """
    if to_user_id == user_id:
        return
    already = harvest.given_to_lately(db, user_id, to_user_id, security.now_utc())
    if already + amount > MANNA_TO_ONE_PERSON:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, TOO_MUCH_FOR_ONE)


def _state(db: Session, user: models.User) -> dict:
    """Everything the grove screen needs about a harvest, in one answer.

    Own account only. What somebody has banked and what they have to give is
    theirs to know: no friend payload carries a word of it.
    """
    row = progress.ensure_progress(db, user.id)
    borne = harvest.on_the_plant(db, user.id)
    basket = harvest.in_the_basket(db, user.id)
    return {
        # The bank. One number, because there is one: manna is earned, kept and
        # spent, and none of it is ever waiting for anything.
        "manna": row.manna,
        "borne": [harvest.serialize_batch(one) for one in borne],
        "basket": [harvest.serialize_batch(one) for one in basket],
        # Whether the one button has anything to do. Said by the server so the
        # screen never has to work out what counts as ready.
        "ready": bool(borne),
        # What a feeding costs and how much a plant can hold, so the button can
        # say the price rather than a copy of it being kept on the client.
        "feed_cost": FEED_COST,
        "feed_cap": FEED_MAX_BANKED,
        # How far the meter has come toward the next bearing, in converted
        # Miles, and how long a season is. Earned, like everything beside it.
        "season_mi": FRUIT_SEASON_MI,
        "season_progress_mi": round(row.fruit_progress_mi, 2),
        # What lives in the grove. Here rather than in a payload of its own
        # because the screen that draws them already reads this one, and what a
        # pet is fed comes out of the basket two lines above it. Presence only:
        # nothing in this list is spent, earned or worth anything.
        "pets": [pets.serialize(one) for one in pets.owned(db, user.id)],
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
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Bring in the harvest.

    One button on one screen, and the fruit comes in whole, because a harvest is
    a harvest. Manna is not part of it: it is banked as the calories are
    credited and is never gathered.

    Nothing is refused when there is nothing to bring in: the answer is that
    none of it moved, which is also what a second press a moment later gets.

    A stray may be drawn to the grove afterwards, which is the one thing this
    button does besides bring the fruit in. It is presence and nothing else, so
    nothing about the harvest above it changes by a fruit either way.
    """
    _spending(user)
    progress.process_user(db, user.id)
    now = security.now_utc()
    taken = harvest.gather(db, user.id, now)
    pets.maybe_arrive(db, user.id, now)
    db.commit()
    return {**_state(db, user), **taken}


@router.post("/harvest/feed")
def feed_plant(
    body: FeedBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Feed manna to a grown plant, yours or a friend's.

    What it buys is fruit on that plant's next bearing and nothing else: not a
    mile of growth, not a level, not a chest (TWO-LANE LAW). It banks on the
    plant and is spent the moment the plant bears.

    A friend's plant is the same act with a name on it, and it is the one that
    pays renown and the one the window's cap counts. Your own is the quiet
    option, worth nothing to anybody's standing and capped only by what a plant
    will hold, because giving to yourself is not giving; it is here so somebody
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
    _within_cap(db, user.id, planting.user_id, cost)
    if not harvest.spend_manna(db, user.id, cost):
        # The one statement that reads the bank and takes from it, so two
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
    """Hand a friend raw manna out of your own bank.

    It joins theirs and is spendable the moment it lands, because manna is a
    bank on both sides. They are told in their letter, which is where every gift
    in this app is attributed.
    """
    _spending(user)
    progress.process_user(db, user.id)
    if body.user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot give to yourself.")
    if not fellowship.are_friends(db, user.id, body.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_FRIEND)
    if body.amount < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A gift is at least 1 manna.")
    _within_cap(db, user.id, body.user_id, body.amount)
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
    progress.ensure_progress(db, body.user_id).manna += body.amount
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
    """Give a friend fruit out of your basket.

    The top of the giving ladder, and the only thing in the game that carries
    where it came from: the miles that grew it and the month it came in travel
    with it as a sentence, frozen at the moment of the gift.

    An amount rather than a batch. The oldest fruit goes first, exactly as it
    does when a pet is fed, so a gift never costs somebody the fruit they were
    about to lose anyway and nobody is ever asked which species to part with.
    What it says about itself is composed from what actually left: one species
    is named, a handful of several is fruit.

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
    if body.count < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A gift is at least one fruit.")
    basket = harvest.oldest_first(db, user.id)
    if body.count > sum(row.count for row in basket):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_ENOUGH_FRUIT)
    taken = harvest.take(db, basket, body.count)
    if not taken:
        # The basket moved between the check above and the taking. Two requests
        # racing cannot both spend the same fruit, and this is the one that lost.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_ENOUGH_FRUIT)

    now = security.now_utc()
    species_id, golden = harvest.gift_kind(taken)
    told = harvest.gift_provenance(taken)
    earned = fellowship.fruit_gift_earns_renown(db, user.id, body.user_id, now)
    # One row per gift however many batches it came off, so everything that adds
    # renown up counts one gift once.
    db.add(
        models.FruitGift(
            from_user_id=user.id,
            to_user_id=body.user_id,
            count=body.count,
            created_at=now,
            earned_renown=earned,
        )
    )
    db.add(
        models.FruitKeepsake(
            user_id=body.user_id,
            from_user_id=user.id,
            from_username=user.username,
            species=species_id,
            golden=golden,
            count=body.count,
            provenance=told,
            received_at=now,
        )
    )
    if earned:
        fellowship.pay_renown(db, user.id, RENOWN_FRUIT_GIFT)
    db.commit()
    return {
        "given": {
            "count": body.count,
            "name": harvest.fruit_name(species_id, golden),
            "label": harvest.fruit_words(body.count, species_id, golden),
            "golden": golden,
            "provenance": told,
        },
        **_state(db, user),
    }


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
