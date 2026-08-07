"""Chests, what comes out of them, and the recap of everything that happened while away."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import achievements, fellowship, grove, models, progress, security
from app.activity import converted_miles
from app.db import get_db

router = APIRouter(tags=["chests"])

# The recap is a story, not a feed. Anything past this many pending chests is
# almost certainly a rebuild replaying months of history, and nobody opens three
# hundred of them in one sitting; the rest are still there, and still waiting.
MAX_RECAP = 200


def _chest(row: models.Chest) -> dict:
    """A closed chest, saying which step of the ladder dropped it and nothing
    more. What is inside is rolled when it is opened.

    tier is the name to print; tier_id is the stable one, which is what the
    odds are keyed on and what the column holds.
    """
    tier_id, tier_name = progress.tier_of(row)
    return {
        "id": row.id,
        "dropped_at": row.dropped_at.isoformat(),
        "tier": tier_name,
        "tier_id": tier_id,
    }


def _pending(db: Session, user_id: int, limit: int | None = None) -> list[models.Chest]:
    stmt = (
        select(models.Chest)
        .where(models.Chest.user_id == user_id, models.Chest.opened_at.is_(None))
        .order_by(models.Chest.id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars())


@router.get("/chests")
def list_chests(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> list[dict]:
    """Every chest still closed, oldest first.

    A chest that came from somebody's oil looks exactly like one the miles
    earned. It is told apart in the letter and nowhere else, because being
    surprised by it is the whole of what was given.
    """
    progress.process_user(db, user.id)
    return [_chest(row) for row in _pending(db, user.id)]


@router.post("/chests/{chest_id}/open")
def open_chest(
    chest_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Open a chest and put what was in it into the satchel.

    The answer is the item itself, in the shape the satchel lists it in, with
    the chest's tier alongside so the moment can be named. One shape for a
    thing that is one thing.
    """
    chest = db.get(models.Chest, chest_id)
    if chest is None or chest.user_id != user.id:
        # One answer for a chest that never existed and one that belongs to
        # somebody else. Telling the two apart would let anyone count another
        # account's chests by walking the ids.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such chest.")
    if chest.opened_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That chest is already open.")

    tier_id, tier_name = progress.tier_of(chest)
    item = progress.open_chest(db, user.id, chest)
    db.commit()
    return {**grove.serialize_item(item), "tier": tier_name, "tier_id": tier_id}


