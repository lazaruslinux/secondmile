"""Friends, the encouragement they send each other, and the renown it pays.

Friendship is strictly mutual and always by name: there is no discovery, no
list of strangers, and no count of anybody's friends anywhere in the API. What
a friend can see of a workout is decided here too, and it is deliberately less
than the owner sees.

Renown is the only thing kept score of, it is earned by giving rather than by
receiving, and no response ever carries the number. It surfaces as a flourish
stage on the avatar border and nowhere else.
"""

import datetime as dt

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app import models, progress
from app.config import (
    FLOURISH_RENOWN,
    RENOWN_CHEER,
    RENOWN_NOTE,
    RENOWN_WINDOW_DAYS,
)
from app.security import now_utc

RENOWN_PER_KIND = {"cheer": RENOWN_CHEER, "note": RENOWN_NOTE}


# --------------------------------------------------------------------------
# Who is whose friend
# --------------------------------------------------------------------------


def friend_ids(db: Session, user_id: int) -> set[int]:
    """Every account this one is actually friends with, both directions.

    One query, because the feed asks this before it asks anything else and the
    answer decides the whole rest of the request.
    """
    rows = db.execute(
        select(models.Friendship.requester_id, models.Friendship.addressee_id).where(
            models.Friendship.status == "accepted",
            or_(
                models.Friendship.requester_id == user_id,
                models.Friendship.addressee_id == user_id,
            ),
        )
    ).all()
    return {
        addressee if requester == user_id else requester for requester, addressee in rows
    }


def are_friends(db: Session, user_id: int, other_id: int) -> bool:
    """Whether an accepted row joins the two, whichever way round it was asked."""
    if user_id == other_id:
        return False
    return (
        db.execute(
            select(models.Friendship.id)
            .where(
                models.Friendship.status == "accepted",
                or_(
                    (models.Friendship.requester_id == user_id)
                    & (models.Friendship.addressee_id == other_id),
                    (models.Friendship.requester_id == other_id)
                    & (models.Friendship.addressee_id == user_id),
                ),
            )
            .limit(1)
        ).first()
        is not None
    )


def link(db: Session, user_id: int, other_id: int) -> models.Friendship | None:
    """The row between two accounts, whichever way round it was asked."""
    return db.execute(
        select(models.Friendship)
        .where(
            or_(
                (models.Friendship.requester_id == user_id)
                & (models.Friendship.addressee_id == other_id),
                (models.Friendship.requester_id == other_id)
                & (models.Friendship.addressee_id == user_id),
            )
        )
        .limit(1)
    ).scalar_one_or_none()


def unlink(db: Session, user_id: int, other_id: int) -> None:
    """Drop whatever stood between two accounts: an invite either way, or the
    friendship itself. Decline, cancel, and unfriend are one action because
    they are one thing from the database's side."""
    db.execute(
        delete(models.Friendship).where(
            or_(
                (models.Friendship.requester_id == user_id)
                & (models.Friendship.addressee_id == other_id),
                (models.Friendship.requester_id == other_id)
                & (models.Friendship.addressee_id == user_id),
            )
        )
    )


# --------------------------------------------------------------------------
# Renown and its flourish
# --------------------------------------------------------------------------


def flourish_stage(renown: int) -> int:
    """Which flourish a renown total wears, from 0 up. Never the number itself:
    the stage is the only thing any response is allowed to say."""
    return sum(1 for threshold in FLOURISH_RENOWN if renown >= threshold)


def earns_renown(
    db: Session, from_user_id: int, to_user_id: int, kind: str, moment: dt.datetime
) -> bool:
    """Whether this encouragement pays its sender anything.

    The diminishing rule: inside the window, one pair earns for the first cheer
    and the first note and nothing after. Asked of the stored earned_renown
    flag rather than of a running total, so the check is one indexed lookup and
    a replay cannot pay twice.
    """
    cutoff = moment - dt.timedelta(days=RENOWN_WINDOW_DAYS)
    return (
        db.execute(
            select(models.Encouragement.id)
            .where(
                models.Encouragement.from_user_id == from_user_id,
                models.Encouragement.to_user_id == to_user_id,
                models.Encouragement.kind == kind,
                models.Encouragement.earned_renown.is_(True),
                models.Encouragement.created_at > cutoff,
            )
            .limit(1)
        ).first()
        is None
    )


