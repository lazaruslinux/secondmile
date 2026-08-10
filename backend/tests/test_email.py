"""Email signups: the verification round trip, and the things it must not leak."""

import argparse
import datetime as dt
import logging

import pytest
from fastapi.testclient import TestClient

from app import config, models, security
from app.main import app as fastapi_app
from conftest import make_invite, make_user

NEWCOMER = {
    "username": "newcomer",
    "email": "newcomer@example.com",
    "password": "long-enough-1",
}


def _register(client, invite=None, **overrides):
    body = {**NEWCOMER, **overrides}
    if invite is not None:
        body["invite_code"] = invite.code
    return client.post("/api/auth/register", json=body)


def _verify(client, token):
    return client.post("/api/auth/verify", json={"token": token})


def test_register_verify_then_sign_in(client, invite, outbox):
    assert _register(client, invite).status_code == 201
    address, token = outbox[0]
    assert address == NEWCOMER["email"]

    # Unverified, so the password alone is not enough yet.
    refused = client.post(
        "/api/auth/login", json={"username": "newcomer", "password": NEWCOMER["password"]}
    )
    assert refused.status_code == 403
    assert refused.json() == {"detail": "Email not verified."}

    assert _verify(client, token).status_code == 204
    signed_in = client.post(
        "/api/auth/login", json={"username": "newcomer", "password": NEWCOMER["password"]}
    )
    assert signed_in.status_code == 204
    me = client.get("/api/auth/me").json()
    assert me["email"] == NEWCOMER["email"]
    assert me["email_verified"] is True


def test_only_the_hash_of_a_verification_token_reaches_the_database(
    client, db_session, invite, outbox
):
    assert _register(client, invite).status_code == 201
    row = db_session.query(models.EmailToken).one()
    assert row.token_hash != outbox[0][1]
    assert row.token_hash == security.hash_token(outbox[0][1])
    assert row.purpose == "verify"


def test_open_registration_takes_no_invite(client, db_session, monkeypatch, outbox):
    monkeypatch.setattr(config.settings, "registration_open", True)
    response = client.post("/api/auth/register", json=NEWCOMER)
    assert response.status_code == 201
    assert db_session.query(models.User).filter_by(username="newcomer").count() == 1
    assert len(outbox) == 1


def test_closed_registration_still_needs_an_invite(client, outbox):
    response = client.post("/api/auth/register", json=NEWCOMER)
    assert response.status_code == 400
    assert outbox == []


def test_status_reports_the_registration_mode(client, monkeypatch):
    assert client.get("/api/status").json()["registration_open"] is False
    monkeypatch.setattr(config.settings, "registration_open", True)
    assert client.get("/api/status").json()["registration_open"] is True


def test_a_taken_name_or_address_looks_exactly_like_a_new_account(
    client, db_session, admin, outbox
):
    # A fresh invite for each attempt, so the second and third get as far as the
    # duplicate check rather than stopping at a spent code.
    first = _register(client, make_invite(db_session, admin.id))
    assert first.status_code == 201
    assert len(outbox) == 1

    taken_username = make_invite(db_session, admin.id)
    taken_email = make_invite(db_session, admin.id)
    same_username = _register(client, taken_username, email="different@example.com")
    same_email = _register(client, taken_email, username="different")

    for response in (same_username, same_email):
        assert response.status_code == first.status_code
        assert response.json() == first.json()
    # No second account, and no mail to the address someone else typed in.
    assert db_session.query(models.User).count() == 2  # the admin and the newcomer
    assert len(outbox) == 1
    # An attempt that created nothing does not spend a code either.
    assert taken_username.used_by is None
    assert taken_email.used_by is None


def test_a_wrong_password_on_an_unverified_account_is_still_a_generic_401(client, db_session):
    make_user(
        db_session, "waiting", "waiting-password-1", email="waiting@example.com", verified=False
    )

    wrong = client.post(
        "/api/auth/login", json={"username": "waiting", "password": "not-the-password-1"}
    )
    assert wrong.status_code == 401
    assert wrong.json() == {"detail": "Invalid username or password"}

    # Only the correct password reaches the verification check, so the pair of
    # answers cannot be used to test passwords against an unverified account.
    right = client.post(
        "/api/auth/login", json={"username": "waiting", "password": "waiting-password-1"}
    )
    assert right.status_code == 403


def test_a_verification_link_works_once(client, invite, outbox):
    assert _register(client, invite).status_code == 201
    token = outbox[0][1]
    assert _verify(client, token).status_code == 204
    assert _verify(client, token).status_code == 400


def test_an_expired_verification_link_is_refused_and_reaped(client, db_session, invite, outbox):
    assert _register(client, invite).status_code == 201
    row = db_session.query(models.EmailToken).one()
    row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    db_session.commit()

    assert _verify(client, outbox[0][1]).status_code == 400
    assert db_session.query(models.EmailToken).count() == 0
    assert db_session.query(models.User).filter_by(username="newcomer").one().email_verified is False


def test_an_unknown_verification_token_is_refused(client):
    assert _verify(client, "not-a-real-token").status_code == 400


