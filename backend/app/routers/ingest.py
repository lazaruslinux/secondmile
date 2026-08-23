"""The sync endpoint the phone posts workout exports to."""

import datetime as dt
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import (
    activity,
    gear,
    healthconnect,
    history,
    models,
    progress,
    push,
    routemaps,
    samples,
    security,
    stamps,
    throttle,
)
from app.config import (
    BACKFILL_WINDOW_DAYS,
    INGEST_LOG_RETENTION_DAYS,
    MAX_INGEST_METRIC_POINTS,
    MAX_INGEST_WORKOUTS,
    SERVER_TZ,
)
from app.db import get_db

router = APIRouter(tags=["ingest"])

TOO_OLD = "before this account's backfill window"


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


def _inside_window(
    user: models.User,
    parsed: list[activity.ParsedWorkout],
    metrics: dict[dt.date, activity.DayMetrics],
) -> tuple[list[activity.ParsedWorkout], dict[dt.date, activity.DayMetrics], list[dict]]:
    """What this account may import out of one export, and one refusal for each
    thing that is older than it may.

    The window runs from BACKFILL_WINDOW_DAYS before the account was created,
    and it is anchored there rather than to now on purpose: a member who joined
    today cannot import a decade of somebody's exports, and a member offline for
    a month after joining still syncs every day of it.

    Refused and counted rather than raised. An export reaching further back than
    the window is what a first sync looks like on a phone with years on it, and
    it is not an error.

    Reads the payload and nothing else. No stored row is ever reconsidered by
    this: what is already in the history stays exactly as it is.
    """
    opened = user.created_at - dt.timedelta(days=BACKFILL_WINDOW_DAYS)
    first_day = opened.astimezone(SERVER_TZ).date()
    refused: list[dict] = []
    kept = []
    for item in parsed:
        if item.start_ts < opened:
            refused.append({"start": item.start_ts.isoformat(), "reason": TOO_OLD})
            continue
        kept.append(item)
    days = {}
    for day, reading in metrics.items():
        if day < first_day:
            refused.append({"day": day.isoformat(), "reason": TOO_OLD})
            continue
        days[day] = reading
    return kept, days, refused