def give(
    db: Session, giver_id: int, workout: models.Workout, kind: str, body: str | None
) -> models.Encouragement:
    """Record one piece of encouragement and pay whatever renown it earns.

    Flushed inside a savepoint so the partial unique index refusing a second
    cheer surfaces as an IntegrityError the caller can answer, rather than
    poisoning the session. The renown is worked out before the insert and
    applied after it, so a refused cheer pays nothing.
    """
    now = now_utc()
    earned = earns_renown(db, giver_id, workout.user_id, kind, now)
    row = models.Encouragement(
        workout_id=workout.id,
        from_user_id=giver_id,
        to_user_id=workout.user_id,
        kind=kind,
        body=body,
        earned_renown=earned,
        created_at=now,
    )
    with db.begin_nested():
        db.add(row)
        db.flush()
    if earned:
        progress.ensure_progress(db, giver_id).renown += RENOWN_PER_KIND[kind]
    db.commit()
    return row


def renown_since(
    db: Session, user_id: int, since: dt.datetime | None
) -> int:
    """How much renown this account has earned since a moment.

    Summed from the encouragements that earned it rather than stored, which is
    what lets the recap say the flourish grew without keeping a second copy of
    the total.
    """
    stmt = select(models.Encouragement.kind, func.count()).where(
        models.Encouragement.from_user_id == user_id,
        models.Encouragement.earned_renown.is_(True),
    )
    if since is not None:
        stmt = stmt.where(models.Encouragement.created_at > since)
    return sum(
        RENOWN_PER_KIND.get(kind, 0) * int(count)
        for kind, count in db.execute(stmt.group_by(models.Encouragement.kind)).all()
    )


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------


def people(db: Session, user_ids) -> dict[int, dict]:
    """The little card a person appears as beside a workout or in a list.

    Two queries for any number of people, because the feed needs one of these
    per row and a per-row query is how a feed stops being fast. Nothing in it
    is private: a name, whether there is a picture, and the two things worn on
    the frame.
    """
    ids = list(user_ids)
    if not ids:
        return {}
    state = {
        user_id: (level, renown)
        for user_id, level, renown in db.execute(
            select(
                models.UserProgress.user_id,
                models.UserProgress.level,
                models.UserProgress.renown,
            ).where(models.UserProgress.user_id.in_(ids))
        ).all()
    }
    rows = db.execute(
        select(models.User.id, models.User.username, models.User.avatar_path).where(
            models.User.id.in_(ids)
        )
    ).all()
    cards = {}
    for user_id, username, avatar_path in rows:
        level, renown = state.get(user_id, (0, 0))
        cards[user_id] = {
            "user_id": user_id,
            "username": username,
            "has_avatar": avatar_path is not None,
            "border_tier": progress.border_tier(level),
            "flourish": flourish_stage(renown),
        }
    return cards


def counts(db: Session, workout_ids, viewer_id: int) -> dict[int, dict]:
    """Cheers, notes, and whether the viewer has already cheered, per workout.

    Two queries for the whole page. The counts are plain text on the card, so
    they are totals rather than lists; the notes themselves are fetched only
    when somebody opens them.
    """
    ids = list(workout_ids)
    out = {
        workout_id: {"cheers": 0, "notes": 0, "cheered_by_me": False}
        for workout_id in ids
    }
    if not ids:
        return out
    for workout_id, kind, count in db.execute(
        select(
            models.Encouragement.workout_id, models.Encouragement.kind, func.count()
        )
        .where(models.Encouragement.workout_id.in_(ids))
        .group_by(models.Encouragement.workout_id, models.Encouragement.kind)
    ).all():
        out[workout_id]["cheers" if kind == "cheer" else "notes"] = int(count)
    for workout_id in db.execute(
        select(models.Encouragement.workout_id).where(
            models.Encouragement.workout_id.in_(ids),
            models.Encouragement.from_user_id == viewer_id,
            models.Encouragement.kind == "cheer",
        )
    ).scalars():
        out[workout_id]["cheered_by_me"] = True
    return out
