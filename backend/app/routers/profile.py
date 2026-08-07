"""The profile: the trophy room, its picture, its badge slots, and the catalogue."""

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

# Straight from starlette: the multipart parser produces starlette's
# UploadFile, and an isinstance check against fastapi's subclass would refuse
# every real upload.
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from app import achievements
from app import activity as activity_rules
from app import avatars, fellowship, models, progress, security, throttle, world
from app.config import MAX_AVATAR_BYTES, MAX_DIAMOND_SPORTS, MAX_DISPLAYED_BADGES
from app.db import get_db
from app.models import ACTIVITIES

router = APIRouter(tags=["profile"])

TOO_LARGE = (
    "That picture is too large. "
    f"The limit is {MAX_AVATAR_BYTES // (1024 * 1024)} MB."
)


class ProfileBody(BaseModel):
    """A patch: only the fields that are sent are changed.

    diamond_sports takes an explicit null, which is the reset to the automatic
    pick, so whether it was sent is read from the model's field set rather than
    from its value. Badge slots have no meaning for null, so an omitted one and
    a null one both leave the slots alone.
    """

    displayed_badges: list[str] | None = None
    diamond_sports: list[str] | None = None


def serialize_profile(db: Session, user: models.User, row: models.UserProgress) -> dict:
    """Everything the profile screen needs in one response."""
    level, into_level, level_span = progress.level_bounds(row.xp)
    owned = progress.owned_card_count(db, user.id)
    return {
        "user_id": user.id,
        "username": user.username,
        "created_at": user.created_at.isoformat(),
        "has_avatar": user.avatar_path is not None,
        # Cache buster for GET /api/profile/avatar/<user_id>; null without one.
        "avatar_version": avatars.version(user.id) if user.avatar_path else None,
        "level": level,
        # Converted Miles, one for one, so these are distances rather than
        # scores. Rounded because the client prints them and a float summed
        # over hundreds of workouts otherwise arrives with a tail on it.
        "xp": round(row.xp, 2),
        "xp_into_level": round(into_level, 2),
        "xp_for_next_level": round(level_span, 2),
        "border_tier": progress.border_tier(level),
        # The stage only, never the renown behind it: every avatar frame draws
        # this, including your own, and the number is not something the game
        # shows anybody.
        "flourish": fellowship.flourish_stage(row.renown),
        "displayed_badges": list(user.displayed_badges or []),
        "race_badges": achievements.badge_summary(db, user.id, "race"),
        # The effective list, never the stored one: the client renders diamonds
        # and should not have to work out what null means.
        "diamond_sports": progress.diamond_sports(db, user.id, user.diamond_sports),
        "streak_weeks": progress.streak_weeks(db, user.id),
        "week": progress.week_totals(
            db, user.id, activity_rules.week_start(security.now_utc())
        ),
        "lifetime": progress.lifetime_totals(db, user.id),
        "cards": {"owned": owned, "total": len(world.CARDS)},
        "achievements": {
            "earned": achievements.earned_count(db, user.id),
            "total": len(achievements.CATALOG),
        },
    }


@router.get("/profile")
def read_profile(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    """The whole profile, after sweeping anything that arrived since last time."""
    return serialize_profile(db, user, progress.process_user(db, user.id))


def _set_badges(db: Session, user: models.User, sent: list[str]) -> None:
    """Checked against what the account actually owns; this function is the only
    thing enforcing that. Achievements and race badges share the slots."""
    chosen = [str(value) for value in sent]
    if len(chosen) > MAX_DISPLAYED_BADGES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"There are only {MAX_DISPLAYED_BADGES} badge slots.",
        )
    if len(set(chosen)) != len(chosen):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A badge cannot fill two slots.")
    owned = set(
        db.execute(
            select(models.UserAchievement.achievement_id).where(
                models.UserAchievement.user_id == user.id
            )
        ).scalars()
    ) | achievements.earned_badge_ids(db, user.id)
    for badge in chosen:
        if badge not in owned:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "You have not earned that badge."
            )
    user.displayed_badges = chosen


