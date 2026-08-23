"""The profile: the trophy room, its picture, its medal slots, and the catalogue."""

import datetime as dt
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

from app import activity as activity_rules
from app import (
    avatars,
    fellowship,
    gear,
    grove,
    images,
    medals,
    models,
    progress,
    security,
    stamps,
    throttle,
)
from app.config import MAX_AVATAR_BYTES, MAX_DIAMOND_SPORTS, MAX_DISPLAYED_BADGES, SERVER_TZ
from app.db import get_db
from app.models import ACTIVITIES
from app.fellowship import feed_row
from app.routers.workouts import photos_for, routes_for, videos_for

router = APIRouter(tags=["profile"])

TOO_LARGE = (
    "That picture is too large. "
    f"The limit is {MAX_AVATAR_BYTES // (1024 * 1024)} MB."
)

MAX_NAME_LENGTH = 40
# What a bio may run to. Enough for a line or two under a name on either
# profile screen, which is where it is read; the column is the same length.
MAX_BIO_LENGTH = 200
# The two the edit form offers. The API takes these and nothing else, so what is
# stored can always be shown by the dropdown that wrote it.
GENDERS = ("Male", "Female")
# Old enough for anybody alive, and a floor that catches the typed year that
# lost a digit. A birthdate is only ever used to work out an age.
EARLIEST_BIRTHDATE = dt.date(1900, 1, 1)


class ProfileBody(BaseModel):
    """A patch: only the fields that are sent are changed.

    Every field here takes an explicit null, which is how each one is cleared,
    so whether it was sent is read from the model's field set rather than from
    its value. Badge slots are the exception: null has no meaning for them, so
    an omitted one and a null one both leave the slots alone.
    """

    displayed_badges: list[str] | None = None
    diamond_sports: list[str] | None = None
    first_name: str | None = None
    last_name: str | None = None
    # A plain string, parsed below, so a date that is not one is answered with
    # the same sentence-shaped 400 as everything else here rather than with the
    # framework's field report.
    birthdate: str | None = None
    gender: str | None = None
    bio: str | None = None


def computed_age(birthdate: dt.date | None, today: dt.date | None = None) -> int | None:
    """Full years lived, or null for an account that has not given a birthdate.

    Worked out on every read rather than stored, which is the whole reason there
    is no age column: a stored age is right for one year and wrong afterwards.
    """
    if birthdate is None:
        return None
    # The instance's day, not the container's: an age should turn over when the
    # people reading it say it does.
    day = today or security.now_utc().astimezone(SERVER_TZ).date()
    had_birthday = (day.month, day.day) >= (birthdate.month, birthdate.day)
    return day.year - birthdate.year - (0 if had_birthday else 1)


def _clean_text(sent: str | None, limit: int, what: str) -> str | None:
    """One optional text field: trimmed, length checked, and blank means clear.

    A field somebody has emptied and one they never filled in are the same
    thing, so an empty string is stored as null rather than as an empty string
    that every reader would then have to treat as null anyway.
    """
    if sent is None:
        return None
    cleaned = sent.strip()
    if len(cleaned) > limit:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{what} must be at most {limit} characters."
        )
    return cleaned or None


def _clean_gender(sent: str | None) -> str | None:
    """One of the two offered choices, or null once emptied.

    A closed set rather than the free text this took before, so nothing reaches
    the column that the edit form could not have put there.
    """
    if sent is None:
        return None
    cleaned = sent.strip()
    if not cleaned:
        return None
    if cleaned not in GENDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Gender must be Male or Female.")
    return cleaned


def _clean_birthdate(sent: str | None) -> dt.date | None:
    if sent is None or not sent.strip():
        return None
    try:
        value = dt.date.fromisoformat(sent.strip())
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That is not a date. Use YYYY-MM-DD."
        ) from None
    if value >= security.now_utc().astimezone(SERVER_TZ).date():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A birthdate has to be in the past.")
    if value <= EARLIEST_BIRTHDATE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That birthdate is too long ago.")
    return value


