"""The satchel and the plot: four items, four verbs, and nothing to look at.

Every item a chest gives is a tool. A seed is planted, water is poured onto one
planting, oil is spent on a friend, and a wish is spent on whichever seed is
missing. There is no fifth thing and no way to merely hold one of them, which is
why every endpoint here is a verb and none of them is a collection.

Oil is the quiet one. Spending it says nothing to the person it is spent on:
no notification, no feed event, and nothing in any response they can read. It
surfaces once, as a chest, in their letter.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import fellowship, grove, models, progress, security, species, throttle
from app.db import get_db

router = APIRouter(tags=["grove"])


class PourBody(BaseModel):
    planting_id: int


class AnointBody(BaseModel):
    user_id: int


class ChooseBody(BaseModel):
    # Optional, because a plot with all twelve in it has nothing left to name.
    species: str | None = None


def _item(db: Session, user_id: int, item_id: int, kind: str) -> models.SatchelItem:
    """One unspent item of the kind the verb needs.

    A missing item, somebody else's, and one already spent are all the same
    404: the satchel of another account is not a thing to count by walking ids,
    and an item that has been used is no longer in any satchel at all.
    """
    row = db.get(models.SatchelItem, item_id)
    if row is None or row.user_id != user_id or row.used_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such item.")
    if row.kind != kind:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"That is not {'an' if kind == 'oil' else 'a'} {kind}."
        )
    return row


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
    item = _item(db, user.id, item_id, "seed")
    planting = grove.plant(db, user.id, item, security.now_utc())
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
    item = _item(db, user.id, item_id, "wish")
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
    made = grove.spend_wish(db, item, wanted, security.now_utc())
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
    item = _item(db, user.id, item_id, "water")
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
            status.HTTP_400_BAD_REQUEST, "That one is fully grown. There is nothing left to grow."
        )
    now = security.now_utc()
    grove.pour(planting, now)
    if own:
        item.used_at = now
    else:
        fellowship.spend_on(db, item, planting.user_id, "water", now)
    db.commit()
    # A friend's planting comes back in the shape a friend is allowed to see.
    return grove.serialize_planting(planting) if own else grove.serialize_for_friend(planting)


@router.post("/satchel/{item_id}/anoint", status_code=status.HTTP_204_NO_CONTENT)
def anoint_friend(
    item_id: int,
    body: AnointBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Spend oil on a friend, and say nothing to them about it.

    Their next credited workout brings them a chest they did not earn. Until
    then there is nothing to see, on either side: no notification goes out, no
    feed event is written, and no response of theirs changes. The letter is
    where it finally says who it came from.
    """
    if throttle.encourage_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many. Wait a minute.")
    item = _item(db, user.id, item_id, "oil")
    if body.user_id == user.id:
        # The one refusal worth making out loud: it leaks nothing, and oil is
        # for somebody else by definition.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Oil is for somebody else.")
    if not fellowship.are_friends(db, user.id, body.user_id):
        # The same answer for a stranger and for an account that does not
        # exist. Which ids are real is not a question this endpoint answers.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such friend.")
    if grove.anointing_waits(db, user.id, body.user_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have oil waiting on that friend."
        )

    now = security.now_utc()
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
            status.HTTP_409_CONFLICT, "You already have oil waiting on that friend."
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