@router.post("/ingest")
async def ingest(
    request: Request, background: BackgroundTasks, db: Session = Depends(get_db)
) -> dict:
    # The limiter runs before the token check so that guessing tokens costs the
    # same allowance as anything else from that address.
    if throttle.ingest_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many syncs just now. Wait a minute.")

    user = ingest_user(request, db)

    raw = await request.body()
    try:
        payload = json.loads(raw, parse_constant=_refuse_constant)
    except (ValueError, RecursionError):
        # Nothing is logged in this case: the payload column is JSON, so there
        # is nowhere to put a body that is not JSON in the first place.
        # JSONDecodeError, UnicodeDecodeError, and the refusal above are all
        # ValueError, so one clause covers every way the body can be unreadable.
        # RecursionError joins them because the parser runs out of stack on a
        # body nested deep enough, and that is the same unreadable body rather
        # than a fault of the server's: without this it escapes as a 500.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body must be JSON.") from None

    # An Android export describes the same morning in a different shape, so it is
    # turned into the one every reader below expects before any of them sees it.
    # What arrived is held onto for the log at the end: the translation is this
    # app's reading of somebody else's payload, and when a reading turns out to be
    # wrong the payload itself is the only thing that can say so.
    exported = payload
    if healthconnect.looks_like(payload):
        payload = healthconnect.translate(payload)

    # Counted before anything is parsed, so an export with a million entries
    # costs one length check rather than a million savepoints.
    entries = activity.workout_entries(payload)
    if entries is not None and len(entries) > MAX_INGEST_WORKOUTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Too many workouts in one export.")
    if activity.metric_points(payload) > MAX_INGEST_METRIC_POINTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Too many health metrics in one export.")

    parsed, ignored = activity.parse_payload(payload)
    # The pedometer's own readings, read here and stored below with the rest of
    # the sync. They earn nothing: steps are stored and shown, and that is all.
    metrics, metric_refusals = activity.parse_metrics(payload)
    ignored += metric_refusals

    # Anything older than this account's backfill window, dropped here and
    # counted with the other refusals. The tombstone and dedupe rules below are
    # untouched by it: this decides what is offered, not what is already stored.
    parsed, metrics, too_old = _inside_window(user, parsed, metrics)
    ignored += too_old

    # The default pair, read once for the export. New walks and runs are
    # recorded in it, as far as the pair itself says they are; a ride, a swim and
    # a step reading never are.
    #
    # Here rather than in the crediting pipeline on purpose. This is the only
    # place a workout is born, so "new" means exactly what it says: a rebuild or
    # a recompute walks the same history again and must never write a shoe over
    # a choice somebody made on an old activity.
    default_pair = gear.default_pair(db, user.id)

    imported = skipped = flagged = routes = minutes = 0
    # What the phone gets told about below, gathered from the rows that were
    # genuinely born here: a skipped duplicate is old news, never announced.
    arrivals: list[dict] = []
    # The rows themselves as well as the lines about them: the standings below
    # are read off the workouts, and an export can carry a week in any order.
    landed: list[models.Workout] = []
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
            indoor=item.indoor,
            gear_id=(
                default_pair.id
                if default_pair is not None and gear.takes(default_pair, item.activity)
                else None
            ),
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
        arrivals.append(
            {
                "activity": item.activity,
                "start": item.start_ts.isoformat(),
                "duration_s": item.duration_s,
                "distance_mi": item.distance_mi,
            }
        )
        if workout.flags:
            flagged += 1
        if routemaps.store_route(db, workout.id, item.route):
            routes += 1
        # The rest of what the entry said, on the row that was just born and on
        # no other. A duplicate above never reaches this line, which is what
        # keeps a re-synced session from being described twice: the same reason
        # the arrivals list is gathered here rather than from the parse.
        minutes += samples.record(db, workout, item.entry)
        landed.append(workout)

    # After the whole loop rather than inside it, and after the minutes are
    # written, which is what the standings are read from: every workout in this
    # export has to be in the table before any of them can be told what it came
    # after. Written once and never revisited - see app.stamps.
    stamped = stamps.stamp(db, user.id, landed)

    # In the same transaction as the workouts above, and worth nothing beside
    # them: the day rows are written for the screens that print them.
    step_days = progress.record_steps(db, user.id, metrics, security.now_utc())

    result = {"imported": imported, "skipped": skipped, "flagged": flagged, "ignored": len(ignored)}

    # Stripped here and not earlier: every route above has already been read out
    # of the payload and drawn, trimmed, into workout_routes, so what goes into
    # the log is the export minus the one thing in it that says where this
    # person lives.
    #
    # The export as it arrived rather than as it was read: for an Apple sync the
    # two are the same object, and for an Android one this keeps what the bridge
    # actually sent, which is what a mapping mistake has to be diagnosed from. A
    # Health Connect payload carries no route, so there is nothing in it to strip.
    payload = activity.without_routes(exported)
    db.add(
        models.IngestLog(
            user_id=user.id,
            received_at=security.now_utc(),
            payload=payload,
            # The log keeps what the response has no room for: why entries were
            # dropped, how many routes were drawn, how many minutes of detail
            # were kept, and how many days of steps were written. None of the
            # four is in the response, whose shape is a frozen contract and
            # which the phone does nothing with. A
            # sync that quietly drops half an export is otherwise impossible to
            # diagnose after the fact.
            result={
                **result,
                "ignored_detail": ignored,
                "routes_stored": routes,
                "samples_stored": minutes,
                "step_days": step_days,
                "pr_stamps": stamped,
            },
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

    # Told after the commit and the crediting above, so the workout a phone
    # buzzes about is already in the feed when its owner taps through. The
    # send itself runs after the response: a slow push service costs the
    # notification some seconds, never the sync.
    if arrivals and user.notify_workout_arrival and push.configured():
        subscriptions = [
            (row.id, row.endpoint, row.p256dh, row.auth)
            for row in db.execute(
                select(models.PushSubscription).where(
                    models.PushSubscription.user_id == user.id
                )
            ).scalars()
        ]
        if subscriptions:
            payload = {"title": "secondmile", "body": push.arrival_body(arrivals, user.units)}
            background.add_task(push.deliver, subscriptions, payload)
    return result
