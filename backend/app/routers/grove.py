"""The satchel and the plot: four items, four verbs, and nothing to look at.

Every item a chest gives is a tool. A seed is planted, water is poured onto one
planting, oil is spent on a friend, and a wish is spent on whichever seed is
missing. There is no fifth thing and no way to merely hold one of them, which is
why every endpoint here is a verb and none of them is a collection.

Oil is the quiet one. Spending it says nothing at the moment it is spent: no
notification and no feed event. It surfaces on the receiving side as a name
against the chest it will lift, and again in the letter once that chest lands.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import fellowship, grove, models, progress, security, species, throttle
from app.config import MAX_PENDING_ANOINTINGS
from app.db import get_db

router = APIRouter(tags=["grove"])

NO_SUCH_ITEM = "No such item."
TOO_MANY_SPENDS = "Too many spends just now. Wait a minute."


class PourBody(BaseModel):
    planting_id: int


class AnointBody(BaseModel):
    user_id: int


class ChooseBody(BaseModel):
    # Optional, because a plot with all twelve in it has nothing left to name.
    species: str | None = None


def _item(
    db: Session, user: models.User, item_id: int, kind: str
) -> models.SatchelItem:
    """One unspent item of the kind the verb needs.

    A missing item, somebody else's, and one already spent are all the same
    404: the satchel of another account is not a thing to count by walking ids,
    and an item that has been used is no longer in any satchel at all.

    The four verbs share one allowance, checked here because here is the one
    line all four of them pass through.
    """
    if throttle.satchel_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_SPENDS)
    row = db.get(models.SatchelItem, item_id)
    if row is None or row.user_id != user.id or row.used_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_ITEM)
    if row.kind != kind:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That item cannot be used here."
        )
    return row


def _spend(db: Session, item: models.SatchelItem, moment: dt.datetime) -> None:
    """Take one item out of the satchel, or answer the way a spent one does.

    The check in _item reads; this writes, and only the write settles it. Two
    requests carrying the same item id can both pass the read, and without this
    they would both go on to plant a seed or pour a water that only exists once.
    The condition is the same one the read made, so the loser is told exactly
    what it would have been told a moment later: there is no such item, because
    by then there is not.

    Every verb below claims before it does anything, so nothing is ever created
    on behalf of an item somebody else already spent.
    """
    claimed = db.execute(
        update(models.SatchelItem)
        .where(models.SatchelItem.id == item.id, models.SatchelItem.used_at.is_(None))
        .values(used_at=moment)
    )
    if claimed.rowcount != 1:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_ITEM)


@router.get("/satchel")
def read_satchel(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> list[dict]:
    """Everything waiting to be used, oldest first. Spent items are gone from
    here the moment they are spent."""
    progress.process_user(db, user.id)
    rows = db.execute(
        select(models.SatchelItem)
        .where(
            models.SatchelItem.user_id == user.id, models.SatchelItem.used_at.is_(None)
        )
        .order_by(models.SatchelItem.id)
    ).scalars()
    return [grove.serialize_item(row) for row in rows]


@router.post("/satchel/{item_id}/plant", status_code=status.HTTP_201_CREATED)
def plant_seed(
    item_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Put a seed in the ground. It grows from then on by itself."""
    item = _item(db, user, item_id, "seed")
    now = security.now_utc()
    _spend(db, item, now)
    planting = grove.plant(db, user.id, item, now)
    db.commit()
    return grove.serialize_planting(planting)


@router.post("/satchel/{item_id}/choose", status_code=status.HTTP_201_CREATED)
def choose_seed(
    item_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
    body: ChooseBody | None = None,
) -> dict:
    """Spend a wish on whichever seed you name, and hold it a moment later.

    The wish is the only item whose verb takes an answer from the player rather
    than a target: the rest of the chest decides what you get, and this one asks.
    What comes back is the seed itself, waiting in the satchel to be planted like
    any other.

    A plot with all twelve in it has nothing left to name, and there the wish
    pours water rather than becoming an item that can never be spent.
    """
    item = _item(db, user, item_id, "wish")
    held = grove.held_species(db, user.id)
    wanted = None if body is None else body.species
    if not species.missing(held):
        # Whatever was named is moot: the plot already holds all of it, so the
        # wish falls to water rather than to nothing.
        wanted = None
    elif wanted is None or wanted not in species.ROLLABLE:
        # The mustard tree answers here alongside everything that is not a
        # species at all. It is given once and is in no bag anything reaches
        # into, a wish included.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No such seed to wish for.")
    elif wanted in held:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You already have that one. Wish for something else."
        )
    now = security.now_utc()
    _spend(db, item, now)
    made = grove.spend_wish(db, item, wanted, now)
    db.commit()
    return grove.serialize_item(made)