@router.get("/recap")
def read_recap(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    """Everything waiting since the last time this was cleared.

    Harvest and mail, which is the only thing opening the app is for. The
    chests were already dropped and the badges were already earned; nothing
    here happens because somebody looked.
    """
    row = progress.process_user(db, user.id)
    since = row.last_ack_at
    badge_stmt = select(models.UserAchievement).where(
        models.UserAchievement.user_id == user.id
    )
    if since is not None:
        badge_stmt = badge_stmt.where(models.UserAchievement.earned_at > since)
    fresh = db.execute(
        badge_stmt.order_by(
            models.UserAchievement.earned_at, models.UserAchievement.achievement_id
        )
    ).scalars()

    # Miles from workouts that landed since the last acknowledgement, by when
    # the row arrived rather than when the workout started: a week of history
    # synced this morning is news this morning, whatever date is on it.
    miles_stmt = select(
        models.Workout.activity, func.coalesce(func.sum(models.Workout.distance_mi), 0.0)
    ).where(models.Workout.user_id == user.id)
    if since is not None:
        miles_stmt = miles_stmt.where(models.Workout.created_at > since)
    miles = sum(
        converted_miles(activity, float(total))
        for activity, total in db.execute(
            miles_stmt.group_by(models.Workout.activity)
        ).all()
    )

    # Ordered as the letter reads: the miles, then what people said about them,
    # then the medals, the achievements, and the chests still waiting.
    return {
        "since": since.isoformat() if since is not None else None,
        "miles": round(miles, 2),
        "encouragement": _received(db, user.id, since),
        "race_badges": _fresh_race_badges(db, user.id, since),
        "achievements": [
            achievements.serialize(achievements.BY_ID[held.achievement_id], held)
            for held in fresh
            if held.achievement_id in achievements.BY_ID
        ],
        "chests": _waiting_chests(db, user.id),
        **_flourish(db, user.id, row, since),
    }


def _waiting_chests(db: Session, user_id: int) -> list[dict]:
    """The chests still closed, and the one thing a letter says that a list of
    them does not: which of them somebody else gave you, and who.

    This is the whole of the reveal. Spending oil is silent when it happens,
    silent while it waits, and silent in every other response; the first the
    recipient hears of it is here, once the chest has actually landed.
    """
    rows = _pending(db, user_id, MAX_RECAP)
    gifts = {
        anointing_id: username
        for anointing_id, username in db.execute(
            select(models.Anointing.id, models.User.username)
            .join(models.User, models.User.id == models.Anointing.from_user_id)
            .where(
                models.Anointing.id.in_(
                    [row.from_anointing_id for row in rows if row.from_anointing_id]
                )
            )
        ).all()
    }
    out = []
    for row in rows:
        chest = _chest(row)
        # Null on every chest the miles themselves earned, which is most of them.
        chest["from_username"] = gifts.get(row.from_anointing_id or 0)
        out.append(chest)
    return out


def _received(db: Session, user_id: int, since: dt.datetime | None) -> dict:
    """What friends said since the last recap was cleared.

    Notes arrive whole, with the name of whoever wrote them, because a note is
    the point of the whole feature and a summary of one is worth nothing.
    Cheers are wordless, so they are counted per workout instead.
    """
    stmt = select(models.Encouragement).where(models.Encouragement.to_user_id == user_id)
    if since is not None:
        stmt = stmt.where(models.Encouragement.created_at > since)
    # Capped like the chests are, and for the same reason: a letter is read in
    # one sitting. Somebody who comes back to more than this has a very good
    # week's worth either way.
    rows = list(
        db.execute(stmt.order_by(models.Encouragement.created_at).limit(MAX_RECAP)).scalars()
    )
    senders = {
        sender_id: username
        for sender_id, username in db.execute(
            select(models.User.id, models.User.username).where(
                models.User.id.in_({row.from_user_id for row in rows})
            )
        ).all()
    }

    cheers: dict[int, int] = {}
    notes = []
    for row in rows:
        if row.kind == "cheer":
            cheers[row.workout_id] = cheers.get(row.workout_id, 0) + 1
            continue
        notes.append(
            {
                "workout_id": row.workout_id,
                "from_user_id": row.from_user_id,
                "username": senders.get(row.from_user_id, ""),
                "body": row.body or "",
                "created_at": row.created_at.isoformat(),
            }
        )
    return {
        "cheers": [
            {"workout_id": workout_id, "count": count}
            for workout_id, count in sorted(cheers.items())
        ],
        "cheer_count": sum(cheers.values()),
        "notes": notes,
    }


def _flourish(
    db: Session, user_id: int, row: models.UserProgress, since: dt.datetime | None
) -> dict:
    """The flourish stage, and whether it grew since the last recap.

    Worked out by taking back the renown earned since that moment rather than
    by storing the old stage, so nothing has to be written down to answer it.
    The renown itself never leaves this function.
    """
    stage = fellowship.flourish_stage(row.renown)
    before = fellowship.flourish_stage(row.renown - fellowship.renown_since(db, user_id, since))
    return {"flourish_stage": stage, "flourish_rose": stage > before}


def _fresh_race_badges(db: Session, user_id: int, since: dt.datetime | None) -> list[dict]:
    """Race badges to tell the player about, newest last.

    Selected by when the workout arrived rather than by when it happened, the
    same rule the miles above follow. A badge's own earned_at is the date of
    the run, which is what the profile should show and exactly the wrong thing
    to filter a recap by: a fortnight of history synced this morning would then
    hand over nothing.
    """
    stmt = (
        select(models.BadgeEarn)
        .join(models.Workout, models.Workout.id == models.BadgeEarn.workout_id)
        .where(models.BadgeEarn.user_id == user_id)
    )
    if since is not None:
        stmt = stmt.where(models.Workout.created_at > since)
    rows = db.execute(stmt.order_by(models.BadgeEarn.earned_at, models.BadgeEarn.id))
    return [
        {
            "id": row.badge_id,
            "name": achievements.BADGES_BY_ID[row.badge_id].name,
            "distance_mi": achievements.BADGES_BY_ID[row.badge_id].distance_mi,
            "workout_id": row.workout_id,
            "earned_at": row.earned_at.isoformat(),
        }
        for row in rows.scalars()
        if row.badge_id in achievements.BADGES_BY_ID
    ]


@router.post("/recap/ack", status_code=status.HTTP_204_NO_CONTENT)
def ack_recap(
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Mark the recap read. Chests are not touched: they wait to be opened."""
    row = progress.ensure_progress(db, user.id)
    row.last_ack_at = security.now_utc()
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