def test_resend_answers_the_same_for_an_address_with_no_account(client, db_session, outbox):
    make_user(
        db_session, "waiting", "waiting-password-1", email="waiting@example.com", verified=False
    )

    unknown = client.post("/api/auth/resend-verification", json={"email": "nobody@example.com"})
    known = client.post("/api/auth/resend-verification", json={"email": "waiting@example.com"})
    assert unknown.status_code == known.status_code == 204
    # Same answer either way, and only the real unverified account is mailed.
    assert [address for address, _ in outbox] == ["waiting@example.com"]


def test_resend_sends_nothing_to_an_already_verified_account(client, db_session, outbox):
    make_user(db_session, "settled", "settled-password-1", email="settled@example.com")
    response = client.post("/api/auth/resend-verification", json={"email": "settled@example.com"})
    assert response.status_code == 204
    assert outbox == []


def test_a_resent_link_replaces_the_previous_one(client, db_session, invite, outbox):
    assert _register(client, invite).status_code == 201
    assert client.post(
        "/api/auth/resend-verification", json={"email": NEWCOMER["email"]}
    ).status_code == 204

    first_token, second_token = outbox[0][1], outbox[1][1]
    assert db_session.query(models.EmailToken).count() == 1
    assert _verify(client, first_token).status_code == 400
    assert _verify(client, second_token).status_code == 204


def test_resend_burst_is_rate_limited(client):
    body = {"email": "nobody@example.com"}
    codes = [
        client.post("/api/auth/resend-verification", json=body).status_code for _ in range(4)
    ]
    assert codes == [204, 204, 204, 429]


def test_verify_burst_is_rate_limited(client):
    codes = [_verify(client, "not-a-real-token").status_code for _ in range(11)]
    # The token is the only thing the endpoint checks, so guessing at it has to
    # cost an allowance like every other guess does.
    assert codes.count(400) == 10
    assert codes[-1] == 429


def test_register_rejects_an_address_that_is_not_one(client, invite, outbox):
    assert _register(client, invite, email="not-an-address").status_code == 400
    assert _register(client, invite, email="still@not@one").status_code == 400
    assert outbox == []


def test_an_address_is_stored_lower_case(client, db_session, invite, outbox):
    assert _register(client, invite, email="Newcomer@Example.COM").status_code == 201
    assert db_session.query(models.User).filter_by(username="newcomer").one().email == (
        "newcomer@example.com"
    )


def test_without_smtp_the_link_is_logged_instead(client, invite, caplog):
    """The documented no-mail setup. Note that outbox is deliberately not used
    here: this exercises the real send path with nowhere to send to."""
    with caplog.at_level(logging.WARNING, logger="secondmile.mail"):
        assert _register(client, invite).status_code == 201

    logged = [record for record in caplog.records if record.name == "secondmile.mail"]
    assert len(logged) == 1
    assert logged[0].levelno == logging.WARNING
    assert "/verify#token=" in logged[0].getMessage()
    assert NEWCOMER["email"] in logged[0].getMessage()


def test_admin_can_verify_an_account_from_the_command_line(client, db_session, monkeypatch):
    import manage

    user = make_user(
        db_session, "offline", "offline-password-1", email="offline@example.com", verified=False
    )
    monkeypatch.setattr(manage, "_session", lambda: db_session)
    manage.cmd_verify_email(argparse.Namespace(username="offline"))

    assert user.email_verified is True
    assert client.post(
        "/api/auth/login", json={"username": "offline", "password": "offline-password-1"}
    ).status_code == 204


def test_verify_email_refuses_an_unknown_account(db_session, monkeypatch):
    import manage

    monkeypatch.setattr(manage, "_session", lambda: db_session)
    with pytest.raises(SystemExit):
        manage.cmd_verify_email(argparse.Namespace(username="nobody"))


# --------------------------------------------------------------------------
# Adding or changing the address on an account
# --------------------------------------------------------------------------

# The member fixture's password, and an address nobody holds yet.
MEMBER_PASSWORD = "runner-password-1"
WANTED = "runner@example.com"


def _ask_for(client, email=WANTED, password=MEMBER_PASSWORD):
    return client.post("/api/settings/email", json={"password": password, "email": email})


def test_adding_an_address_waits_for_the_link_before_anything_moves(
    signed_in, db_session, member, change_outbox
):
    assert _ask_for(signed_in).status_code == 204

    # Nothing has moved yet: the address is only waiting.
    db_session.refresh(member)
    assert member.pending_email == WANTED
    assert member.email is None
    assert [address for address, _ in change_outbox] == [WANTED]
    assert signed_in.get("/api/auth/me").json()["pending_email"] == WANTED

    assert _verify(signed_in, change_outbox[0][1]).status_code == 204
    db_session.refresh(member)
    assert member.email == WANTED
    assert member.email_verified is True
    assert member.pending_email is None

    # Signed in again, because the swap took every session with it. See the
    # case below: this is the credential change it looks like.
    assert signed_in.post(
        "/api/auth/login", json={"username": member.username, "password": MEMBER_PASSWORD}
    ).status_code == 204
    me = signed_in.get("/api/auth/me").json()
    assert (me["email"], me["pending_email"]) == (WANTED, None)