@router.post("/satchel/{item_id}/pour")
def pour_water(
    item_id: int,
    body: PourBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Empty one water onto one planting, which is worth ten Miles of growth.

    Your own, or a friend's. Watering somebody else's plot is worth renown to
    whoever did it and nothing at all to the plot's owner beyond the growth,
    which is the whole shape of this game: giving is the thing that pays.
    """
    item = _item(db, user, item_id, "water")
    planting = db.get(models.Planting, body.planting_id)
    own = planting is not None and planting.user_id == user.id
    if planting is None or (
        not own and not fellowship.are_friends(db, user.id, planting.user_id)
    ):
        # A stranger's planting and one that never existed answer the same
        # way: whose plot an id belongs to is not a thing to learn by asking.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such planting.")
    if grove.is_gilded(planting):
        # Water helps until there are no levels left. Refusing rather than
        # wasting it is the whole point of saying so.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That one is fully grown."
        )
    now = security.now_utc()
    # Claimed before the water lands, so a planting cannot take two levels of
    # growth out of one item that two requests both read as unspent.
    _spend(db, item, now)
    # Whoever poured is written down beside the growth, in this transaction, so
    # a later rebuild can put the water back where it went.
    grove.pour(db, user.id, planting, now)
    if not own:
        fellowship.spend_on(db, item, planting.user_id, "water", now)
    db.commit()
    # A friend's planting comes back in the shape a friend is allowed to see.
    return grove.serialize_planting(planting) if own else grove.serialize_for_friend(planting)


@router.post("/satchel/{item_id}/anoint", status_code=status.HTTP_204_NO_CONTENT)
def anoint_friend(
    item_id: int,
    body: AnointBody,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Spend oil on a friend, and lift one of the chests their own miles bring.

    A chest is normally its own step of the ladder, and one time in five the
    step above. A gift promises that step instead of risking it, on the next
    chest with room for one: the miles are still theirs, and what falls out of
    them is better for somebody having given.

    Nothing is said as it happens. The receiving side reads it on their own
    screen, as a name against the chest it is waiting on, and again in the
    letter once that chest has landed.
    """
    item = _item(db, user, item_id, "oil")
    if body.user_id == user.id:
        # The one refusal worth making out loud: it leaks nothing, and oil is
        # for somebody else by definition.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot anoint yourself.")
    if not fellowship.are_friends(db, user.id, body.user_id):
        # The same answer for a stranger and for an account that does not
        # exist. Which ids are real is not a question this endpoint answers.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such friend.")
    if grove.anointing_waits(db, user.id, body.user_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have a potion waiting on that friend."
        )
    if len(grove.pending_anointings(db, body.user_id)) >= MAX_PENDING_ANOINTINGS:
        # How much of one walker's coming ladder may be lifted before they have
        # run any of it. Refused rather than swallowed: the potion is a legendary
        # item and spending it on nothing would be the worse answer by far. Counted
        # here and not in an index, so two givers racing can leave a fourth
        # waiting; the miles spend them all the same, one chest each.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "They already have all the gifts they can hold. Try again once they have run.",
        )

    now = security.now_utc()
    # Claimed first, so two requests carrying the same oil cannot both reach the
    # insert below. The rollback on the conflicting insert takes this back with
    # it, which is what leaves the oil unspent when the gift is refused.
    _spend(db, item, now)
    try:
        with db.begin_nested():
            db.add(
                models.Anointing(
                    from_user_id=user.id,
                    to_user_id=body.user_id,
                    created_at=now,
                    consumed_at=None,
                    consumed_chest_id=None,
                )
            )
            db.flush()
    except IntegrityError:
        # Two of these racing each other. The index settles it and the second
        # one is the conflict it would have been a moment later.
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have a potion waiting on that friend."
        ) from None
    # Renown to the giver, now, quietly. The recipient's side of this stays
    # silent until the chest lands: nothing they can read has changed.
    fellowship.spend_on(db, item, body.user_id, "oil", now)
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/grove")
def read_grove(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> list[dict]:
    """Everything growing in your plot, oldest first. Swept before it is read,
    so a sync that landed a moment ago has already watered it."""
    progress.process_user(db, user.id)
    rows = db.execute(
        select(models.Planting)
        .where(models.Planting.user_id == user.id)
        .order_by(models.Planting.id)
    ).scalars()
    return [grove.serialize_planting(row) for row in rows]


@router.get("/grove/{user_id}")
def read_friend_grove(
    user_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """A friend's plot: what is growing in it and how grown, and nothing else.

    No miles, no dates, no numbers of any kind. A garden is something you see
    over the fence, not a page of somebody's statistics.
    """
    if user_id != user.id and not fellowship.are_friends(db, user.id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such friend.")
    rows = db.execute(
        select(models.Planting)
        .where(models.Planting.user_id == user_id)
        .order_by(models.Planting.id)
    ).scalars()
    return [grove.serialize_for_friend(row) for row in rows]


@router.get("/species")
def read_species(_user: models.User = Depends(security.current_user)) -> dict:
    """The twelve a seed can be, in catalogue order, and what a wish is called.

    Authored content and nothing else: no account is read, no table is touched,
    and everybody gets the same answer. It is served rather than written down a
    second time on the client because a catalogue kept in two places disagrees
    with itself the first time a species is renamed, and the client needs the
    whole of it to offer a wish something nobody owns yet.

    The mustard tree is not in here. This is the bag a chest and a wish reach
    into, and that one is given rather than rolled; the plot it is planted in is
    what names it. Behind a session like everything else in this file, which
    costs a catalogue nothing and keeps one rule about who may read this app.
    """
    return {
        "species": [
            {
                "id": row.id,
                "seed_name": row.seed_name,
                "plant_name": row.plant_name,
                "rarity": row.rarity,
            }
            for row in (species.BY_ID[species_id] for species_id in species.ROLLABLE)
        ],
        "wish_name": species.WISH_NAME,
    }
