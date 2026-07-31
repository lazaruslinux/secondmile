"""Chests, the card album, and the accolades earned along the roads."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import journey as engine
from app import models, security, world
from app.db import get_db

router = APIRouter(tags=["cards"])


def _card(card: world.Card) -> dict:
    """A card the player owns, with everything on the plate."""
    return {
        "id": card.id,
        "set_id": card.set_id,
        "set_name": world.CARD_SETS[card.set_id].name,
        "number": card.number,
        "name": card.name,
        "rarity": card.rarity,
        "flavor": card.flavor,
    }


@router.get("/chests")
def list_chests(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> list[dict]:
    """Every chest still closed, oldest first.

    The card inside is not in this response. It is decided and stored at the
    moment the chest drops, but the reveal belongs to opening it, and an API
    that answers the question early takes the only surprise the game has.
    """
    rows = db.execute(
        select(models.Chest)
        .where(models.Chest.user_id == user.id, models.Chest.opened_at.is_(None))
        .order_by(models.Chest.id)
    ).scalars()
    return [
        {
            "id": row.id,
            "dropped_at": row.dropped_at.isoformat(),
            "set_id": world.CARDS[row.card_id].set_id,
            "set_name": world.CARD_SETS[world.CARDS[row.card_id].set_id].name,
        }
        for row in rows
    ]


@router.post("/chests/{chest_id}/open")
def open_chest(
    chest_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Reveal what a chest was carrying and add it to the album."""
    chest = db.get(models.Chest, chest_id)
    if chest is None or chest.user_id != user.id:
        # One answer for a chest that never existed and one that belongs to
        # somebody else. Telling the two apart would let anyone count another
        # account's chests by walking the ids.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such chest.")
    if chest.opened_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That chest is already open.")

    card = world.CARDS[chest.card_id]
    now = security.now_utc()
    chest.opened_at = now
    owned = db.get(models.UserCard, (user.id, card.id))
    if owned is None:
        owned = models.UserCard(
            user_id=user.id, card_id=card.id, count=1, first_found_at=now
        )
        db.add(owned)
    else:
        owned.count += 1
    db.commit()
    return {
        "card": _card(card),
        # Duplicates are meant to be kept and given away rather than hoarded,
        # so the client is told plainly rather than left to work it out.
        "duplicate": owned.count > 1,
        "count": owned.count,
    }


@router.get("/album")
def read_album(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    """The field guide: every set, every plate, owned or not.

    An unowned plate carries its number and its rarity and nothing else. The
    name and the line of text under it are the reward for finding the card,
    and an album that listed them all up front would be a shopping list.
    """
    held = {
        row.card_id: row
        for row in db.execute(
            select(models.UserCard).where(models.UserCard.user_id == user.id)
        ).scalars()
    }
    sets = []
    for card_set in world.CARD_SETS.values():
        cards = world.CARDS_BY_SET[card_set.id]
        plates = []
        for card in cards:
            row = held.get(card.id)
            if row is None:
                plates.append({"number": card.number, "rarity": card.rarity, "owned": False})
                continue
            plates.append(
                {
                    **_card(card),
                    "owned": True,
                    "count": row.count,
                    "first_found_at": row.first_found_at.isoformat(),
                }
            )
        sets.append(
            {
                "id": card_set.id,
                "name": card_set.name,
                "size": len(cards),
                "owned": sum(1 for card in cards if card.id in held),
                "cards": plates,
            }
        )
    return {"sets": sets}


@router.get("/accolades")
def read_accolades(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> list[dict]:
    """The permanent marks of places the marker has passed, oldest first."""
    # The sweep runs here because an accolade is earned by movement, and the
    # Almanac showing a stale list after a sync would be its own small lie.
    engine.process_user(db, user.id)
    rows = db.execute(
        select(models.UserAccolade)
        .where(models.UserAccolade.user_id == user.id)
        .order_by(models.UserAccolade.earned_at, models.UserAccolade.accolade_id)
    ).scalars()
    earned = []
    for row in rows:
        milestone = world.ACCOLADES.get(row.accolade_id)
        if milestone is None:
            # An accolade the current release no longer defines. Skipped
            # rather than shown as a blank, and left in the table so that
            # reinstating it gives the player back what they earned.
            continue
        earned.append(
            {
                "id": milestone.id,
                "name": milestone.name,
                "detail": milestone.detail,
                "earned_at": row.earned_at.isoformat(),
            }
        )
    return earned
