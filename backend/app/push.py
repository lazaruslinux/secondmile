"""Web push: one notification when a sync brings new workouts.

The server composes the whole notification here, so every device says the same
thing and the service worker stays a dumb pipe. Sends run in a background task
after the ingest transaction has committed: the workout is already in the feed
by the time any phone buzzes about it.
"""

import base64
import datetime as dt
import functools
import json
import logging

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush

from app import db, models
from app.config import SERVER_TZ, settings

log = logging.getLogger("secondmile.push")

# Mirrors the frontend's formatting exactly (format.ts), because this text sits
# on a lock screen beside the app that renders the same workout.
KM_PER_MILE = 1.609344

# How long a push service holds an undelivered notification for a phone that is
# off. A day: a sync announcement older than that is stale news.
TTL_SECONDS = 86400

# What one browser handed over at subscribe time, carried from the request that
# read it to the background task that spends it.
Subscription = tuple[int, str, str, str]  # (id, endpoint, p256dh, auth)

# How the pruning of dead subscriptions opens a database session of its own.
# A function the tests, which run without DATABASE_URL, replace to point at
# their engine.
def session_factory():
    return db.SessionLocal()


def configured() -> bool:
    return bool(settings.vapid_private_key and settings.vapid_subject)


@functools.lru_cache(maxsize=1)
def _public_key(private_key: str) -> str:
    """The base64url uncompressed point the browser needs, derived from the
    private key so the pair can never be configured out of step."""
    raw = base64.urlsafe_b64decode(private_key + "=" * (-len(private_key) % 4))
    key = ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
    point = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(point).rstrip(b"=").decode()


def public_key() -> str | None:
    return _public_key(settings.vapid_private_key) if configured() else None


def _clock(seconds: float) -> str:
    """The feed's clock form: 1:04:31, or 24:07 under an hour."""
    whole = max(0, round(seconds))
    hours, minutes, secs = whole // 3600, (whole % 3600) // 60, whole % 60
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _distance(miles: float, units: str, decimals: int) -> str:
    shown = miles * KM_PER_MILE if units == "metric" else miles
    return f"{shown:.{decimals}f} {'km' if units == 'metric' else 'mi'}"


def _start(ts: dt.datetime) -> str:
    local = ts.astimezone(SERVER_TZ)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def arrival_body(arrivals: list[dict], units: str) -> str:
    """The sentence under the title.

    One workout is announced by name; a sync that brought several is one
    notification rather than one per workout, because the phone it lands on is
    in a pocket, not a log file.
    """
    if len(arrivals) == 1:
        item = arrivals[0]
        when = _start(dt.datetime.fromisoformat(item["start"]))
        stats = f"{_distance(item['distance_mi'], units, 2)} in {_clock(item['duration_s'])}"
        return f"Your {when} {item['activity']} is in. {stats}."
    total = sum(item["distance_mi"] for item in arrivals)
    return f"{len(arrivals)} workouts are in. {_distance(total, units, 1)} total."


def deliver(subscriptions: list[Subscription], payload: dict) -> None:
    """Send one payload to every subscription, and forget the dead ones.

    Runs after the response is gone, so nothing here may raise: a push service
    outage costs the notification and a log line, never the sync.
    """
    data = json.dumps(payload)
    dead: list[int] = []
    for sub_id, endpoint, p256dh, auth in subscriptions:
        try:
            webpush(
                subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
                data=data,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
                ttl=TTL_SECONDS,
            )
        except WebPushException as exc:
            # 404 and 410 are the push service saying this device is gone for
            # good; anything else is weather, kept and retried next sync.
            status = exc.response.status_code if exc.response is not None else None
            if status in (404, 410):
                dead.append(sub_id)
            else:
                log.warning("push send failed (%s)", status or exc)
    if dead:
        session = session_factory()
        try:
            for sub_id in dead:
                row = session.get(models.PushSubscription, sub_id)
                if row is not None:
                    session.delete(row)
            session.commit()
        finally:
            session.close()
