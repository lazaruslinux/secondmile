"""Friends, the encouragement they send each other, and the renown it pays.

Friendship is strictly mutual and always asked for by name: no count of
anybody's friends appears anywhere in the API, and nothing suggests anybody to
anybody. Members of one instance may look each other up, because an instance is
a private club and its roster is a room somebody was let into, and what they
find is a name, a face and a line: everything the game keeps stays behind an
accepted invite. What a friend can see of a workout is decided here too, and it
is deliberately less than the owner sees.

Renown is the only thing kept score of, it is earned by giving rather than by
receiving, and no response ever carries the number. It surfaces as a flourish
stage on the avatar border and nowhere else.
"""

import datetime as dt

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, progress
from app.activity import converted_miles
from app.config import (
    FLOURISH_RENOWN,
    RENOWN_CHEER,
    RENOWN_FEED,
    RENOWN_FRUIT_GIFT,
    RENOWN_MANNA_GIFT,
    RENOWN_NOTE,
    RENOWN_OIL,
    RENOWN_WATER,
    RENOWN_WINDOW_DAYS,
)
from app.security import now_utc

# The three things an account may keep back from its friends, and the whole of
# what hidden_from_friends may hold. Distance, time, and the words on a workout
# are not on the list: they are the card itself, and a feed of cards saying
# nothing is not a feed. Pace is not on it either, and deliberately: pace is
# distance over time, both of which stay, so a toggle for it would promise a
# privacy it could not keep.
HIDEABLE = ("avg_hr", "active_kcal", "route")

RENOWN_PER_KIND = {"cheer": RENOWN_CHEER, "note": RENOWN_NOTE}
# What giving away something a chest gave you is worth. The same diminishing
# window applies, kind by kind, for the same reason: two accounts trading
# water all evening earn one pour's worth between them.
RENOWN_PER_GIFT = {"water": RENOWN_WATER, "oil": RENOWN_OIL}

# How many notes ride a card without anybody asking for them: the pair printed
# under every activity. Whatever else was said waits behind the view-all line.
INLINE_NOTES = 2


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


