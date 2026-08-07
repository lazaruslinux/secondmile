"""Registration, sign in, sign out, and password changes."""

import datetime as dt

from conftest import MEMBER, make_invite

from app import models, security
from app.config import APP_VERSION


def test_status_is_public(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    # Read from config rather than written out again: this endpoint exists to
    # report the version the build is running, and a literal here only ever
    # fails the suite one commit after a bump.
    assert response.json() == {
        "name": "secondmile",
        "version": APP_VERSION,
        "registration_open": False,
    }


def test_register_with_invite_asks_for_verification(client, invite, outbox):
    response = client.post(
        "/api/auth/register",
        json={
            "invite_code": invite.code,
            "username": "newcomer",
            "email": "newcomer@example.com",
            "password": "long-enough-1",
        },
    )
    assert response.status_code == 201
    assert response.json() == {"detail": "Check your email to verify your account."}
    # No session comes back: the account still has to answer its mail.
    assert client.cookies.get("session") is None
    assert client.get("/api/auth/me").status_code == 401
    assert outbox[0][0] == "newcomer@example.com"


def test_register_rejects_unknown_invite(client, admin):
    response = client.post(
        "/api/auth/register",
        json={
            "invite_code": "no-such-code",
            "username": "newcomer",
            "email": "newcomer@example.com",
            "password": "long-enough-1",
        },
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Invite code is not valid."}


def test_invite_works_once(client, invite, outbox):
    first = client.post(
        "/api/auth/register",
        json={
            "invite_code": invite.code,
            "username": "first",
            "email": "first@example.com",
            "password": "long-enough-1",
        },
    )
    assert first.status_code == 201
    second = client.post(
        "/api/auth/register",
        json={
            "invite_code": invite.code,
            "username": "second",
            "email": "second@example.com",
            "password": "long-enough-1",
        },
    )
    assert second.status_code == 400


def test_expired_invite_is_refused(client, db_session, admin):
    stale = make_invite(db_session, admin.id, days=14)
    stale.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
    db_session.commit()
    response = client.post(
        "/api/auth/register",
        json={
            "invite_code": stale.code,
            "username": "latecomer",
            "email": "latecomer@example.com",
            "password": "long-enough-1",
        },
    )
    assert response.status_code == 400


def test_register_enforces_username_and_password_rules(client, invite):
    bad_name = client.post(
        "/api/auth/register",
        json={
            "invite_code": invite.code,
            "username": "No Spaces",
            "email": "spaces@example.com",
            "password": "long-enough-1",
        },
    )
    assert bad_name.status_code == 400

    short_password = client.post(
        "/api/auth/register",
        json={
            "invite_code": invite.code,
            "username": "shorty",
            "email": "shorty@example.com",
            "password": "tooshort",
        },
    )
    assert short_password.status_code == 400


def test_register_refuses_a_password_nobody_typed(client, invite, db_session):
    """Argon2 will hash a megabyte as willingly as a passphrase, and charge the
    server for every byte of it."""
    response = client.post(
        "/api/auth/register",
        json={
            "invite_code": invite.code,
            "username": "longwinded",
            "email": "longwinded@example.com",
            "password": "a" * (security.MAX_PASSWORD_LENGTH + 1),
        },
    )
    assert response.status_code == 400
    assert "at most" in response.json()["detail"]
    assert db_session.query(models.User).filter_by(username="longwinded").count() == 0


def test_a_password_at_the_length_cap_is_still_accepted(client, invite, outbox):
    response = client.post(
        "/api/auth/register",
        json={
            "invite_code": invite.code,
            "username": "atthecap",
            "email": "atthecap@example.com",
            "password": "a" * security.MAX_PASSWORD_LENGTH,
        },
    )
    assert response.status_code == 201


def test_password_change_refuses_one_over_the_length_cap(signed_in):
    response = signed_in.post(
        "/api/auth/password",
        json={
            "current_password": MEMBER["password"],
            "new_password": "a" * (security.MAX_PASSWORD_LENGTH + 1),
        },
    )
    assert response.status_code == 400
    assert "at most" in response.json()["detail"]


def test_login_logout_round_trip(client, member):
    assert client.get("/api/auth/me").status_code == 401

    login = client.post("/api/auth/login", json=MEMBER)
    assert login.status_code == 204
    assert client.get("/api/auth/me").json()["username"] == MEMBER["username"]

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_login_rejects_wrong_password(client, member):
    response = client.post(
        "/api/auth/login", json={"username": MEMBER["username"], "password": "wrong-password-1"}
    )
    assert response.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_session_row_is_gone_after_logout(client, db_session, member):
    from app import models

    client.post("/api/auth/login", json=MEMBER)
    assert db_session.query(models.UserSession).count() == 1
    client.post("/api/auth/logout")
    assert db_session.query(models.UserSession).count() == 0


def test_expired_session_is_refused_and_reaped(client, db_session, member):
    from app import models

    client.post("/api/auth/login", json=MEMBER)
    row = db_session.query(models.UserSession).one()
    row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    db_session.commit()

    assert client.get("/api/auth/me").status_code == 401
    assert db_session.query(models.UserSession).count() == 0


def test_password_change_kills_other_sessions(client, db_session, member):
    from app import models

    # A second sign in stands in for another browser or another device.
    other = client.post("/api/auth/login", json=MEMBER)
    assert other.status_code == 204
    stale_cookie = client.cookies.get("session")

    client.cookies.clear()
    client.post("/api/auth/login", json=MEMBER)
    assert db_session.query(models.UserSession).count() == 2

    changed = client.post(
        "/api/auth/password",
        json={"current_password": MEMBER["password"], "new_password": "brand-new-password-1"},
    )
    assert changed.status_code == 204
    assert db_session.query(models.UserSession).count() == 1

    # The session that made the change still works; the other one does not.
    assert client.get("/api/auth/me").status_code == 200
    client.cookies.clear()
    client.cookies.set("session", stale_cookie)
    assert client.get("/api/auth/me").status_code == 401


def test_password_change_needs_the_current_password(signed_in):
    response = signed_in.post(
        "/api/auth/password",
        json={"current_password": "not-it-at-all", "new_password": "brand-new-password-1"},
    )
    assert response.status_code == 403


def test_password_change_enforces_length(signed_in):
    response = signed_in.post(
        "/api/auth/password",
        json={"current_password": MEMBER["password"], "new_password": "short"},
    )
    assert response.status_code == 400


def test_new_password_is_the_one_that_works(client, member):
    client.post("/api/auth/login", json=MEMBER)
    client.post(
        "/api/auth/password",
        json={"current_password": MEMBER["password"], "new_password": "brand-new-password-1"},
    )
    client.post("/api/auth/logout")

    assert client.post("/api/auth/login", json=MEMBER).status_code == 401
    fresh = client.post(
        "/api/auth/login",
        json={"username": MEMBER["username"], "password": "brand-new-password-1"},
    )
    assert fresh.status_code == 204


def test_login_burst_is_rate_limited(client, member):
    wrong = {"username": MEMBER["username"], "password": "wrong-password-1"}
    codes = [client.post("/api/auth/login", json=wrong).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429
    # The limit is on attempts, not on failures: the correct password is refused
    # too while the window is still full.
    assert client.post("/api/auth/login", json=MEMBER).status_code == 429


def test_register_burst_is_rate_limited(client, admin, db_session):
    body = {
        "invite_code": "nope",
        "username": "someone",
        "email": "someone@example.com",
        "password": "long-enough-1",
    }
    codes = [client.post("/api/auth/register", json=body).status_code for _ in range(6)]
    assert codes[:5] == [400] * 5
    assert codes[5] == 429


def test_malformed_body_gets_the_standard_error_shape(client):
    response = client.post("/api/auth/login", json={"username": "only-a-name"})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