def serialize_profile(db: Session, user: models.User, row: models.UserProgress) -> dict:
    """Everything the profile screen needs in one response."""
    level, into_level, level_span = progress.level_bounds(row.xp)
    gifts = grove.pending_gift_names(db, user.id)
    monday = activity_rules.week_start(security.now_utc())
    return {
        "user_id": user.id,
        "username": user.username,
        # The name they go by, in halves and joined. Null in all three places
        # for an account that has given neither half.
        "first_name": user.first_name,
        "last_name": user.last_name,
        "display_name": fellowship.display_name(user.first_name, user.last_name),
        "birthdate": user.birthdate.isoformat() if user.birthdate else None,
        # Derived from the birthdate on every read, never stored beside it.
        "age": computed_age(user.birthdate),
        "gender": user.gender,
        # What they wrote about themselves, or null. Not private: this rides
        # the friend payload too, and the edit form says so.
        "bio": user.bio,
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
        # The whole catalogue, unearned rows included, with a count on each.
        # The stars a client draws are that count and nothing stored.
        "medals": medals.medal_summary(db, user.id),
        # The effective list, never the stored one: the client renders diamonds
        # and should not have to work out what null means.
        "diamond_sports": progress.diamond_sports(db, user.id, user.diamond_sports),
        "streak_weeks": progress.streak_weeks(db, user.id),
        # Which days of this week already carry a workout, Monday first. Worked
        # out here rather than on the client, so the diamonds under the streak
        # are bucketed by the same instance-timezone Monday the streak itself is
        # counted over, and so they stop depending on how far the feed has been
        # scrolled.
        "week_days": progress.week_days(db, user.id),
        "week": progress.week_totals(db, user.id, monday),
        "lifetime": progress.lifetime_totals(db, user.id),
        # The raw count, this week. Beside the two tables and in neither of
        # them, and in no miles figure anywhere: steps are not a sport and not
        # a mile, and this line is the whole of what the app makes of them.
        # Only ever on your own profile, because what a pedometer saw is
        # ambient life rather than something done, and a friend has no business
        # reading it.
        "week_steps": progress.step_count(db, user.id, monday),
        # What the calories have come to: the bank, one number, spendable and
        # permanent. Own screen only, and never on the friend payload.
        "manna": row.manna,
        # How much is in the plot and how much of it is grown. Not a
        # collection: there is no total to fill, only what somebody planted.
        "grove": grove.summary(db, user.id),
        # Oil and water, spent and arrived. Counts only, the same four on the
        # friend payload: a tally of giving, not a record of it.
        "item_tallies": grove.item_tallies(db, user.id),
        # The shoes and the miles on them. Maintenance rather than game: no
        # number here is in any total on this payload, and nothing in the game
        # reads one. The owner's copy carries the three things only they need:
        # what a pair started at, when they mean to replace it, and which pair
        # new walks and runs are recorded in.
        "gear": gear.gear_list(db, user.id, own=True),
        # Which chest is coming and how far off it is, so the banner can say
        # so without asking a second endpoint, and whose oil is on it.
        "next_chest": progress.next_chest(row, gifts),
        # Every gift still waiting, oldest first. One waiting while
        # next_chest.gifted_by is null is one the next chest has no room for:
        # it is not lost, it is holding out for a chest it can lift.
        "pending_gifts": [{"from": name} for name in gifts],
        # When this account's phone last posted, so Home can say something when
        # a sync has stopped arriving. Own-only by construction: a friend is
        # served by serialize_friend_profile, whose shape is the allowlist, and
        # this line is not in it. Null for an account that has never synced.
        "last_sync_at": (
            stamp.isoformat()
            if (stamp := activity_rules.last_sync_at(db, user.id)) is not None
            else None
        ),
    }


@router.get("/profile")
def read_profile(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    """The whole profile, after sweeping anything that arrived since last time."""
    if throttle.profile_read_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, throttle.TOO_MANY_READS)
    return serialize_profile(db, user, progress.process_user(db, user.id))