def invited(db: Session, from_user_id: int, to_user_id: int) -> bool:
    """Whether one account has an invite waiting on another, that way round only.

    The direction is the whole of it. Whoever received an invite may see the
    face of whoever sent it, because answering a card with no picture on it is
    answering nobody. The other way round is refused: an account can create a
    pending invite to any name it likes, so serving the recipient's picture back
    would make the invite form a way to look up the person behind a username,
    which is the hole the rest of this file is shaped around.
    """
    return (
        db.execute(
            select(models.Friendship.id)
            .where(
                models.Friendship.requester_id == from_user_id,
                models.Friendship.addressee_id == to_user_id,
                models.Friendship.status == "pending",
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
# The names somebody typed into the invite form
# --------------------------------------------------------------------------
# Kept apart from the friendship rows on purpose. A friendship row exists only
# when the name resolved, so a list built from those rows says which of the
# names somebody tried are real accounts. These rows are the names themselves,
# real or not, and they are what the sent list is served from.


def outbound_names(db: Session, user_id: int) -> list[str]:
    """Every name this account has invited and not cancelled, in name order.

    Sorted here rather than by when they were sent, so the list does not
    reshuffle itself between visits.
    """
    return sorted(
        db.execute(
            select(models.OutboundInvite.username).where(
                models.OutboundInvite.user_id == user_id
            )
        ).scalars()
    )


def record_outbound(db: Session, user_id: int, username: str, moment: dt.datetime) -> None:
    """Remember one name somebody typed. Sending the same invite twice is a
    no-op, settled by the unique pair rather than by reading first."""
    try:
        with db.begin_nested():
            db.add(
                models.OutboundInvite(
                    user_id=user_id, username=username, created_at=moment
                )
            )
            db.flush()
    except IntegrityError:
        # Already there, which is what a second invite to the same name is.
        db.rollback()


def forget_outbound(db: Session, user_id: int, username: str) -> None:
    """Take one name back off the sent list, whether or not it was on it."""
    db.execute(
        delete(models.OutboundInvite).where(
            models.OutboundInvite.user_id == user_id,
            models.OutboundInvite.username == username,
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


def gift_earns_renown(
    db: Session, from_user_id: int, to_user_id: int, kind: str, moment: dt.datetime
) -> bool:
    """Whether giving one item away pays its giver anything.

    The same seven day window the words above use, asked of the satchel: one
    pair earns for the first water and the first oil inside it and nothing
    after. Spending on your own plot is not giving and never asks this.
    """
    cutoff = moment - dt.timedelta(days=RENOWN_WINDOW_DAYS)
    return (
        db.execute(
            select(models.SatchelItem.id)
            .where(
                models.SatchelItem.user_id == from_user_id,
                models.SatchelItem.given_to_user_id == to_user_id,
                models.SatchelItem.kind == kind,
                models.SatchelItem.earned_renown.is_(True),
                models.SatchelItem.used_at > cutoff,
            )
            .limit(1)
        ).first()
        is None
    )


def _first_in_window(db: Session, stmt, moment: dt.datetime, column) -> bool:
    """Whether one pair has no earning row of this kind inside the window yet.

    The three manna givings ask this of three different tables, so the window
    itself is written once: the caller brings the rows for its pair and its
    kind, and this decides whether the newest of them is old enough to have let
    the next one earn again.
    """
    cutoff = moment - dt.timedelta(days=RENOWN_WINDOW_DAYS)
    return db.execute(stmt.where(column > cutoff).limit(1)).first() is None


def feed_earns_renown(
    db: Session, from_user_id: int, to_user_id: int, moment: dt.datetime
) -> bool:
    """Whether feeding this friend's plant pays anything.

    Water's rule pointed at a different verb: one pair earns for the first feed
    inside the window and nothing after, however many plants are fed. Feeding
    your own plot never asks, because giving to yourself is not giving.
    """
    if from_user_id == to_user_id:
        return False
    return _first_in_window(
        db,
        select(models.PlantFeeding.id).where(
            models.PlantFeeding.from_user_id == from_user_id,
            models.PlantFeeding.to_user_id == to_user_id,
            models.PlantFeeding.earned_renown.is_(True),
        ),
        moment,
        models.PlantFeeding.created_at,
    )


def manna_gift_earns_renown(
    db: Session, from_user_id: int, to_user_id: int, moment: dt.datetime
) -> bool:
    """Whether handing this friend raw manna pays anything. A note's rule: the
    first one inside the window, whatever it was worth."""
    return _first_in_window(
        db,
        select(models.MannaGift.id).where(
            models.MannaGift.from_user_id == from_user_id,
            models.MannaGift.to_user_id == to_user_id,
            models.MannaGift.earned_renown.is_(True),
        ),
        moment,
        models.MannaGift.created_at,
    )


def fruit_gift_earns_renown(
    db: Session, from_user_id: int, to_user_id: int, moment: dt.datetime
) -> bool:
    """Whether giving this friend fruit pays anything. The top of the ladder,
    diminishing like everything else on it."""
    return _first_in_window(
        db,
        select(models.FruitBatch.id).where(
            models.FruitBatch.user_id == from_user_id,
            models.FruitBatch.given_to_user_id == to_user_id,
            models.FruitBatch.earned_renown.is_(True),
        ),
        moment,
        models.FruitBatch.given_at,
    )


def pay_renown(db: Session, user_id: int, amount: int) -> None:
    """Add to what somebody has earned by giving. Never by receiving: a number
    that grew from being given to would reward asking rather than caring."""
    if amount:
        progress.ensure_progress(db, user_id).renown += amount
    db.flush()


def spend_on(
    db: Session,
    item: models.SatchelItem,
    recipient_id: int,
    kind: str,
    moment: dt.datetime,
) -> None:
    """Record who one spent item went to and pay whatever renown it earned.

    The spending itself already happened: the caller took the item out of the
    satchel with a conditional update, which is the one thing that decides
    whether this call happens at all. This rides on that single spend rather
    than writing used_at a second time, so there is exactly one statement in the
    codebase that can turn an unspent item into a spent one.

    Flushes but never commits: the caller owns the transaction, because the
    thing the item actually did has to succeed or fail alongside this.
    """
    earned = gift_earns_renown(db, item.user_id, recipient_id, kind, moment)
    item.given_to_user_id = recipient_id
    item.earned_renown = earned
    if earned:
        progress.ensure_progress(db, item.user_id).renown += RENOWN_PER_GIFT[kind]
    db.flush()


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

    Summed from the things that earned it rather than stored, which is what
    lets the recap say the flourish grew without keeping a second copy of the
    total. Every way of giving counts: words about somebody's workout, something
    out of a chest handed over, and manna spent on somebody else's grove.
    """
    said = select(models.Encouragement.kind, func.count()).where(
        models.Encouragement.from_user_id == user_id,
        models.Encouragement.earned_renown.is_(True),
    )
    given = select(models.SatchelItem.kind, func.count()).where(
        models.SatchelItem.user_id == user_id,
        models.SatchelItem.earned_renown.is_(True),
    )
    if since is not None:
        said = said.where(models.Encouragement.created_at > since)
        given = given.where(models.SatchelItem.used_at > since)
    total = sum(
        RENOWN_PER_KIND.get(kind, 0) * int(count)
        for kind, count in db.execute(said.group_by(models.Encouragement.kind)).all()
    )
    total += sum(
        RENOWN_PER_GIFT.get(kind, 0) * int(count)
        for kind, count in db.execute(given.group_by(models.SatchelItem.kind)).all()
    )
    return total + _manna_renown_since(db, user_id, since)


def _manna_renown_since(db: Session, user_id: int, since: dt.datetime | None) -> int:
    """The three manna givings, counted the same way the two above are.

    One count each rather than one query: they are three tables, and the row
    that earned in each of them carries its own stamp. A feeding of your own
    plot never earned, so it is never counted here either.
    """
    rows = (
        (models.PlantFeeding, models.PlantFeeding.from_user_id, models.PlantFeeding.created_at, RENOWN_FEED),
        (models.MannaGift, models.MannaGift.from_user_id, models.MannaGift.created_at, RENOWN_MANNA_GIFT),
        (models.FruitBatch, models.FruitBatch.user_id, models.FruitBatch.given_at, RENOWN_FRUIT_GIFT),
    )
    total = 0
    for table, owner, stamp, worth in rows:
        stmt = (
            select(func.count())
            .select_from(table)
            .where(owner == user_id, table.earned_renown.is_(True))
        )
        if since is not None:
            stmt = stmt.where(stamp > since)
        total += worth * int(db.execute(stmt).scalar_one())
    return total


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------


def display_name(first_name: str | None, last_name: str | None) -> str | None:
    """The name somebody goes by, or null when they have not given one.

    Composed here rather than on the client so every screen that shows a person
    joins the halves the same way, and so an account with only one of the two
    reads as that one rather than as a name with a hole in it. The username is
    untouched by all of this: it is still the login and the invite identity, and
    it is what a card falls back to.
    """
    joined = " ".join(part.strip() for part in (first_name, last_name) if part and part.strip())
    return joined or None


def hidden_fields(db: Session, user_ids) -> dict[int, tuple[str, ...]]:
    """What each of these accounts keeps back, by account id.

    One query for a whole page, the way the cards beside it are read: the feed
    asks this of every owner on the page at once rather than per row. Never
    served to anybody. It is the owner's answer to what a friend may see, and
    the list itself is between the owner and the server.
    """
    ids = list(user_ids)
    if not ids:
        return {}
    return {
        user_id: tuple(str(field) for field in (hidden or []))
        for user_id, hidden in db.execute(
            select(models.User.id, models.User.hidden_from_friends).where(
                models.User.id.in_(ids)
            )
        ).all()
    }


def people(db: Session, user_ids) -> dict[int, dict]:
    """The little card a person appears as beside a workout or in a list.

    Two queries for any number of people, because the feed needs one of these
    per row and a per-row query is how a feed stops being fast. Nothing in it
    is private: a name, whether there is a picture, the two things worn on the
    frame, and the medals they chose to wear.
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
        select(
            models.User.id,
            models.User.username,
            models.User.avatar_path,
            models.User.first_name,
            models.User.last_name,
            # Read alongside the rest rather than asked for per person: the
            # medals are the reason a feed row says who somebody is, and one
            # more round trip per row would undo what this function is for.
            models.User.displayed_badges,
        ).where(models.User.id.in_(ids))
    ).all()
    cards = {}
    for user_id, username, avatar_path, first_name, last_name, badges in rows:
        level, renown = state.get(user_id, (0, 0))
        cards[user_id] = {
            "user_id": user_id,
            "username": username,
            # Null unless they have given a name; the card falls back to the
            # username, which every account has.
            "display_name": display_name(first_name, last_name),
            "has_avatar": avatar_path is not None,
            "border_tier": progress.border_tier(level),
            "flourish": flourish_stage(renown),
            # The ones they chose to wear, in slot order, never the ones a
            # workout earned. Copied into a list so an account wearing none
            # arrives as [] and the client never has to read a null.
            "displayed_badges": list(badges or []),
        }
    return cards


def note_card(person: dict, body: str | None, created_at: dt.datetime) -> dict:
    """One written note, as every screen that prints one receives it.

    Written once because two places serve it: the thread endpoint, and the pair
    of notes a card carries without being asked. A card drawn from one of those
    and a card drawn from the other have to be the same card, or the same words
    read differently depending on which end of the screen they arrived at.
    """
    return {
        "user": person,
        "body": body or "",
        "created_at": created_at.isoformat(),
    }


def first_notes(db: Session, workout_ids, limit: int = INLINE_NOTES) -> dict[int, list[dict]]:
    """The oldest few notes on each of these workouts, oldest first.

    One query for a whole page of workouts, whatever is said on them: the notes
    are numbered inside each workout by a window function and the page is cut at
    the number, so a feed of twenty cards asks once rather than twenty times.
    The numbering is the thread's own order, tie-broken by id, so the pair under
    a card is the pair at the top of the thread it opens.

    Nothing here decides who may read anything. The ids arrive from a caller
    that has already settled what this viewer may see, and these notes ride a
    payload that was going out either way.
    """
    ids = list(workout_ids)
    if not ids:
        return {}
    ranked = (
        select(
            models.Encouragement.workout_id,
            models.Encouragement.from_user_id,
            models.Encouragement.body,
            models.Encouragement.created_at,
            func.row_number()
            .over(
                partition_by=models.Encouragement.workout_id,
                order_by=(models.Encouragement.created_at, models.Encouragement.id),
            )
            .label("place"),
        )
        .where(
            models.Encouragement.workout_id.in_(ids),
            models.Encouragement.kind == "note",
        )
        .subquery()
    )
    rows = db.execute(
        select(
            ranked.c.workout_id,
            ranked.c.from_user_id,
            ranked.c.body,
            ranked.c.created_at,
        )
        .where(ranked.c.place <= limit)
        .order_by(ranked.c.workout_id, ranked.c.place)
    ).all()
    # The writers batched the way the feed batches everybody else: two queries
    # for every face on the page.
    cards = people(db, {from_user_id for _, from_user_id, _, _ in rows})
    out: dict[int, list[dict]] = {}
    for workout_id, from_user_id, body, created_at in rows:
        out.setdefault(workout_id, []).append(
            note_card(cards[from_user_id], body, created_at)
        )
    return out


def counts(db: Session, workout_ids, viewer_id: int) -> dict[int, dict]:
    """What a workout has been given: the two totals, whether the viewer has
    cheered it, and the oldest notes written on it.

    Four queries for the whole page however many rows are on it. The notes are
    here rather than fetched per card because the pair under a card is part of
    the card: asking for them one workout at a time is what turns a feed into
    twenty requests. The rest of the thread still waits until somebody opens it.
    """
    ids = list(workout_ids)
    out = {
        workout_id: {
            "hype_count": 0,
            "note_count": 0,
            "cheered_by_me": False,
            # The oldest two, in the thread's order. Empty when nobody has
            # written, never absent.
            "notes": [],
        }
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
        out[workout_id]["hype_count" if kind == "cheer" else "note_count"] = int(count)
    for workout_id in db.execute(
        select(models.Encouragement.workout_id).where(
            models.Encouragement.workout_id.in_(ids),
            models.Encouragement.from_user_id == viewer_id,
            models.Encouragement.kind == "cheer",
        )
    ).scalars():
        out[workout_id]["cheered_by_me"] = True
    for workout_id, notes in first_notes(db, ids).items():
        out[workout_id]["notes"] = notes
    return out


def feed_row(
    workout: models.Workout,
    person: dict,
    own: bool,
    medal_ids: list[str],
    has_route: bool,
    photo_ids: list[int],
    video_ids: list[int],
    encouragement: dict,
    hidden: tuple[str, ...] = (),
) -> dict:
    """One feed event.

    Here rather than in a router because three of them serve these rows: the
    feed, a friend's profile, and your own training log. This function is the
    only place the rule below is written down, and a second copy of it is a copy
    somebody can edit on its own.

    A friend sees what you did, in full: the distance, the time, the heart
    rate, the calories, and the line you ran. What they do not see is what you
    said they may not. `hidden` is the owner's own list, from HIDEABLE, and a
    field on it is left out of the row altogether rather than sent as a null: a
    null would say the workout carried no heart rate, which is a different thing
    from being asked not to look. The route is hidden by has_route reading
    false, so no map is drawn and nothing asks for the line the endpoint would
    refuse anyway.

    Own rows carry everything whatever the list says. Hiding a number from
    yourself is not a privacy setting, and the experience a workout earned is
    still on your own rows and nowhere else.

    Pace is not here and never was: it is the distance over the time, both of
    which every row carries, and the client does that division itself.
    """
    kept_back = () if own else hidden
    row = {
        "workout_id": workout.id,
        "user": person,
        "activity": workout.activity,
        # Beside the activity because it only ever qualifies it: an indoor walk
        # is a walk, drawn with a treadmill instead of a pavement. Never held
        # back, because it is part of what the activity was rather than a
        # number about a body.
        "indoor": workout.indoor,
        "start_ts": workout.start_ts.isoformat(),
        "distance_mi": round(workout.distance_mi, 3),
        "duration_s": workout.duration_s,
        "medals": medal_ids,
        # False rather than absent when the route is hidden: a card reads this
        # to decide whether to draw a map, and the honest answer to "is there
        # one you can see" is no.
        "has_route": has_route and "route" not in kept_back,
        "title": workout.title,
        "post": workout.post,
        "photos": photo_ids,
        # Beside the photos rather than folded in with them: the card fetches
        # the two from different endpoints and draws a play mark on one of
        # them, so a reader that could not tell them apart would draw neither.
        "videos": video_ids,
        "source": workout.source,
        "own": own,
    }
    if "avg_hr" not in kept_back:
        row["avg_hr"] = round(workout.avg_hr, 1) if workout.avg_hr is not None else None
    if "active_kcal" not in kept_back:
        row["active_kcal"] = round(workout.active_kcal, 1)
    if own:
        row["xp"] = round(converted_miles(workout.activity, workout.distance_mi), 2)
        # Own rows only, and only so the edit panel can open its picker on the
        # pair already assigned. Cards print nothing about gear.
        row["gear_id"] = workout.gear_id
    row["encouragement"] = encouragement
    return row