def _set_diamonds(user: models.User, sent: list[str] | None) -> None:
    """Null goes back to the automatic pick; a list is taken as the slot order."""
    if sent is None:
        user.diamond_sports = None
        return
    chosen = [str(value) for value in sent]
    if len(chosen) > MAX_DIAMOND_SPORTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"There are only {MAX_DIAMOND_SPORTS} diamond slots.",
        )
    if len(set(chosen)) != len(chosen):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A sport cannot fill two diamonds.")
    for sport in chosen:
        if sport not in ACTIVITIES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"A diamond must be one of: {', '.join(ACTIVITIES)}.",
            )
    user.diamond_sports = chosen


@router.patch("/profile")
def set_profile(
    body: ProfileBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Choose which badges sit in the slots and which sports wear diamonds."""
    if body.displayed_badges is not None:
        _set_badges(db, user, body.displayed_badges)
    if "diamond_sports" in body.model_fields_set:
        _set_diamonds(user, body.diamond_sports)
    db.commit()
    return serialize_profile(db, user, progress.ensure_progress(db, user.id))


@router.post("/profile/avatar")
async def upload_avatar(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Take a picture, store something the server made instead (app/avatars.py).

    The form is parsed by hand so the size cap sits in the parser itself: an
    oversized body is abandoned mid-stream, not spooled to disk and measured
    afterwards (an UploadFile parameter would spool first).
    """
    if throttle.avatar_limiter.hit(throttle.client_address(request)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many uploads. Wait a minute."
        )

    # Content-Length is a claim, checked first to refuse the obvious case
    # cheaply; the parser below enforces the same cap on the actual bytes.
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_AVATAR_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, TOO_LARGE)

    try:
        form = await request.form(
            max_files=1, max_fields=0, max_part_size=MAX_AVATAR_BYTES
        )
    except MultiPartException:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, TOO_LARGE) from None
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No picture was uploaded.")
        raw = await upload.read()
    finally:
        await form.close()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No picture was uploaded.")

    try:
        stored = avatars.store(user.id, raw)
    except avatars.RejectedImage as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    user.avatar_path = stored
    db.commit()
    return {"has_avatar": True, "avatar_version": avatars.version(user.id)}


@router.delete("/profile/avatar", status_code=status.HTTP_204_NO_CONTENT)
def delete_avatar(
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    avatars.remove(user.id)
    user.avatar_path = None
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/profile/avatar/{user_id}")
def read_avatar(
    user_id: int,
    db: Session = Depends(get_db),
    viewer: models.User = Depends(security.current_user),
) -> FileResponse:
    """Serve one account's picture to any signed-in player. Not public: an
    unauthenticated URL returning a photograph invites hotlinking."""
    owner = db.get(models.User, user_id)
    if owner is None or owner.avatar_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No picture.")
    stored = avatars.path_for(user_id)
    if not os.path.isfile(stored):
        # The row says there is a picture and the disk disagrees, which is what
        # a lost or unmounted volume looks like. Handing that to FileResponse
        # raises inside the response and answers 500; the same 404 as an account
        # with no picture is both the honest answer and the one that still says
        # nothing about which accounts exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No picture.")
    return FileResponse(
        stored,
        media_type=avatars.MEDIA_TYPE,
        headers={
            # Private: a shared cache must not hand one member's picture to
            # another request. The ?v= the client appends handles new uploads.
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/achievements")
def read_achievements(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> list[dict]:
    """The whole catalogue, in order, with what this account has done. Swept
    first so the list is never stale after a sync."""
    progress.process_user(db, user.id)
    held = {
        row.achievement_id: row
        for row in db.execute(
            select(models.UserAchievement).where(models.UserAchievement.user_id == user.id)
        ).scalars()
    }
    return [
        achievements.serialize(row, held.get(row.id)) for row in achievements.CATALOG
    ]
