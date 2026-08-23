"""Push: where a device subscribes, and the one notification a sync sends."""

import base64
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException

from app import config, models, push, security
from conftest import make_user
from test_ingest import export, post, workout
from test_steps import TODAY, reading, sync

SUBSCRIPTION = {
    "endpoint": "https://push.example.com/send/abc123",
    "keys": {"p256dh": "browser-point", "auth": "browser-secret"},
}

# 39 minutes 12 seconds, so the body's clock form is pinned exactly.
RUN = workout("Outdoor Run", "2026-07-20T05:54:00+00:00", 2352.0, 4.21, 350, 150)


@pytest.fixture()
def vapid(monkeypatch) -> str:
    """A real keypair in settings, the way a configured install has one."""
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.private_numbers().private_value.to_bytes(32, "big")
    private = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    monkeypatch.setattr(config.settings, "vapid_private_key", private)
    monkeypatch.setattr(config.settings, "vapid_subject", "mailto:push@example.com")
    return private


@pytest.fixture()
def sent(monkeypatch) -> list[dict]:
    """Every send the app attempted, captured where the delivery would start."""
    calls: list[dict] = []
    monkeypatch.setattr(push, "webpush", lambda **kwargs: calls.append(kwargs))
    return calls


def subscribed(client) -> None:
    assert client.post("/api/push/subscriptions", json=SUBSCRIPTION).status_code == 204


def test_no_keypair_means_no_push(signed_in, sent, ingest_token):
    assert signed_in.get("/api/push/key").status_code == 404
    assert signed_in.post("/api/push/subscriptions", json=SUBSCRIPTION).status_code == 404
    # A phone that subscribed before the keys were removed stays silent too.
    assert post(signed_in, ingest_token, export(RUN)).status_code == 200
    assert sent == []


def test_the_key_is_derived_from_the_private_one(client, vapid):
    answer = client.get("/api/push/key")
    assert answer.status_code == 200
    key = answer.json()["key"]
    # A base64url uncompressed P-256 point is 65 bytes and starts with 0x04.
    point = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
    assert len(point) == 65 and point[0] == 4


def test_a_device_subscribes_and_unsubscribes(signed_in, db_session, member, vapid):
    subscribed(signed_in)
    row = db_session.query(models.PushSubscription).one()
    assert (row.user_id, row.p256dh, row.auth) == (member.id, "browser-point", "browser-secret")

    body = {"endpoint": SUBSCRIPTION["endpoint"]}
    assert signed_in.request("DELETE", "/api/push/subscriptions", json=body).status_code == 204
    assert db_session.query(models.PushSubscription).count() == 0
    # Turning off a device that was already off asks for the state there is.
    assert signed_in.request("DELETE", "/api/push/subscriptions", json=body).status_code == 204


def test_an_endpoint_is_not_a_url_essay(signed_in, vapid):
    body = {"endpoint": "http://push.example.com/plain", "keys": SUBSCRIPTION["keys"]}
    assert signed_in.post("/api/push/subscriptions", json=body).status_code == 400


def test_a_resubscribe_follows_whoever_is_signed_in(signed_in, db_session, member, vapid):
    """One endpoint is one device; the account signed in on it owns the row."""
    other = make_user(db_session, "someoneelse", "password-someoneelse")
    db_session.add(
        models.PushSubscription(
            user_id=other.id,
            endpoint=SUBSCRIPTION["endpoint"],
            p256dh="old-point",
            auth="old-secret",
            created_at=member.created_at,
        )
    )
    db_session.commit()

    subscribed(signed_in)
    row = db_session.query(models.PushSubscription).one()
    assert (row.user_id, row.p256dh) == (member.id, "browser-point")


def test_a_stranger_cannot_turn_off_your_device(signed_in, db_session, member, vapid):
    other = make_user(db_session, "someoneelse", "password-someoneelse")
    db_session.add(
        models.PushSubscription(
            user_id=other.id,
            endpoint="https://push.example.com/send/theirs",
            p256dh="p",
            auth="a",
            created_at=member.created_at,
        )
    )
    db_session.commit()

    body = {"endpoint": "https://push.example.com/send/theirs"}
    assert signed_in.request("DELETE", "/api/push/subscriptions", json=body).status_code == 204
    assert db_session.query(models.PushSubscription).count() == 1


def test_a_new_workout_notifies_every_subscribed_device(
    signed_in, ingest_token, vapid, sent
):
    subscribed(signed_in)
    assert post(signed_in, ingest_token, export(RUN)).json()["imported"] == 1

    assert len(sent) == 1
    assert sent[0]["subscription_info"] == SUBSCRIPTION
    assert json.loads(sent[0]["data"]) == {
        "title": "secondmile",
        "body": "Your 5:54 AM run is in. 4.21 mi in 39:12.",
    }