def _set_badges(db: Session, user: models.User, sent: list[str]) -> None:
    """Checked against what the account actually owns; this function is the only
    thing enforcing that. Every family shares the slots."""
    chosen = [str(value) for value in sent]
    if len(chosen) > MAX_DISPLAYED_BADGES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"There are only {MAX_DISPLAYED_BADGES} medal slots.",
        )
    if len(set(chosen)) != len(chosen):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A medal cannot fill two slots.")
    owned = medals.earned_medal_ids(db, user.id)
    for badge in chosen:
        if badge not in owned:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "You have not earned that medal."
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
    """Choose which badges sit in the slots, which sports wear diamonds, and
    what this account calls itself.

    Sending a field as null clears it, which is why a sent null and an omitted
    field have to be told apart: the first is somebody deleting their birthdate
    and the second is somebody saving a different part of the form.
    """
    if throttle.profile_edit_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many edits just now. Wait a minute.")
    if body.displayed_badges is not None:
        _set_badges(db, user, body.displayed_badges)
    if "diamond_sports" in body.model_fields_set:
        _set_diamonds(user, body.diamond_sports)
    if "first_name" in body.model_fields_set:
        user.first_name = _clean_text(body.first_name, MAX_NAME_LENGTH, "A first name")
    if "last_name" in body.model_fields_set:
        user.last_name = _clean_text(body.last_name, MAX_NAME_LENGTH, "A last name")
    if "birthdate" in body.model_fields_set:
        user.birthdate = _clean_birthdate(body.birthdate)
    if "gender" in body.model_fields_set:
        user.gender = _clean_gender(body.gender)
    if "bio" in body.model_fields_set:
        user.bio = _clean_text(body.bio, MAX_BIO_LENGTH, "A bio")
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
    if throttle.avatar_limiter.hit(throttle.user_key(user)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many uploads just now. Wait a minute."
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
    except images.RejectedImage as exc:
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
    if throttle.delete_media_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many changes just now. Wait a minute.")
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
    """Serve one member's picture to any other member of this instance.

    The gate is the session and nothing narrower, and that follows the club:
    every member may look one another up by name and read the card that comes
    back, and a card with the face cut out of it is not the card the instance
    agreed to serve. The narrower rule this replaced -- yourself, your friends,
    and whoever you had invited -- was shaped around an app with no way to find
    anybody, and there is one now.

    An account with no picture, and an id nobody owns, are the same 404, so
    this still cannot be asked which ids are real. Behind a session in all
    cases: an unauthenticated URL returning a photograph invites hotlinking,
    and a photograph is the one thing here worth hotlinking.
    """
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


# --------------------------------------------------------------------------
# Somebody else's profile
# --------------------------------------------------------------------------

# How much of a friend's history the screen carries. Four rather than the feed's
# twenty because this is a glance at how somebody is doing rather than their
# history, and there is no cursor here to ask for more.
FRIEND_WORKOUTS = 4

# How many pictures the strip across the profile holds. Six because that is
# what one workout may carry, which makes it one number rather than two.
RECENT_PHOTOS = 6


def _hidden_for(user: models.User, viewer_id: int) -> tuple[str, ...]:
    """What this account keeps back from whoever is reading it.

    Nothing is kept back when the two are the same person. This endpoint
    answers about yourself as well, and a hidden field is something an account
    said about its friends rather than about itself. Written once because two
    places on this screen honour the list and two copies of a privacy rule are
    two things to remember to edit.
    """
    return () if viewer_id == user.id else tuple(user.hidden_from_friends or [])


def _shown_totals(totals: dict[str, dict], hidden: tuple[str, ...]) -> dict[str, dict]:
    """Per-activity totals with the calories taken out where they are hidden.

    A hidden field is dropped from the row rather than sent as a zero: a zero
    would say they burned nothing, which is a different thing from being asked
    not to look. Distance and time stay whatever the list says, the same way
    they stay on a workout card.
    """
    if "active_kcal" not in hidden:
        return totals
    return {
        activity: {key: value for key, value in row.items() if key != "active_kcal"}
        for activity, row in totals.items()
    }


def _recent_photos(db: Session, user_id: int) -> list[dict]:
    """The last few pictures this account attached to a workout, newest first.

    The strip is media rather than history, so the order is the order they were
    added in rather than the order the workouts happened in: a picture put on
    last week's run today is the newest thing there is to look at. Each one
    carries the workout it belongs to and the two figures the tag under it
    prints; the picture itself is fetched from the workout photo endpoint,
    which is friend-gated exactly as this screen is.
    """
    rows = db.execute(
        select(
            models.WorkoutPhoto.id,
            models.Workout.id,
            models.Workout.activity,
            models.Workout.indoor,
            models.Workout.distance_mi,
            models.Workout.duration_s,
        )
        .join(models.Workout, models.Workout.id == models.WorkoutPhoto.workout_id)
        # A picture on a deleted workout is not on the strip: the endpoint that
        # serves it answers 404 now, so a tile here would draw a hole. One on a
        # workout taken off the feeds goes the same way and for the same
        # reason, and this screen is only ever read by a friend.
        .where(
            models.Workout.user_id == user_id,
            models.Workout.deleted_at.is_(None),
            models.Workout.hidden_from_feed.is_(False),
        )
        # By id within a stamp, so two pictures uploaded in the same second
        # keep a stable order between reads.
        .order_by(models.WorkoutPhoto.created_at.desc(), models.WorkoutPhoto.id.desc())
        .limit(RECENT_PHOTOS)
    ).all()
    return [
        {
            "photo_id": photo_id,
            "workout_id": workout_id,
            "activity": activity,
            # The tag under the picture wears the sport mark, so it needs the
            # same qualifier every other row that draws one carries.
            "indoor": indoor,
            "distance_mi": round(distance_mi, 3),
            "duration_s": duration_s,
        }
        for photo_id, workout_id, activity, indoor, distance_mi, duration_s in rows
    ]


def _friend_workouts(db: Session, user: models.User, viewer_id: int) -> list[dict]:
    """Their last few workouts, in the feed's own row shape.

    Built by the feed's serializer rather than by a second one written here.
    That function is where the rule lives about what somebody else's row may
    carry, and two copies of a privacy rule are two things to remember to edit.
    The lookups around it are batched the way the feed batches them: a page of
    rows is a handful of queries, never one each.

    Nothing is kept back when these are somebody's own workouts on their own
    profile; see _hidden_for. A workout taken off the feeds is the exception,
    and it is out of this list for everybody, the owner reading their own
    profile included: the feed's rule is the feed's rule wherever the rows are
    drawn. Its own history still has it.
    """
    hidden = _hidden_for(user, viewer_id)
    rows = list(
        db.execute(
            select(models.Workout)
            .where(
                models.Workout.user_id == user.id,
                models.Workout.deleted_at.is_(None),
                models.Workout.hidden_from_feed.is_(False),
            )
            # By id within a timestamp, the feed's own tie-break, so two
            # workouts sharing a start time keep a stable order between reads.
            .order_by(models.Workout.start_ts.desc(), models.Workout.id.desc())
            .limit(FRIEND_WORKOUTS)
        ).scalars()
    )
    if not rows:
        return []
    earned = medals.medals_for(db, rows)
    routed = routes_for(db, rows)
    pictures = photos_for(db, rows)
    clips = videos_for(db, rows)
    card = fellowship.people(db, [user.id])[user.id]
    encouragement = fellowship.counts(db, [row.id for row in rows], viewer_id)
    placed = stamps.for_workouts(db, [row.id for row in rows])
    return [
        feed_row(
            row,
            card,
            # Never your own, even on your own profile: an own row carries the
            # experience it earned, and no experience is sent from here at all.
            False,
            earned.get(row.id, []),
            row.id in routed,
            pictures.get(row.id, []),
            clips.get(row.id, []),
            encouragement[row.id],
            hidden,
            placed.get(row.id),
        )
        for row in rows
    ]


def serialize_friend_profile(db: Session, user: models.User, viewer_id: int) -> dict:
    """What one account may see of another: who they are and how they are doing.

    Written out separately rather than as serialize_profile with a flag on it,
    and that is the point of the whole endpoint. The other one carries a
    birthdate, an age, a gender, the chest ladder and every gift waiting on it,
    and a boolean deciding which of those to drop is one careless edit away
    from sending them all. The shape of this function IS the allowlist: a field
    reaches a friend because somebody typed it here.

    What their workouts carry is the feed's rule, honouring whatever this
    account has asked to keep back; see feed_row.
    """
    row = db.get(models.UserProgress, user.id)
    # Read as it stands rather than swept first. Sweeping credits workouts,
    # drops chests and awards medals, and none of that is something one
    # account's curiosity should do to another's game. A friend's level is
    # already read this way everywhere else a friend appears.
    xp = row.xp if row else 0.0
    level, into_level, level_span = progress.level_bounds(xp)
    totals = progress.lifetime_totals(db, user.id)
    hidden = _hidden_for(user, viewer_id)
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": fellowship.display_name(user.first_name, user.last_name),
        # What they wrote about themselves. The one piece of free text on an
        # account a friend reads, and it is written to be read.
        "bio": user.bio,
        "has_avatar": user.avatar_path is not None,
        "avatar_version": avatars.version(user.id) if user.avatar_path else None,
        "created_at": user.created_at.isoformat(),
        "border_tier": progress.border_tier(level),
        "flourish": fellowship.flourish_stage(row.renown if row else 0),
        "displayed_badges": list(user.displayed_badges or []),
        "level": level,
        # The ladder, as the You screen draws it: how far up they are and how
        # far into the rung they stand. This screen mirrors that screen, so the
        # meter under the level is filled from the same three numbers under the
        # same names. Rounded here because the client prints them.
        "xp": round(xp, 2),
        "xp_into_level": round(into_level, 2),
        "xp_for_next_level": round(level_span, 2),
        # Raw distance and never the converted number the ladder is climbed on:
        # a swim of half a mile is half a mile of somebody's body moving, and
        # this line is the one that says how far. One decimal, which is what
        # the screen prints. Workouts only, here as everywhere: a mile is the
        # work put into a recorded activity, and no pedometer reading is in it.
        "miles": round(sum(total["distance_mi"] for total in totals.values()), 1),
        "medals": medals.medal_summary(db, user.id),
        # The summary only. The plot itself is GET /api/grove/{user_id}, which
        # the same screen already calls, and serving it twice would mean two
        # places to remember when what a friend sees of a garden changes.
        "grove": grove.summary(db, user.id),
        # The same four counts the You screen carries. Aggregates with nobody
        # named in them, and the oil column only moves once a gift has landed,
        # so this says how much somebody gives without telling anybody who.
        "item_tallies": grove.item_tallies(db, user.id),
        # Their shoes, size and width included. Deliberate: reading what a
        # friend wears is the whole reason a friend sees gear at all. What a
        # pair started at, when they mean to replace it, and which is their
        # default stay behind; see gear.serialize.
        "gear": gear.gear_list(db, user.id, own=False),
        # The same two cards the You screen carries, in the same shape, so the
        # sport chips and the tables are drawn from one payload rather than
        # worked out twice. The calories come out of both where they are
        # hidden: a week total is a calorie figure like any other.
        "week": _shown_totals(
            progress.week_totals(
                db, user.id, activity_rules.week_start(security.now_utc())
            ),
            hidden,
        ),
        "lifetime": _shown_totals(totals, hidden),
        # The strip across the profile: their last few pictures, newest first.
        "recent_photos": _recent_photos(db, user.id),
        "workouts": _friend_workouts(db, user, viewer_id),
    }


