"""Where a device turns workout notifications on, and off again."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, push, security, throttle
from app.db import get_db

router = APIRouter(prefix="/push", tags=["push"])

# One sentence for every endpoint here when no keypair is configured: the
# feature is off server-wide, which is a supported way to run.
NOT_CONFIGURED = "Push is not set up on this server."


class Keys(BaseModel):
    p256dh: str = Field(max_length=255)
    auth: str = Field(max_length=255)


class SubscriptionBody(BaseModel):
    # Push services mint long URLs, but not unbounded ones; the cap keeps a
    # hostile client from storing an essay in the column.
    endpoint: str = Field(max_length=2048)
    keys: Keys


class EndpointBody(BaseModel):
    endpoint: str = Field(max_length=2048)


@router.get("/key")
def vapid_key() -> dict:
    """Public on purpose: the key is baked into every subscription a browser
    makes with it, so it was never a secret."""
    key = push.public_key()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_CONFIGURED)
    return {"key": key}


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def subscribe(
    body: SubscriptionBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> None:
    if not push.configured():
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_CONFIGURED)
    if throttle.push_subscribe_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many changes just now. Wait a minute.")
    if not body.endpoint.startswith("https://"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That is not a push endpoint.")
    row = db.execute(
        select(models.PushSubscription).where(models.PushSubscription.endpoint == body.endpoint)
    ).scalar_one_or_none()
    if row is None:
        row = models.PushSubscription(
            user_id=user.id,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            created_at=security.now_utc(),
        )
        db.add(row)
    else:
        # The push service minted this endpoint for one device, so whoever is
        # signed in on that device now is who it should notify: re-subscribing
        # moves the row rather than refusing it.
        row.user_id = user.id
        row.p256dh = body.keys.p256dh
        row.auth = body.keys.auth
    db.commit()


@router.post("/test")
def send_test(
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Send this account's devices one notification, now, and say what happened.

    Sent in the request rather than in a background task, which is the whole
    point: somebody staring at a silent phone needs the answer on the screen in
    front of them, and "the push service took it" and "that device is not
    registered any more" are the two answers they are trying to tell apart.

    Answers how many devices accepted it. A device the push service has given
    up on is dropped on the way past and is not counted, so a reading of zero
    means this account has nothing left to notify and the switch on this device
    wants turning on again.

    It does not, and cannot, promise the notification was shown. A phone with
    the app's notifications switched off at the operating system level takes
    delivery and displays nothing, and no server ever learns that.
    """
    if not push.configured():
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_CONFIGURED)
    if throttle.push_test_limiter.hit(throttle.user_key(user)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many tests just now. Wait a minute."
        )
    subscriptions = [
        (row.id, row.endpoint, row.p256dh, row.auth)
        for row in db.execute(
            select(models.PushSubscription).where(models.PushSubscription.user_id == user.id)
        ).scalars()
    ]
    if not subscriptions:
        return {"sent": 0, "removed": 0}
    sent, removed = push.deliver(
        subscriptions,
        {"title": "secondmile", "body": "Notifications are working on this device."},
    )
    return {"sent": sent, "removed": removed}


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(
    body: EndpointBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> None:
    """Idempotent: turning off a device that was already off is a 204, because
    the state asked for is the state there is."""
    if throttle.push_subscribe_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many changes just now. Wait a minute.")
    row = db.execute(
        select(models.PushSubscription).where(
            models.PushSubscription.endpoint == body.endpoint,
            models.PushSubscription.user_id == user.id,
        )
    ).scalar_one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()