def test_a_repeat_sync_stays_silent(signed_in, ingest_token, vapid, sent):
    subscribed(signed_in)
    post(signed_in, ingest_token, export(RUN))
    # The overlapping export every later sync carries: nothing new, no buzz.
    assert post(signed_in, ingest_token, export(RUN)).json()["imported"] == 0
    assert len(sent) == 1


def test_steps_never_notify(signed_in, ingest_token, vapid, sent):
    subscribed(signed_in)
    assert sync(signed_in, ingest_token, metrics=reading(TODAY, steps=8000)).status_code == 200
    assert sent == []


def test_the_account_switch_silences_every_device(signed_in, ingest_token, vapid, sent):
    subscribed(signed_in)
    answer = signed_in.patch("/api/settings", json={"notify_workout_arrival": False})
    assert answer.json()["notify_workout_arrival"] is False
    assert signed_in.get("/api/auth/me").json()["notify_workout_arrival"] is False

    post(signed_in, ingest_token, export(RUN))
    assert sent == []


def test_one_sync_with_two_workouts_is_one_notification(
    signed_in, ingest_token, vapid, sent
):
    subscribed(signed_in)
    walk = workout("Outdoor Walk", "2026-07-20T07:10:00+00:00", 1500.0, 2.1, 150, 110)
    post(signed_in, ingest_token, export(RUN, walk))

    assert len(sent) == 1
    assert json.loads(sent[0]["data"])["body"] == "2 workouts are in. 6.3 mi total."


def test_a_gone_device_is_forgotten(
    signed_in, ingest_token, db_session, member, vapid, monkeypatch
):
    subscribed(signed_in)

    def gone(**kwargs):
        raise WebPushException("gone", response=SimpleNamespace(status_code=410))

    monkeypatch.setattr(push, "webpush", gone)
    # The suite's one in-memory database has one connection, so a second
    # session would collide with the open one; the prune borrows it instead.
    monkeypatch.setattr(push, "session_factory", lambda: db_session)
    post(signed_in, ingest_token, export(RUN))
    assert db_session.query(models.PushSubscription).count() == 0


def test_the_body_reads_in_the_account_units():
    arrivals = [
        {
            "activity": "run",
            "start": "2026-07-20T05:54:00+00:00",
            "duration_s": 2352.0,
            "distance_mi": 4.21,
        }
    ]
    assert push.arrival_body(arrivals, "metric") == "Your 5:54 AM run is in. 6.78 km in 39:12."


def test_the_clock_form_grows_hours_when_it_needs_them():
    arrivals = [
        {
            "activity": "cycle",
            "start": "2026-07-20T14:05:00+00:00",
            "duration_s": 3725.0,
            "distance_mi": 20.0,
        }
    ]
    assert push.arrival_body(arrivals, "imperial") == "Your 2:05 PM cycle is in. 20.00 mi in 1:02:05."


def test_a_test_send_reports_how_many_devices_took_it(
    signed_in, db_session, member, vapid, sent
):
    """The button exists so somebody with a silent phone gets a real answer."""
    for index in (1, 2):
        db_session.add(
            models.PushSubscription(
                user_id=member.id,
                endpoint=f"https://push.example.com/{index}",
                p256dh="key",
                auth="auth",
                created_at=security.now_utc(),
            )
        )
    db_session.commit()

    response = signed_in.post("/api/push/test")
    assert response.status_code == 200
    assert response.json() == {"sent": 2, "removed": 0}
    assert len(sent) == 2


def test_a_test_send_with_no_devices_answers_zero(signed_in, member, vapid, sent):
    """Zero is the reading that tells somebody to turn the switch back on."""
    assert signed_in.post("/api/push/test").json() == {"sent": 0, "removed": 0}
    assert sent == []


def test_a_test_send_forgets_a_device_the_service_gave_up_on(
    signed_in, db_session, member, vapid, monkeypatch
):
    """A gone device is dropped on the way past and is not counted as sent."""
    db_session.add(
        models.PushSubscription(
            user_id=member.id,
            endpoint="https://push.example.com/gone",
            p256dh="key",
            auth="auth",
            created_at=security.now_utc(),
        )
    )
    db_session.commit()

    def gone(**kwargs):
        raise WebPushException("gone", response=SimpleNamespace(status_code=410))

    monkeypatch.setattr(push, "webpush", gone)
    monkeypatch.setattr(push, "session_factory", lambda: db_session)

    assert signed_in.post("/api/push/test").json() == {"sent": 0, "removed": 1}
    assert db_session.query(models.PushSubscription).count() == 0


def test_a_test_send_needs_a_configured_server(signed_in):
    """Without a keypair the whole feature is off, and it says so."""
    assert signed_in.post("/api/push/test").status_code == 404