def serialize_member_card(db: Session, user: models.User, viewer_id: int) -> dict:
    """What one member may see of another they are not friends with.

    A third serializer rather than either of the other two with a flag on it,
    and for the reason the second one exists: a boolean deciding which fields
    to drop is one careless edit away from sending all of them. The shape of
    this function IS the allowlist, and it is short on purpose. A name, a face
    in its frame, a line they wrote about themselves, and the month they
    joined. Everything the game keeps -- the level, the miles, the medals, the
    grove, the workouts -- stays behind friendship, where it has always been.

    The frame and the flourish come along because they are how a person is
    drawn everywhere in this app, on a feed row and in a friends list alike.
    The medals do not: those are things somebody earned, and earning is the
    part a friend gets to look at.
    """
    row = db.get(models.UserProgress, user.id)
    level, _, _ = progress.level_bounds(row.xp if row else 0.0)
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": fellowship.display_name(user.first_name, user.last_name),
        "has_avatar": user.avatar_path is not None,
        "avatar_version": avatars.version(user.id) if user.avatar_path else None,
        "border_tier": progress.border_tier(level),
        "flourish": fellowship.flourish_stage(row.renown if row else 0),
        "bio": user.bio,
        "created_at": user.created_at.isoformat(),
        # Said outright rather than left to be inferred from which keys are
        # missing: the screen draws a different card, and it should know that
        # from the payload rather than from the absence of one.
        "restricted": True,
        "friendship": friendship_state(db, user.id, viewer_id),
    }


