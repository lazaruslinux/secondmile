"""Chests, what comes out of them, and the recap of everything that happened while away."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import fellowship, grove, medals, models, progress, security
from app.activity import converted_miles
from app.db import get_db

router = APIRouter(tags=["chests"])

# The recap is a story, not a feed. A letter is read in one sitting, and
# somebody who comes back to more than this many notes has a very good week's
# worth either way; the rest are still on the workouts they were written on.
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


def _pending(db: Session, user_id: int) -> list[models.Chest]:
    """Every chest still closed, oldest first. Never capped: the letter counts
    them now, and a count that stopped at some number would be a lie."""
    return list(
        db.execute(
            select(models.Chest)
            .where(models.Chest.user_id == user_id, models.Chest.opened_at.is_(None))
            .order_by(models.Chest.id)
        ).scalars()
    )


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

    Nothing is opened here either, any more. The letter announces what landed
    and the inventory is where the lid comes off, which is what makes a chest
    something kept rather than something cleared on the way past.
    """
    row = progress.process_user(db, user.id)
    since = row.last_ack_at

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

    # Ordered as the letter reads: what window it covers, the miles in it, what
    # people said about them, then the medals, what grew, and what landed.
    return {
        "since": since.isoformat() if since is not None else None,
        "last_sync_at": _last_sync(db, user.id),
        "miles": round(miles, 2),
        "encouragement": _received(db, user.id, since),
        "medals": _fresh_medals(db, user.id, since),
        "plant_growth": _plant_growth(db, user.id, since),
        **_delivered(db, user.id),
        **_flourish(db, user.id, row, since),
    }


def _delivered(db: Session, user_id: int) -> dict:
    """How many chests are waiting in the inventory, and who gave any of them.

    A count rather than a list: the letter says they arrived, the inventory is
    where they are opened, and a letter that also opened them would be two
    places doing one job.

    The names are what a count cannot carry on its own, and they are the whole
    of the reveal. Spending oil is silent when it happens, silent while it
    waits, and silent in every other response; the first the recipient hears of
    it is here, once the chest has actually landed.
    """
    rows = _pending(db, user_id)
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
    return {
        "chests_delivered": len(rows),
        # One name per gifted chest, in the order they landed, so two from the
        # same friend are still two things given. Empty on the ordinary letter,
        # where every chest is one the miles themselves earned.
        "chest_givers": [
            gifts[row.from_anointing_id] for row in rows if row.from_anointing_id in gifts
        ],
    }


def _last_sync(db: Session, user_id: int) -> str | None:
    """When the phone last posted an export, or null for an account that has
    never sent one.

    Null is an ordinary answer rather than a fault: a player who only ever uses
    the manual form has no sync to report, and neither has anybody on their
    first day.

    UTC and ISO, like every other stamp in the letter. The instance timezone
    rides on /api/status and the client renders in it, because a browser pinned
    to UTC would read a quarter to two in the afternoon as nine in the evening.
    """
    stamp = db.execute(
        select(models.IngestLog.received_at)
        .where(models.IngestLog.user_id == user_id)
        .order_by(models.IngestLog.received_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return stamp.isoformat() if stamp is not None else None


def _plant_growth(db: Session, user_id: int, since: dt.datetime | None) -> list[dict]:
    """The plants that put on at least a whole level since the letter was last
    cleared, in the shape the plot is read in, with the levels they gained.

    Worked out by taking the growth back off again rather than by writing down
    what a plant used to be, which is the same trick the flourish uses: every
    workout that arrived since the acknowledgement is subtracted from what a
    planting holds now, and the level it stood at before is read off the rest.

    Water is the gap. Nothing records which planting a water item was poured
    into, so growth that water paid for cannot be taken back off, and a level
    that water alone carried is missed. Missing one is the quiet way to be
    wrong: the alternative guesses, and a letter congratulating the wrong plant
    is worse than a letter that says nothing.
    """
    rows = list(
        db.execute(
            select(models.Planting)
            .where(models.Planting.user_id == user_id)
            .order_by(models.Planting.id)
        ).scalars()
    )
    if not rows:
        return []

    stmt = select(
        models.Workout.activity,
        models.Workout.distance_mi,
        models.Workout.created_at,
        models.Workout.start_ts,
    ).where(models.Workout.user_id == user_id)
    if since is not None:
        stmt = stmt.where(models.Workout.created_at > since)
    # (when it landed, what it was worth to a plant), which is the same pair
    # the growth was credited from in the first place.
    arrivals = [
        (
            created_at or start_ts,
            grove.growth_amount(converted_miles(activity, float(distance)), activity),
        )
        for activity, distance, created_at, start_ts in db.execute(stmt).all()
    ]

    out = []
    for row in rows:
        # Only what was already in the ground when a workout landed grew from
        # it, which is the rule grow() itself follows.
        gained = sum(amount for moment, amount in arrivals if row.planted_at <= moment)
        level = grove.level_of(row)
        before = grove.level_for(row.species, max(row.growth_mi - gained, 0.0))
        if level > before:
            out.append({**grove.serialize_planting(row), "levels_gained": level - before})
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
    # Capped at MAX_RECAP, which is the only thing in the letter that still is:
    # a count of chests costs nothing to be honest about, and a wall of notes
    # does.
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


def _fresh_medals(db: Session, user_id: int, since: dt.datetime | None) -> list[dict]:
    """Medals to tell the player about, newest last, every family.

    Selected by when the workout arrived rather than by when it happened, the
    same rule the miles above follow. A medal's own earned_at is the date of
    the run, which is what the profile should show and exactly the wrong thing
    to filter a recap by: a fortnight of history synced this morning would then
    hand over nothing. A weekly medal is filtered by the arrival of the workout
    that crossed the line, which is the same rule read one table across.
    """
    found: list[tuple[dt.datetime, int, dict]] = []
    order = {medal.id: index for index, medal in enumerate(medals.CATALOG)}
    for table in (models.BadgeEarn, models.WeeklyBadgeEarn):
        stmt = (
            select(table)
            .join(models.Workout, models.Workout.id == table.workout_id)
            .where(table.user_id == user_id)
        )
        if since is not None:
            stmt = stmt.where(models.Workout.created_at > since)
        for row in db.execute(stmt).scalars():
            if row.badge_id not in medals.BY_ID:
                continue
            found.append(
                (
                    row.earned_at,
                    order[row.badge_id],
                    {
                        "id": row.badge_id,
                        "name": medals.BY_ID[row.badge_id].name,
                        "earned_at": row.earned_at.isoformat(),
                    },
                )
            )
    # Oldest first, and the catalogue settles two earned on the same run, so the
    # letter reads the same way twice.
    return [entry for _stamp, _rank, entry in sorted(found, key=lambda item: item[:2])]


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
