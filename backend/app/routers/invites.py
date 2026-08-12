"""Invite links: minting them, listing them, taking them back, and the page
somebody who was sent one lands on.

Everything about a link is decided the moment it is minted. It works once, it
never expires on its own, and whoever minted it can take it back until it is
spent. The welcome page is the only unauthenticated thing here, and it answers
one shape for a live code and the same 404 for every dead one: claimed,
revoked, expired, and never minted are four different endings and one answer,
because a link that no longer works should not go on to say why.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import avatars, fellowship, models, progress, security, throttle
from app.db import get_db

router = APIRouter(tags=["invites"])

# What a code that no longer works is told, whichever way it stopped working.
# One sentence for the four endings, and the page prints it as it stands.
DEAD_LINK = "This invite link is not valid anymore."

# How many links one account may have waiting at once. Far more than anybody
# has people to invite, and low enough that the table is not somewhere to park
# a few thousand codes.
MAX_OPEN_LINKS = 50


def _live(db: Session, code: str) -> models.Invite | None:
    """The invite behind a code, if it is still worth anything.

    Claimed, revoked, and expired all read as nothing here, which is what makes
    the four dead cases answer identically further up: they never reach a
    branch that could tell them apart.
    """
    invite = db.execute(
        select(models.Invite).where(models.Invite.code == code)
    ).scalar_one_or_none()
    if invite is None or invite.used_by is not None or invite.revoked_at is not None:
        return None
    # Null means it never expires, which is every link minted in the app. A
    # date belongs to the codes the command line makes.
    if invite.expires_at is not None and invite.expires_at <= security.now_utc():
        return None
    return invite


def _link_row(db: Session, invite: models.Invite) -> dict:
    """One of your own links, as the settings screen lists it.

    The code travels because the row is the whole URL on screen and the client
    builds that from the address it was opened on, which is right for whoever
    is reading rather than for whoever installed the site. Who claimed it is a
    name rather than an id: it is there to be read, not to be tapped.
    """
    claimed_by = None
    if invite.used_by is not None:
        person = db.get(models.User, invite.used_by)
        if person is not None:
            claimed_by = fellowship.display_name(person.first_name, person.last_name) or (
                person.username
            )
    # No revoked state travels: revoking deletes the row, so a listed link is
    # either waiting or claimed.
    return {
        "id": invite.id,
        "code": invite.code,
        "created_at": invite.created_at.isoformat(),
        "claimed_by": claimed_by,
    }


@router.get("/invites")
def list_invites(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> list[dict]:
    """The links this account minted, newest first.

    Its own and nobody else's, codes included: a code is a credential, and the
    only person who has any business reading one is whoever is about to send
    it. The command line's codes are not here either, for the same reason the
    screen has no way to revoke them: they belong to whoever runs the server.
    """
    rows = list(
        db.execute(
            select(models.Invite)
            .where(models.Invite.created_by == user.id, models.Invite.auto_friend.is_(True))
            .order_by(models.Invite.created_at.desc(), models.Invite.id.desc())
        ).scalars()
    )
    return [_link_row(db, invite) for invite in rows]


@router.post("/invites", status_code=status.HTTP_201_CREATED)
def mint_invite(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    """Make a link that lets one person in, and makes the two of you friends.

    Never expires, because a link somebody texts to their brother is not a
    thing to put a clock on: it is spent the moment it is claimed, and that is
    the only ending it needs. Revocable until then, which is the answer to a
    link sent to the wrong number.
    """
    if throttle.invite_link_limiter.hit(throttle.user_key(user)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many links just now. Wait a minute."
        )
    waiting = db.execute(
        select(models.Invite).where(
            models.Invite.created_by == user.id,
            models.Invite.auto_friend.is_(True),
            models.Invite.used_by.is_(None),
            models.Invite.revoked_at.is_(None),
        )
    ).scalars()
    if len(list(waiting)) >= MAX_OPEN_LINKS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Too many links are waiting. Revoke one to make another.",
        )
    invite = models.Invite(
        code=security.generate_token(),
        created_by=user.id,
        created_at=security.now_utc(),
        # Null on purpose; see the docstring.
        expires_at=None,
        auto_friend=True,
    )
    db.add(invite)
    db.commit()
    return _link_row(db, invite)


@router.post("/invites/{invite_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(
    invite_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Take back a link before anybody spends it.

    Only your own, and only one that is still waiting: a claimed link has
    already done what it was for, and revoking it afterwards would say
    something about the account it let in rather than about the link. Anything
    else is the same 404 an id nobody minted gets.

    The row is deleted outright rather than stamped. An unclaimed link has no
    history worth keeping, and a dead row lingering in the Settings list reads
    as clutter; a deleted code answers the welcome page and the claim exactly
    the way a code nobody minted does, which is the answer it should give.
    """
    if throttle.friend_action_limiter.hit(throttle.user_key(user)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many changes just now. Wait a minute."
        )
    invite = db.get(models.Invite, invite_id)
    if (
        invite is None
        or invite.created_by != user.id
        or invite.used_by is not None
        or invite.revoked_at is not None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such link.")
    db.delete(invite)
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/invites/{code}/welcome")
def read_welcome(code: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """Who sent this link, for the page it opens. Signed out, deliberately.

    The one thing it says is the person who invited you, drawn the way that
    person is drawn everywhere else in the app. Nothing about the instance,
    nobody else on it, and no way to ask about anybody: the code is the whole
    of the question and it answers about exactly one account.

    A dead code and one that was never minted take the same branch to the same
    sentence. A code is sixty-odd characters of entropy, so guessing one is not
    the risk; the risk is a link somebody still holds becoming a way to learn
    that an account was created, or that somebody took the link back, and one
    answer for the four endings is what closes that.
    """
    if throttle.welcome_limiter.hit(throttle.client_address(request)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts just now. Wait a minute."
        )
    invite = _live(db, code.strip())
    inviter = None if invite is None else db.get(models.User, invite.created_by)
    if inviter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEAD_LINK)
    row = db.get(models.UserProgress, inviter.id)
    level, _, _ = progress.level_bounds(row.xp if row else 0.0)
    return {
        # Always a name: the composed one where they gave one, and the username
        # they signed up with otherwise. A card with no name on it is not a
        # card, and this is the whole of what the page has to introduce.
        "inviter_display_name": fellowship.display_name(inviter.first_name, inviter.last_name)
        or inviter.username,
        "inviter_has_avatar": inviter.avatar_path is not None,
        "inviter_avatar_version": avatars.version(inviter.id)
        if inviter.avatar_path
        else None,
        "inviter_border_tier": progress.border_tier(level),
        "inviter_flourish": fellowship.flourish_stage(row.renown if row else 0),
    }


@router.get("/invites/{code}/avatar")
def read_welcome_avatar(
    code: str, request: Request, db: Session = Depends(get_db)
) -> FileResponse:
    """The inviter's picture, for the welcome page to draw in its frame.

    Its own endpoint rather than the profile one, which is behind a session and
    stays there. What gates this is the code: whoever holds a live link was
    handed it by the person whose face this is, and that is the same permission
    the sentence above it rides on. Every dead code, and an inviter with no
    picture, is the same 404 the endpoint beside it gives.
    """
    if throttle.welcome_limiter.hit(throttle.client_address(request)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts just now. Wait a minute."
        )
    invite = _live(db, code.strip())
    inviter = None if invite is None else db.get(models.User, invite.created_by)
    if inviter is None or inviter.avatar_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEAD_LINK)
    stored = avatars.path_for(inviter.id)
    if not os.path.isfile(stored):
        # The row says there is a picture and the disk disagrees. The same 404,
        # for the reason the profile endpoint gives it: handing a missing path
        # to FileResponse raises inside the response and answers 500.
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEAD_LINK)
    return FileResponse(
        stored,
        media_type=avatars.MEDIA_TYPE,
        headers={
            # Public in the sense that no session is checked, private in the
            # sense that a shared cache has no business keeping it: the code in
            # the path is a credential.
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )
