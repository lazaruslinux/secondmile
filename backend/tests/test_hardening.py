"""Checks on the properties that are easy to break and hard to notice."""

import os
import time

import pytest

from app import config, models, security, throttle
from conftest import ADMIN, MEMBER


def _set_cookie_header(response):
    for header, value in response.headers.raw:
        if header.decode().lower() == "set-cookie":
            return value.decode()
    raise AssertionError("no Set-Cookie header on the response")


def test_session_cookie_attributes(client, member):
    header = _set_cookie_header(client.post("/api/auth/login", json=MEMBER))
    lowered = header.lower()
    assert lowered.startswith("session=")
    assert "httponly" in lowered  # unreadable from JavaScript
    assert "samesite=lax" in lowered  # not attached to cross-site writes
    assert "path=/" in lowered
    assert "max-age=" in lowered


def test_secure_attribute_follows_the_setting(client, member, monkeypatch):
    # Off in the rest of the suite, because a cookie jar will not send a Secure
    # cookie back over plain http and every test request is plain http.
    monkeypatch.setattr(config.settings, "cookie_secure", True)
    header = _set_cookie_header(client.post("/api/auth/login", json=MEMBER))
    assert "secure" in header.lower()


def test_logout_clears_the_cookie(client, member):
    client.post("/api/auth/login", json=MEMBER)
    header = _set_cookie_header(client.post("/api/auth/logout"))
    lowered = header.lower()
    assert lowered.startswith("session=")
    assert "httponly" in lowered
    # An immediate expiry is how a cookie is withdrawn.
    assert "max-age=0" in lowered or "expires=" in lowered


def test_only_the_hash_of_a_session_reaches_the_database(client, db_session, member):
    client.post("/api/auth/login", json=MEMBER)
    cookie = client.cookies.get("session")
    row = db_session.query(models.UserSession).one()
    assert row.token_hash != cookie
    assert row.token_hash == security.hash_token(cookie)


def test_password_hashes_are_argon2id(db_session, member):
    assert member.password_hash.startswith("$argon2id$")
    assert MEMBER["password"] not in member.password_hash


def test_unknown_user_login_takes_the_dummy_verify_path(client, member, monkeypatch):
    """An unknown username must cost the same work as a known one.

    Asserting on wall-clock timing would be flaky on a shared machine, so this
    checks the thing timing is a proxy for: that the branch really does run a
    verification rather than returning early.
    """
    calls = []
    real_dummy = security.dummy_verify

    def counting_dummy():
        calls.append(1)
        real_dummy()

    # The router calls it through the module rather than by an imported name, so
    # patching the module attribute is enough to see the call.
    monkeypatch.setattr(security, "dummy_verify", counting_dummy)

    unknown = client.post(
        "/api/auth/login", json={"username": "nobody-here", "password": "some-password-1"}
    )
    assert unknown.status_code == 401
    assert calls == [1]

    known = client.post(
        "/api/auth/login", json={"username": MEMBER["username"], "password": "wrong-password-1"}
    )
    assert known.status_code == 401
    # Same status and same wording, so the response body says nothing about
    # whether the account exists.
    assert unknown.json() == known.json()
    assert unknown.json() == {"detail": "Invalid username or password"}


def test_unknown_user_and_wrong_password_are_indistinguishable(client, member):
    unknown = client.post(
        "/api/auth/login", json={"username": "ghost-account", "password": "some-password-1"}
    )
    wrong = client.post(
        "/api/auth/login", json={"username": MEMBER["username"], "password": "wrong-password-1"}
    )
    assert unknown.status_code == wrong.status_code
    assert unknown.json() == wrong.json()
    assert unknown.headers.get("content-length") == wrong.headers.get("content-length")


def test_status_endpoint_leaks_nothing(client):
    assert set(client.get("/api/status").json()) == {"name", "version", "registration_open"}


def test_placeholder_database_password_refuses_startup(monkeypatch):
    monkeypatch.setattr(
        config.settings,
        "database_url",
        "postgresql+psycopg://secondmile:change-me@db:5432/secondmile",
    )
    with pytest.raises(SystemExit) as raised:
        config.check_deploy_config()
    assert "change-me" in str(raised.value) or "placeholder" in str(raised.value)