def friendship_state(db: Session, user_id: int, viewer_id: int) -> str:
    """Where these two accounts stand, in one word the button can read.

    Only ever asked about a pair the caller is one half of, so nothing here
    tells anybody about anyone else's invites. "friends" cannot appear on the
    profile card, which is served to non-friends only; it is here because the
    roster search serves the same card for people you already know.
    """
    if fellowship.are_friends(db, viewer_id, user_id):
        return "friends"
    if fellowship.invited(db, viewer_id, user_id):
        return "invited_by_me"
    if fellowship.invited(db, user_id, viewer_id):
        return "invited_me"
    return "none"


@router.get("/profile/{user_id}")
def read_friend_profile(
    user_id: int,
    db: Session = Depends(get_db),
    viewer: models.User = Depends(security.current_user),
) -> dict:
    """One person, seen from wherever the reader is standing.

    Three answers. Yourself and your friends get the whole thing. Another
    member of this instance gets the restricted card: a name, a face, a line,
    and a month, which is what the club decided a member may see of a member
    they have not met. An id nobody owns is the same 404 it always was, which
    is why this still cannot be asked whether a stranger is real.

    The 404 is now the only refusal, and it means one thing rather than two: no
    such account. A member who is not a friend used to take it as well, and
    that was the rule before the instance decided it was a private club and a
    roster you were let into rather than an index of the world.
    """
    person = db.get(models.User, user_id)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such friend.")
    if user_id != viewer.id and not fellowship.are_friends(db, viewer.id, user_id):
        return serialize_member_card(db, person, viewer.id)
    return serialize_friend_profile(db, person, viewer.id)
