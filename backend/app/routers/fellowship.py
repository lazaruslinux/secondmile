"""Friends, the invites between them, and the feed they share.

Everything here answers as little as it can. An invite says nothing about
whether the name existed, the friends list carries no counts, and a feed row
for somebody else's workout holds the headline and nothing behind it: no heart
rate, no calories, no flags, and no experience. What a friend sees is what a
friend would be told at the door.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import fellowship, medals, models, progress, security, throttle
from app.db import get_db
from app.routers.workouts import parse_cursor, photos_for, routes_for

router = APIRouter(tags=["fellowship"])

# One page of the feed. Fixed rather than asked for: the home screen is the
# only thing that reads it, and a cursor is how it goes further back.
FEED_PAGE_SIZE = 20

# How many names may sit on the sent list at once. Far more than anybody has
# people to invite, and low enough that the list cannot be used as somewhere to
# park a dictionary of usernames. The refusal says the same thing whatever was
# typed, so it gives nothing away either.
MAX_OUTBOUND_INVITES = 100
TOO_MANY_INVITES = "Too many pending invites."
# Answering invites: accepting, declining, cancelling, unfriending. One sentence
# for the four, because they come out of one allowance.
TOO_MANY_ACTIONS = "Too many changes just now. Wait a minute."


class InviteBody(BaseModel):
    username: str


@router.post("/friends/invite", status_code=status.HTTP_204_NO_CONTENT)
def invite_friend(
    body: InviteBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Ask somebody to be friends, by name.

    Answers 204 whatever happens: whether that name exists, whether they have
    already been asked, and whether they already said yes are all things this
    endpoint would otherwise be a way to look up. There is no discovery in this
    app, and an invite form that reported back would be one.

    Two rows can come out of it. The name as it was typed is always written
    down, real or not, and that is what the sent list is served from; the
    friendship row is written only when the name resolves, and that is what the
    other person answers. Keeping them apart is what stops invite, read, cancel,
    repeat from being a way to walk the username space.
    """
    if throttle.invite_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many invites just now. Wait a minute.")
    wanted = body.username.strip().lower()
    if wanted == user.username:
        # The one refusal worth making out loud. It leaks nothing: the caller
        # already knows their own name.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot invite yourself.")

    now = security.now_utc()
    other = db.execute(
        select(models.User).where(models.User.username == wanted)
    ).scalar_one_or_none()
    existing = None if other is None else fellowship.link(db, user.id, other.id)

    if existing is None or existing.status != "accepted":
        # Nothing to add to the sent list for somebody who is already a friend:
        # they are on the list above it, and the name is not waiting on anybody.
        if len(fellowship.outbound_names(db, user.id)) >= MAX_OUTBOUND_INVITES:
            # Checked before the row is looked for rather than after, so the cap
            # answers the same way for a name already sent as for a new one.
            raise HTTPException(status.HTTP_400_BAD_REQUEST, TOO_MANY_INVITES)
        fellowship.record_outbound(db, user.id, wanted, now)
        # Committed on its own, before the friendship below, so a race on that
        # row cannot take this one back out with it.
        db.commit()

    if other is not None and other.id != user.id and existing is None:
        try:
            with db.begin_nested():
                db.add(
                    models.Friendship(
                        requester_id=user.id,
                        addressee_id=other.id,
                        status="pending",
                        created_at=now,
                    )
                )
                db.flush()
        except IntegrityError:
            # Two invites racing each other. The first one stands and this one
            # is the no-op it would have been a moment later.
            db.rollback()
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/friends")
def list_friends(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    """Who you are friends with, and the invites waiting either way.

    No counts anywhere, here or anywhere else: how many friends somebody has is
    not a number this game keeps.

    The two lists are not the same shape, and that is deliberate. A friend and
    somebody who has asked to be one are people this account has a card for:
    both of them chose to be here. The invites you sent are names you typed, and
    they come back as exactly that. Serving a card there would mean this
    endpoint could be asked, one name at a time, which names belong to real
    people and what those people look like, and no amount of care further down
    would take that back.
    """
    rows = list(
        db.execute(
            select(models.Friendship).where(
                or_(
                    models.Friendship.requester_id == user.id,
                    models.Friendship.addressee_id == user.id,
                )
            )
        ).scalars()
    )
    friends, pending_in = [], []
    for row in rows:
        other_id = row.addressee_id if row.requester_id == user.id else row.requester_id
        if row.status == "accepted":
            friends.append(other_id)
        elif row.addressee_id == user.id:
            pending_in.append(other_id)

    cards = fellowship.people(db, friends + pending_in)

    def listed(ids: list[int]) -> list[dict]:
        # By name, so the list does not reshuffle itself between visits.
        return sorted(
            (cards[user_id] for user_id in ids if user_id in cards),
            key=lambda card: card["username"],
        )

    return {
        "friends": listed(friends),
        "pending_in": listed(pending_in),
        # Read from the names, never from the friendships: a declined invite is
        # still listed here, and so is a name nobody answers to. The caller
        # learns nothing they did not type.
        "pending_out": [{"username": name} for name in fellowship.outbound_names(db, user.id)],
    }


@router.post("/friends/{user_id}/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_friend(
    user_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Say yes to an invite somebody sent you."""
    if throttle.friend_action_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_ACTIONS)
    row = db.execute(
        select(models.Friendship).where(
            models.Friendship.requester_id == user_id,
            models.Friendship.addressee_id == user.id,
            models.Friendship.status == "pending",
        )
    ).scalar_one_or_none()
    if row is None:
        # Nothing to accept, whether because it was never sent, was already
        # accepted, or was withdrawn.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No invite from that account.")
    row.status = "accepted"
    row.responded_at = security.now_utc()
    inviter = db.get(models.User, user_id)
    if inviter is not None:
        # The name comes off both sent lists. The inviter's is the one the
        # contract names; the other is for the pair who invited each other, where
        # only one invite could be accepted and the second would otherwise sit on
        # its sender's screen for good, waiting on somebody already a friend.
        fellowship.forget_outbound(db, inviter.id, user.username)
        fellowship.forget_outbound(db, user.id, inviter.username)
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.delete("/friends/invites/{username}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_invite(
    username: str,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Take back an invite you sent, by the name you sent it to.

    By name rather than by id because a name is all the sent list carries, and
    that is the point of it: the caller cancels what they typed. 204 whatever
    happens, for the invite form's own reason. Only the invite this account sent
    is touched: an invite waiting on you is declined with the verb below, and
    an accepted friendship is ended there too.
    """
    if throttle.friend_action_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_ACTIONS)
    wanted = username.strip().lower()
    fellowship.forget_outbound(db, user.id, wanted)
    other = db.execute(
        select(models.User.id).where(models.User.username == wanted)
    ).scalar_one_or_none()
    if other is not None:
        db.execute(
            delete(models.Friendship).where(
                models.Friendship.requester_id == user.id,
                models.Friendship.addressee_id == other,
                models.Friendship.status == "pending",
            )
        )
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.delete("/friends/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_friend(
    user_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Decline an invite or stop being friends.

    One verb for the two, and 204 even when there was nothing there: the caller
    asked for these two accounts to have nothing between them, and afterwards
    they do not. Withdrawing one you sent is the endpoint above, because that
    one is answered by a name rather than by an id.

    The sent list is left exactly as it is. Declining used to take a name off
    it, which meant the sender could watch a name disappear and read that as an
    answer; a decline is now invisible, which is the answer the person declining
    was giving.
    """
    if throttle.friend_action_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_ACTIONS)
    fellowship.unlink(db, user.id, user_id)
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/feed")
def read_feed(
    before: str | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> list[dict]:
    """Your workouts and your friends', newest first.

    Swept first, so a sync that landed a moment ago is on the page rather than
    waiting for the profile to be looked at. Paged by the same cursor the
    history uses: the start time of the last row on the page.
    """
    if throttle.feed_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, throttle.TOO_MANY_READS)
    progress.process_user(db, user.id)
    visible = fellowship.friend_ids(db, user.id) | {user.id}

    stmt = select(models.Workout).where(models.Workout.user_id.in_(visible))
    if before:
        stmt = stmt.where(models.Workout.start_ts < parse_cursor(before))
    rows = list(
        db.execute(
            # By id within a timestamp, so two workouts sharing a start time
            # keep a stable order between pages.
            stmt.order_by(models.Workout.start_ts.desc(), models.Workout.id.desc()).limit(
                FEED_PAGE_SIZE
            )
        ).scalars()
    )

    earned = medals.medals_for(db, rows)
    routed = routes_for(db, rows)
    pictures = photos_for(db, rows)
    people = fellowship.people(db, {row.user_id for row in rows})
    counts = fellowship.counts(db, [row.id for row in rows], user.id)
    # Asked of the owners on this page, not of the reader: what a row shows is
    # decided by whoever did the workout.
    kept_back = fellowship.hidden_fields(db, {row.user_id for row in rows})
    return [
        fellowship.feed_row(
            row,
            people[row.user_id],
            row.user_id == user.id,
            earned.get(row.id, []),
            row.id in routed,
            pictures.get(row.id, []),
            counts[row.id],
            kept_back.get(row.user_id, ()),
        )
        for row in rows
        if row.user_id in people
    ]