def test_empty_database_url_refuses_startup(monkeypatch):
    monkeypatch.setattr(config.settings, "database_url", "")
    with pytest.raises(SystemExit):
        config.check_deploy_config()


def test_placeholder_postgres_password_refuses_startup(monkeypatch):
    monkeypatch.setattr(
        config.settings, "database_url", "postgresql+psycopg://user:real-secret@db:5432/secondmile"
    )
    monkeypatch.setitem(os.environ, "POSTGRES_PASSWORD", "change-me")
    with pytest.raises(SystemExit):
        config.check_deploy_config()


def test_a_real_configuration_starts(monkeypatch):
    monkeypatch.setattr(
        config.settings, "database_url", "postgresql+psycopg://user:real-secret@db:5432/secondmile"
    )
    monkeypatch.setitem(os.environ, "POSTGRES_PASSWORD", "real-secret")
    config.check_deploy_config()


def test_forwarded_for_uses_the_right_most_entry():
    class FakeRequest:
        def __init__(self, forwarded, peer):
            self.headers = {"x-forwarded-for": forwarded} if forwarded else {}
            self.client = type("Peer", (), {"host": peer})()

    # Addresses below are from the ranges reserved for documentation.
    # A caller who prepends their own entry cannot choose their bucket: the
    # right-most entry is the one our own proxy wrote.
    forged, proxy, socket_peer = "203.0.113.4", "198.51.100.9", "192.0.2.1"
    assert throttle.client_address(FakeRequest(f"{forged}, {proxy}", socket_peer)) == proxy
    assert throttle.client_address(FakeRequest("", socket_peer)) == socket_peer
    # A non-address on the right did not come from our proxy, so fall back to
    # the socket rather than reading further left into caller-supplied text.
    assert throttle.client_address(FakeRequest(f"{forged}, junk", socket_peer)) == socket_peer


def test_forged_forwarded_for_cannot_dodge_the_login_limiter(client, member):
    wrong = {"username": MEMBER["username"], "password": "wrong-password-1"}
    codes = []
    for attempt in range(6):
        # A new left-most entry each time, which is all an attacker controls.
        codes.append(
            client.post(
                "/api/auth/login",
                json=wrong,
                headers={"X-Forwarded-For": f"203.0.113.{attempt}, 198.51.100.9"},
            ).status_code
        )
    assert codes[5] == 429


def test_limiter_window_and_sweep():
    limiter = throttle.RateLimiter(2, "test")
    assert limiter.hit("a") is False
    assert limiter.hit("a") is False
    assert limiter.hit("a") is True
    # A different address has its own allowance.
    assert limiter.hit("b") is False
    assert limiter.tracked() == 2
    limiter.clear()
    assert limiter.tracked() == 0


def test_limiter_forgets_old_attempts(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    limiter = throttle.RateLimiter(1, "test")
    assert limiter.hit("a") is False
    assert limiter.hit("a") is True
    # Once the window has passed, the old attempt no longer counts against the
    # allowance; the window slides rather than resetting on a fixed schedule.
    clock[0] += 120
    assert limiter.hit("a") is False


def test_reset_limiters_clears_every_one(client, member):
    wrong = {"username": MEMBER["username"], "password": "wrong-password-1"}
    for _ in range(5):
        client.post("/api/auth/login", json=wrong)
    assert client.post("/api/auth/login", json=wrong).status_code == 429
    throttle.reset_limiters()
    assert client.post("/api/auth/login", json=wrong).status_code == 401


def test_admin_flag_is_read_from_the_database_not_the_cookie(client, db_session, admin):
    client.post("/api/auth/login", json=ADMIN)
    assert client.get("/api/auth/me").json()["is_admin"] is True
    admin.is_admin = False
    db_session.commit()
    # No new sign in, and the answer has already changed.
    assert client.get("/api/auth/me").json()["is_admin"] is False
