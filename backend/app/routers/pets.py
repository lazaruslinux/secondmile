"""The two things anybody does to a pet: feed it, and give it a name.

Own rows only. There is no verb here that reaches anybody else's grove, because
a pet is not a thing to be given, spent or poured into; a friend sees that one is
there and nothing more.

Nothing in this file touches manna, experience, a level, a chest, growth, yield,
a medal or renown, and no release may teach it to. Feeding takes fruit out of
the basket and puts nothing anywhere else.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import harvest, models, pets, progress, security, throttle
from app.config import PET_STAGE_FRUIT
from app.db import get_db
from app.routers.harvest import NOT_ENOUGH_FRUIT, TOO_MANY_SPENDS

router = APIRouter(tags=["pets"])

NO_PET = "Nothing in your grove is growing just now."
NO_SUCH_PET = "No such pet."
TOO_MUCH_FRUIT = "That is more fruit than it has room for."


class FeedBody(BaseModel):
    # How many fruit to feed at once. One by default, which is the smallest
    # thing the card offers.
    count: int = 1


class NameBody(BaseModel):
    # Blank takes the name back off, so an empty box and no field are one
    # answer rather than two.
    name: str | None = None


def _spending(user: models.User) -> None:
    """The harvest's own allowance. Feeding a pet is fruit out of the basket,
    so it spends from the budget the four harvest verbs already share."""
    if throttle.harvest_spend_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_SPENDS)


@router.post("/pets/feed")
def feed_pet(
    body: FeedBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Feed fruit from the basket to whichever pet is still growing.

    Any fruit at all, and every one of them is worth exactly one: what it grew
    on and whether it is golden change the word on the screen and nothing else.

    The basket is checked before anything is taken, so a request for more than
    is there costs nothing rather than emptying it part way. A feeding larger
    than what is left to grow is refused for the same reason: the fruit would go
    in and buy nothing, and there is no verb here for wasting it.
    """
    _spending(user)
    progress.process_user(db, user.id)
    pet = pets.ungrown(db, user.id)
    if pet is None:
        # A grown pet and a grove that has never been found by one are the same
        # answer: there is nothing here to feed.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NO_PET)
    if body.count < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A feeding is at least one fruit.")
    # Feeding past the last crossing used to swallow the remainder whole: "feed
    # all 47" on a pet owing 20 burned the other 27 for nothing. Refused at the
    # door now (his rule 2026-08-29), so the card's own Max row is the most
    # anybody can hand over in one go.
    room = PET_STAGE_FRUIT[-1] - pet.fruit_fed
    if body.count > room:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, TOO_MUCH_FRUIT)
    basket = harvest.oldest_first(db, user.id)
    if body.count > sum(row.count for row in basket):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_ENOUGH_FRUIT)
    taken = harvest.take(db, basket, body.count)
    if not taken:
        # The basket moved between the check above and the taking, which is the
        # same answer as not having had it in the first place.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_ENOUGH_FRUIT)

    pets.feed(db, pet, body.count, security.now_utc())
    golden = any(row.golden for row, _ in taken)
    db.commit()
    # The golden flag buys nothing and is not a number: it is there so the card
    # can say a different sentence about the same mouthful.
    return {"pet": pets.serialize(pet), "golden": golden}


@router.post("/pets/{pet_id}/name")
def name_pet(
    pet_id: int,
    body: NameBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Name a pet, or take its name back off. Yours at any stage.

    Somebody else's pet and one that never existed are the same 404, which is
    the answer every row in this app that belongs to one person gives.
    """
    if throttle.profile_edit_limiter.hit(throttle.user_key(user)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many edits just now. Wait a minute."
        )
    pet = db.get(models.Pet, pet_id)
    if pet is None or pet.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_PET)
    pet.name = pets.clean_name(body.name)
    db.commit()
    return pets.serialize(pet)