def test_completing_a_change_of_address_revokes_every_session(
    signed_in, client, db_session, member, change_outbox
):
    """Moving an account to another inbox decides who the account answers to,
    so it is a credential event and every session dies with it, including the
    one that asked for the change."""
    # A second browser on the same account, to prove it is not only the caller's
    # own session that goes.
    elsewhere = TestClient(fastapi_app)
    assert elsewhere.post(
        "/api/auth/login", json={"username": member.username, "password": MEMBER_PASSWORD}
    ).status_code == 204

    assert _ask_for(signed_in).status_code == 204
    assert _verify(client, change_outbox[0][1]).status_code == 204

    assert db_session.query(models.UserSession).count() == 0
    assert signed_in.get("/api/auth/me").status_code == 401
    assert elsewhere.get("/api/auth/me").status_code == 401


def test_a_change_link_is_stored_as_a_hash_with_its_own_purpose(
    signed_in, db_session, member, change_outbox
):
    assert _ask_for(signed_in).status_code == 204
    row = db_session.query(models.EmailToken).one()
    assert row.purpose == "change-email"
    assert row.token_hash == security.hash_token(change_outbox[0][1])


def test_changing_the_address_needs_the_current_password(
    signed_in, db_session, member, change_outbox
):
    refused = _ask_for(signed_in, password="not-the-password-1")
    assert refused.status_code == 403
    assert refused.json() == {"detail": "Current password is not correct."}
    db_session.refresh(member)
    assert member.pending_email is None
    assert change_outbox == []


def test_an_address_another_account_holds_is_answered_exactly_the_same(
    signed_in, db_session, member, change_outbox
):
    make_user(db_session, "somebody", "somebody-password-1", email="taken@example.com")

    free = _ask_for(signed_in, email="free@example.com")
    taken = _ask_for(signed_in, email="taken@example.com")
    assert free.status_code == taken.status_code == 204
    assert free.content == taken.content
    # The second one stored nothing and mailed nobody: the person who really
    # owns that address hears nothing about a request they did not make.
    db_session.refresh(member)
    assert member.pending_email == "free@example.com"
    assert [address for address, _ in change_outbox] == ["free@example.com"]


def test_an_address_taken_while_the_link_was_waiting_cannot_be_swapped_in(
    signed_in, db_session, member, change_outbox
):
    assert _ask_for(signed_in).status_code == 204
    make_user(db_session, "quicker", "quicker-password-1", email=WANTED)

    refused = _verify(signed_in, change_outbox[0][1])
    assert refused.status_code == 400
    db_session.refresh(member)
    assert member.email is None
    # The request is spent either way, so the stale pending address does not sit
    # on the account waiting to be swapped in by a link that no longer exists.
    assert member.pending_email is None
    assert db_session.query(models.EmailToken).count() == 0


def test_only_one_address_may_be_waiting_at_a_time(
    signed_in, db_session, member, change_outbox
):
    assert _ask_for(signed_in, email="first@example.com").status_code == 204
    assert _ask_for(signed_in, email="second@example.com").status_code == 204
    assert db_session.query(models.EmailToken).count() == 1

    first_token, second_token = change_outbox[0][1], change_outbox[1][1]
    assert _verify(signed_in, first_token).status_code == 400
    assert _verify(signed_in, second_token).status_code == 204
    db_session.refresh(member)
    assert member.email == "second@example.com"


def test_the_address_form_refuses_something_that_is_not_an_address(
    signed_in, db_session, member, change_outbox
):
    assert _ask_for(signed_in, email="not-an-address").status_code == 400
    db_session.refresh(member)
    assert member.pending_email is None
    assert change_outbox == []


def test_a_changed_address_is_stored_lower_case(signed_in, db_session, member, change_outbox):
    assert _ask_for(signed_in, email="Runner@Example.COM").status_code == 204
    db_session.refresh(member)
    assert member.pending_email == WANTED


def test_address_changes_are_rate_limited(signed_in, change_outbox):
    codes = [_ask_for(signed_in, email=f"one{n}@example.com").status_code for n in range(4)]
    assert codes == [204, 204, 204, 429]


def test_without_smtp_the_change_link_is_logged_instead(signed_in, caplog):
    """The same no-mail setup the signup link has. change_outbox is deliberately
    not used here: this exercises the real send path with nowhere to send to."""
    with caplog.at_level(logging.WARNING, logger="secondmile.mail"):
        assert _ask_for(signed_in).status_code == 204

    logged = [record for record in caplog.records if record.name == "secondmile.mail"]
    assert len(logged) == 1
    message = logged[0].getMessage()
    # In the fragment, like every emailed link here, so no proxy log along the
    # way holds a working credential.
    assert "/verify#token=" in message
    assert "?token=" not in message
    assert WANTED in message


def test_changing_an_address_needs_a_session(client, member):
    assert client.post(
        "/api/settings/email", json={"password": MEMBER_PASSWORD, "email": WANTED}
    ).status_code == 401
