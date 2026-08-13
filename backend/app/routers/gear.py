"""Gear: recording a pair of shoes, and what happens to it afterwards.

Own gear only, everywhere. There is no endpoint here that reads or writes
anybody else's: a friend sees gear on their friend's profile, which is served by
the profile router, and nothing in this file takes an account id.

Every write answers with the whole list, so the screen that sent one redraws
from the server's word rather than from what it just sent.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session

from app import gear, models, security, throttle
from app.db import get_db

router = APIRouter(prefix="/gear", tags=["gear"])

NO_SUCH_GEAR = "No such gear."
# Refused rather than cascaded: deleting a pair that is on activities would
# quietly change what those activities say happened.
STILL_WORN = "Those are on activities you have recorded. Retire them instead."


class GearBody(BaseModel):
    """A new pair, or a patch to one.

    Every field is optional so one panel can save a whole pair and a single
    change alike; which of them were sent is read from the model's field set,
    the way every other patch in this app reads it. Creating checks that the
    four that make a pair are there.
    """

    style: str | None = None
    brand: str | None = None
    model: str | None = None
    nickname: str | None = None
    size: float | None = None
    width: str | None = None
    starting_mi: float | None = None
    replace_around_mi: float | None = None


def _writing(user: models.User) -> None:
    """The allowance every write here shares. One budget for the lot: they are
    a handful of verbs on one small list."""
    if throttle.gear_limiter.hit(throttle.user_key(user)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many changes just now. Wait a minute."
        )


def _own(db: Session, gear_id: int, user_id: int) -> models.Gear:
    """One of your own pairs, or the same 404 a pair that does not exist gets."""
    row = db.get(models.Gear, gear_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_SUCH_GEAR)
    return row


def _text(sent: str | None, limit: int, what: str) -> str:
    cleaned = (sent or "").strip()
    if not cleaned:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{what} is needed.")
    if len(cleaned) > limit:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{what} must be at most {limit} characters."
        )
    return cleaned


def _nickname(sent: str | None) -> str | None:
    """Optional, and an empty box clears it: a name somebody deleted and one
    they never gave are the same thing."""
    cleaned = (sent or "").strip()
    if len(cleaned) > gear.MAX_NICKNAME:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A nickname must be at most {gear.MAX_NICKNAME} characters.",
        )
    return cleaned or None


def _miles(sent: float | None, what: str) -> float:
    if sent is None or sent < 0 or sent > gear.MAX_MILES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{what} must be a number of miles.")
    return float(sent)


def _style(sent: str | None) -> str:
    if sent not in gear.STYLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose men's or women's.")
    return sent


def _size(style: str, sent: float | None) -> float:
    if sent is None or not gear.is_size(style, sent):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That is not a size we offer.")
    return float(sent)


def _width(style: str, sent: str | None) -> str:
    # An unsent width is the standard one, because that is what the picker opens
    # on and what almost everybody is wearing.
    if sent is None:
        return gear.DEFAULT_WIDTH[style]
    if not gear.is_width(style, sent):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That is not a width we offer.")
    return sent


def _listed(db: Session, user_id: int) -> list[dict]:
    return gear.gear_list(db, user_id, own=True)


@router.post("", status_code=status.HTTP_201_CREATED)
def add_gear(
    body: GearBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """Record a pair of shoes."""
    _writing(user)
    style = _style(body.style)
    row = models.Gear(
        user_id=user.id,
        kind=gear.SHOES,
        style=style,
        brand=_text(body.brand, gear.MAX_BRAND, "A brand"),
        model=_text(body.model, gear.MAX_MODEL, "A model"),
        nickname=_nickname(body.nickname),
        size=_size(style, body.size),
        width=_width(style, body.width),
        # A pair recorded without one starts at nothing, which is what a new
        # pair out of the box is.
        starting_mi=_miles(body.starting_mi or 0.0, "Starting miles"),
        replace_around_mi=(
            None
            if body.replace_around_mi is None
            else _miles(body.replace_around_mi, "A replacement mileage")
        ),
        is_default=False,
        created_at=security.now_utc(),
    )
    db.add(row)
    db.commit()
    return _listed(db, user.id)


@router.patch("/{gear_id}")
def edit_gear(
    gear_id: int,
    body: GearBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """Change what a pair says about itself.

    The style is what the size and the width are offered against, so a style
    that moves takes both with it: the pair is re-checked as a whole rather than
    field by field, which is what stops a men's 9 2E becoming a women's one
    nobody could have chosen from the form.
    """
    _writing(user)
    row = _own(db, gear_id, user.id)
    style = _style(body.style) if "style" in body.model_fields_set else row.style
    size = _size(style, body.size if "size" in body.model_fields_set else row.size)
    width = (
        _width(style, body.width)
        if "width" in body.model_fields_set
        else (row.width if gear.is_width(style, row.width) else gear.DEFAULT_WIDTH[style])
    )
    if "brand" in body.model_fields_set:
        row.brand = _text(body.brand, gear.MAX_BRAND, "A brand")
    if "model" in body.model_fields_set:
        row.model = _text(body.model, gear.MAX_MODEL, "A model")
    if "nickname" in body.model_fields_set:
        row.nickname = _nickname(body.nickname)
    if "starting_mi" in body.model_fields_set:
        row.starting_mi = _miles(body.starting_mi, "Starting miles")
    if "replace_around_mi" in body.model_fields_set:
        row.replace_around_mi = (
            None
            if body.replace_around_mi is None
            else _miles(body.replace_around_mi, "A replacement mileage")
        )
    row.style = style
    row.size = size
    row.width = width
    db.commit()
    return _listed(db, user.id)


@router.post("/{gear_id}/default")
def make_default(
    gear_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """Make one pair the one new walks and runs are recorded in.

    At most one per account, which is what the first statement enforces: every
    other pair is cleared before this one is set, so two rows can never both
    claim it.
    """
    _writing(user)
    row = _own(db, gear_id, user.id)
    if row.retired_at is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Those are retired. Un-retire them first."
        )
    db.execute(
        update(models.Gear)
        .where(models.Gear.user_id == user.id, models.Gear.id != row.id)
        .values(is_default=False)
    )
    row.is_default = True
    db.commit()
    return _listed(db, user.id)


@router.post("/{gear_id}/retire")
def retire_gear(
    gear_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """Put a pair away. It keeps its miles and stays on the activities it is
    already on, and nothing new is recorded in it."""
    _writing(user)
    row = _own(db, gear_id, user.id)
    if row.retired_at is None:
        gear.retire(row, security.now_utc())
        db.commit()
    return _listed(db, user.id)


@router.post("/{gear_id}/unretire")
def unretire_gear(
    gear_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """Take a pair back out of retirement. It is not made the default again:
    that is a separate decision, and it was cleared when they were put away."""
    _writing(user)
    row = _own(db, gear_id, user.id)
    row.retired_at = None
    db.commit()
    return _listed(db, user.id)


@router.delete("/{gear_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gear(
    gear_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Remove a pair that was never worn.

    Only that pair. Anything on an activity is refused in a plain sentence and
    retired instead: the alternative is a delete that rewrites what a workout
    says it was done in.
    """
    _writing(user)
    row = _own(db, gear_id, user.id)
    if gear.in_use(db, row.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, STILL_WORN)
    db.delete(row)
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
