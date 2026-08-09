"""Friends, the invites between them, and the feed they share.

Everything here answers as little as it can. An invite says nothing about
whether the name existed, the friends list carries no counts, and a feed row
for somebody else's workout holds the headline and nothing behind it: no heart
rate, no calories, no flags, and no experience. What a friend sees is what a
friend would be told at the door.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import fellowship, medals, models, progress, security, throttle
from app.activity import converted_miles
from app.db import get_db
from app.routers.workouts import parse_cursor, photos_for, routes_for

router = APIRouter(tags=["fellowship"])

# One page of the feed. Fixed rather than asked for: the home screen is the
# only thing that reads it, and a cursor is how it goes further back.
FEED_PAGE_SIZE = 20


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
    """
    if throttle.invite_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many invites. Wait a minute.")
    wanted = body.username.strip().lower()
    if wanted == user.username:
        # The one refusal worth making out loud. It leaks nothing: the caller
        # already knows their own name.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot invite yourself.")

    other = db.execute(
        select(models.User).where(models.User.username == wanted)
    ).scalar_one_or_none()
    if other is not None and other.id != user.id and fellowship.link(db, user.id, other.id) is None:
        try:
            with db.begin_nested():
                db.add(
                    models.Friendship(
                        requester_id=user.id,
                        addressee_id=other.id,
                        status="pending",
                        created_at=security.now_utc(),
                    )
                )
                db.flush()
            db.commit()
        except IntegrityError:
            # Two invites racing each other. The first one stands and this one
            # is the no-op it would have been a moment later.
            db.rollback()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/friends")
def list_friends(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    """Who you are friends with, and the invites waiting either way.

    No counts anywhere, here or anywhere else: how many friends somebody has is
    not a number this game keeps.
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
    friends, pending_in, pending_out = [], [], []
    for row in rows:
        other_id = row.addressee_id if row.requester_id == user.id else row.requester_id
        if row.status == "accepted":
            friends.append(other_id)
        elif row.addressee_id == user.id:
            pending_in.append(other_id)
        else:
            pending_out.append(other_id)

    cards = fellowship.people(db, friends + pending_in + pending_out)

    def listed(ids: list[int]) -> list[dict]:
        # By name, so the list does not reshuffle itself between visits.
        return sorted(
            (cards[user_id] for user_id in ids if user_id in cards),
            key=lambda card: card["username"],
        )

    return {
        "friends": listed(friends),
        "pending_in": listed(pending_in),
        "pending_out": listed(pending_out),
    }


@router.post("/friends/{user_id}/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_friend(
    user_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Say yes to an invite somebody sent you."""
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
    """Decline an invite, withdraw one, or stop being friends.

    One verb for the three, and 204 even when there was nothing there: the
    caller asked for these two accounts to have nothing between them, and
    afterwards they do not.
    """
    fellowship.unlink(db, user.id, user_id)
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


def feed_row(
    workout: models.Workout,
    person: dict,
    own: bool,
    medal_ids: list[str],
    has_route: bool,
    photo_ids: list[int],
    encouragement: dict,
) -> dict:
    """One feed event.

    Named rather than private because the friend profile serves these same
    rows, and this function is the only place the rule below is written down.
    A second copy of it is a copy somebody can edit on its own.

    Distance and duration and nothing finer. A friend's row deliberately
    carries no heart rate, no calories, no flags, and no pace field: the feed
    says what somebody did, not how their body was doing while they did it.
    Experience is on your own rows only, for the same reason.

    The title, the post, and the photos are the exception, and they are on a
    friend's row in full. Nothing here is inferred from a body: it is what the
    person chose to say, and writing it is the act of sharing it.
    """
    row = {
        "workout_id": workout.id,
        "user": person,
        "activity": workout.activity,
        "start_ts": workout.start_ts.isoformat(),
        "distance_mi": round(workout.distance_mi, 3),
        "duration_s": workout.duration_s,
        "medals": medal_ids,
        "has_route": has_route,
        "title": workout.title,
        "post": workout.post,
        "photos": photo_ids,
        "source": workout.source,
        "own": own,
    }
    if own:
        row["xp"] = round(converted_miles(workout.activity, workout.distance_mi), 2)
    row["encouragement"] = encouragement
    return row


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
    return [
        feed_row(
            row,
            people[row.user_id],
            row.user_id == user.id,
            earned.get(row.id, []),
            row.id in routed,
            pictures.get(row.id, []),
            counts[row.id],
        )
        for row in rows
        if row.user_id in people
    ]
