"""The sync endpoint the phone posts workout exports to."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import activity, models, security, throttle
from app.db import get_db

router = APIRouter(tags=["ingest"])


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
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many syncs. Slow down.")

    user = ingest_user(request, db)

    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Nothing is logged in this case: the payload column is JSON, so there
        # is nowhere to put a body that is not JSON in the first place.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body must be JSON.") from None

    parsed, ignored = activity.parse_payload(payload)

    imported = skipped = flagged = 0
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
            skipped += 1
            continue

        # Checked after the insert so the workout being judged is included in
        # the day's total.
        if activity.over_daily_cap(db, user.id, item.activity, item.start_ts):
            workout.flags = {**flags, "daily_cap": True}
        imported += 1
        if workout.flags:
            flagged += 1

    result = {"imported": imported, "skipped": skipped, "flagged": flagged, "ignored": len(ignored)}
    db.add(
        models.IngestLog(
            user_id=user.id,
            received_at=security.now_utc(),
            payload=payload,
            # The log keeps the reasons; the response keeps the count. A sync
            # that quietly drops half an export is otherwise impossible to
            # diagnose after the fact.
            result={**result, "ignored_detail": ignored},
        )
    )
    db.commit()
    return result
