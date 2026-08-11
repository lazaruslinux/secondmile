"""The sync endpoint the phone posts workout exports to."""

import datetime as dt
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import activity, history, models, progress, routemaps, security, throttle
from app.config import INGEST_LOG_RETENTION_DAYS, MAX_INGEST_WORKOUTS
from app.db import get_db

router = APIRouter(tags=["ingest"])


def _refuse_constant(literal: str) -> float:
    """Called by json.loads for a bare NaN, Infinity, or -Infinity.

    Python's parser accepts all three even though no other JSON reader has to,
    and the payload column is stored verbatim, so one of them reaching the
    database is a row Postgres cannot write back out. Refusing here turns it
    into the same 400 any other unreadable body gets.
    """
    raise ValueError(f"{literal} is not a number this endpoint accepts")


def ingest_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    """The account behind the Authorization bearer token.

    A bearer token rather than the session cookie because the poster is an
    automation on a phone that cannot answer an interactive login, and because
    the endpoint has to keep working when the rest of the site sits behind a
    forward-auth layer.
    """
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid ingest token")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized
    row = db.execute(
        select(models.IngestToken).where(
            models.IngestToken.token_hash == security.hash_token(token.strip())
        )
    ).scalar_one_or_none()
    if row is None:
        raise unauthorized
    user = db.get(models.User, row.user_id)
    if user is None:
        raise unauthorized
    return user


@router.post("/ingest")
async def ingest(request: Request, db: Session = Depends(get_db)) -> dict:
    # The limiter runs before the token check so that guessing tokens costs the
    # same allowance as anything else from that address.
    if throttle.ingest_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many syncs just now. Wait a minute.")

    user = ingest_user(request, db)

    raw = await request.body()
    try:
        payload = json.loads(raw, parse_constant=_refuse_constant)
    except ValueError:
        # Nothing is logged in this case: the payload column is JSON, so there
        # is nowhere to put a body that is not JSON in the first place.
        # JSONDecodeError, UnicodeDecodeError, and the refusal above are all
        # ValueError, so one clause covers every way the body can be unreadable.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body must be JSON.") from None

    # Counted before anything is parsed, so an export with a million entries
    # costs one length check rather than a million savepoints.
    entries = activity.workout_entries(payload)
    if entries is not None and len(entries) > MAX_INGEST_WORKOUTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Too many workouts in one export.")

    parsed, ignored = activity.parse_payload(payload)

    imported = skipped = flagged = routes = 0
    for item in parsed:
        flags = {}
        if activity.impossible_pace(item.activity, item.duration_s, item.distance_mi):
            flags["impossible_pace"] = True
        workout = models.Workout(
            user_id=user.id,
            activity=item.activity,
            start_ts=item.start_ts,
            duration_s=item.duration_s,
            distance_mi=item.distance_mi,
            active_kcal=item.active_kcal,
            avg_hr=item.avg_hr,
            source="sync",
            flags=flags,
            created_at=security.now_utc(),
        )
        try:
            # Each row gets its own savepoint. A duplicate raises inside it and
            # rolls back only that row, so one already-known workout in a
            # thousand does not abort the whole export the way a single
            # transaction would.
            with db.begin_nested():
                db.add(workout)
                db.flush()
        except IntegrityError:
            # A workout already known keeps the route it already has. Re-writing
            # it would be work for no change, and this is the common case: every
            # overlapping export window arrives full of them.
            skipped += 1
            continue

        # Checked after the insert so the workout being judged is included in
        # the day's total.
        if activity.over_daily_cap(db, user.id, item.activity, item.start_ts):
            workout.flags = {**flags, "daily_cap": True}
        imported += 1
        if workout.flags:
            flagged += 1
        if routemaps.store_route(db, workout.id, item.route):
            routes += 1

    result = {"imported": imported, "skipped": skipped, "flagged": flagged, "ignored": len(ignored)}

    # Stripped here and not earlier: every route above has already been read out
    # of the payload and drawn, trimmed, into workout_routes, so what goes into
    # the log is the export minus the one thing in it that says where this
    # person lives.
    payload = activity.without_routes(payload)
    db.add(
        models.IngestLog(
            user_id=user.id,
            received_at=security.now_utc(),
            payload=payload,
            # The log keeps the reasons; the response keeps the count. A sync
            # that quietly drops half an export is otherwise impossible to
            # diagnose after the fact. The route tally rides here rather than in
            # the response because the response shape is a frozen contract and
            # nothing on the phone would do anything with the number.
            result={**result, "ignored_detail": ignored, "routes_stored": routes},
        )
    )

    # This account's expired logs, dropped on this account's own sync, in the
    # same transaction as the row that just arrived. Scoped per user so a
    # dormant account's cleanup never waits on somebody else's phone, and no
    # scheduled job has to exist for the table to stay bounded.
    db.execute(
        delete(models.IngestLog).where(
            models.IngestLog.user_id == user.id,
            models.IngestLog.received_at
            < security.now_utc() - dt.timedelta(days=INGEST_LOG_RETENTION_DAYS),
        )
    )

    # And the same bargain one table over: whatever this account deleted longer
    # ago than the window has its pictures, its video, its line and its words
    # taken away here, on this account's own sync and in this transaction. The
    # workout rows themselves stay. They are the tombstones the dedupe above
    # reads, which is why the export that just arrived carrying one of them
    # counted as skipped rather than importing it all over again.
    history.purge_expired(db, user.id)
    db.commit()

    # Credit whatever this sync brought in. Doing it here rather than only
    # when the app is next opened is what makes the recap a story that was
    # already written by the time anybody looks at it.
    progress.process_user(db, user.id)
    return result
