"""Checks on the properties that are easy to break and hard to notice."""

import os
import time

import anyio
import pytest

from app import config, main, models, security, throttle
from conftest import ADMIN, MEMBER
from test_grove import sign_in


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
    assert unknown.json() == {"detail": "Invalid username or password."}


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
    assert set(client.get("/api/status").json()) == {
        "name",
        "version",
        "registration_open",
        "timezone",
    }


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


def test_trusted_proxy_hops_skips_the_entries_our_own_proxies_wrote(monkeypatch):
    class FakeRequest:
        def __init__(self, forwarded, peer="192.0.2.1"):
            self.headers = {"x-forwarded-for": forwarded} if forwarded else {}
            self.client = type("Peer", (), {"host": peer})()

    forged, real_client, inner_proxy = "203.0.113.4", "198.51.100.9", "192.0.2.7"
    header = f"{forged}, {real_client}, {inner_proxy}"

    # Nothing configured: one proxy, so the right-most entry is the caller.
    assert throttle.client_address(FakeRequest(header)) == inner_proxy
    # One extra proxy of our own wrote the right-most entry, so the one before
    # it is what the proxy behind it saw.
    monkeypatch.setattr(config.settings, "trusted_proxy_hops", 1)
    assert throttle.client_address(FakeRequest(header)) == real_client
    # More hops than the header carries falls back to the connection address
    # rather than reading off the end into whatever the caller wrote.
    monkeypatch.setattr(config.settings, "trusted_proxy_hops", 5)
    assert throttle.client_address(FakeRequest(header)) == "192.0.2.1"
    assert throttle.client_address(FakeRequest("")) == "192.0.2.1"
    # A nonsense setting cannot make it read further right than the header goes.
    monkeypatch.setattr(config.settings, "trusted_proxy_hops", -3)
    assert throttle.client_address(FakeRequest(header)) == inner_proxy


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


def test_the_limiter_evicts_the_oldest_key_rather_than_refusing_new_ones(monkeypatch):
    """At the ceiling, somebody is flooding it with addresses they made up.

    Refusing new keys there was the old answer, and it turns a flood into an
    outage: every real person arriving after the table filled would be told to
    wait, on an endpoint they had not touched. The oldest key is dropped
    instead, which costs the earliest attacker their count and nobody else
    anything.
    """
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    monkeypatch.setattr(throttle, "_MAX_TRACKED", 3)
    # Above the ceiling, so the sweep never runs and the eviction is what is
    # being watched rather than the tidy-up in front of it.
    monkeypatch.setattr(throttle, "_SWEEP_THRESHOLD", 100)
    limiter = throttle.RateLimiter(2, "test")

    for index, key in enumerate(("a", "b", "c")):
        clock[0] += 1
        assert limiter.hit(key) is False
        assert limiter.tracked() == index + 1

    # The table is full and a fourth key arrives. It is let in, and the one that
    # has gone longest without a hit is the one that makes room.
    clock[0] += 1
    assert limiter.hit("d") is False
    assert limiter.tracked() == 3
    assert "a" not in limiter._hits
    assert {"b", "c", "d"} == set(limiter._hits)
    # And the newcomer really got an allowance rather than a place in a queue.
    assert limiter.hit("d") is False
    assert limiter.hit("d") is True


def test_one_account_cannot_spend_another_accounts_allowance(client, db_session, member):
    """The signed-in limiters count per account, not per address.

    Everything in this suite arrives from one address, which is also what a
    household behind one router looks like. Counting those together would mean
    one phone syncing hard could lock the rest of a family out of their own
    profiles.
    """
    client.post("/api/auth/login", json=MEMBER)
    codes = [client.patch("/api/profile", json={}).status_code for _ in range(11)]
    assert codes[-1] == 429
    assert codes.count(200) == 10

    _other, other_client = sign_in(db_session, "mate")
    # Same address, untouched allowance.
    assert other_client.patch("/api/profile", json={}).status_code == 200


def test_reset_limiters_clears_every_one(client, member):
    wrong = {"username": MEMBER["username"], "password": "wrong-password-1"}
    for _ in range(5):
        client.post("/api/auth/login", json=wrong)
    assert client.post("/api/auth/login", json=wrong).status_code == 429
    throttle.reset_limiters()
    assert client.post("/api/auth/login", json=wrong).status_code == 401


def test_every_limiter_is_registered_for_the_reset(client, member):
    """A limiter that is not in the group is the test that passes alone and
    fails in the suite, so the group is checked rather than assumed."""
    names = {limiter.name for limiter in throttle._ALL_LIMITERS}
    assert {"workout-edit", "verify"} <= names
    for limiter in throttle._ALL_LIMITERS:
        limiter.hit("198.51.100.9")
        assert limiter.tracked() == 1
    throttle.reset_limiters()
    assert all(limiter.tracked() == 0 for limiter in throttle._ALL_LIMITERS)


def test_admin_flag_is_read_from_the_database_not_the_cookie(client, db_session, admin):
    client.post("/api/auth/login", json=ADMIN)
    assert client.get("/api/auth/me").json()["is_admin"] is True
    admin.is_admin = False
    db_session.commit()
    # No new sign in, and the answer has already changed.
    assert client.get("/api/auth/me").json()["is_admin"] is False


def _oversized(size: int) -> bytes:
    """A body of roughly `size` bytes that is valid JSON if it survives."""
    return b'{"filler":"' + b"x" * size + b'"}'


def test_body_over_the_ingest_cap_is_refused_before_the_token_is_read(client):
    response = client.post(
        "/api/ingest",
        content=_oversized(config.MAX_INGEST_BODY_BYTES),
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    # 413 rather than 401: the size is settled before anything reads the body,
    # and before the token is checked, so a flood costs nothing to refuse.
    assert response.status_code == 413


def test_sync_gets_more_room_than_the_rest_of_the_api(client):
    body = _oversized(config.MAX_BODY_BYTES + 1024)
    assert client.post("/api/auth/login", content=body).status_code == 413
    # The same body at the sync endpoint gets as far as the token check.
    everywhere_else = client.post(
        "/api/ingest", content=body, headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert everywhere_else.status_code == 401


def test_a_body_without_a_content_length_is_counted_as_it_arrives():
    """The declared length is only a claim, so the bytes are counted too.

    Driven directly rather than through the test client, which always declares
    a length: this is the path a chunked upload takes.
    """
    chunk = b"x" * (1024 * 1024)
    read = 0
    statuses = []

    async def parses_the_body(scope, receive, send):
        while (await receive()).get("more_body"):
            pass
        # What a handler does with a body it cannot make sense of.
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        nonlocal read
        read += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message):
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    async def drive():
        middleware = main.BodySizeLimitMiddleware(parses_the_body)
        scope = {"type": "http", "method": "POST", "path": "/api/ingest", "headers": []}
        await middleware(scope, receive, send)

    anyio.run(drive)

    assert statuses == [413]
    # Cut off at the cap rather than read to the end.
    assert read <= config.MAX_INGEST_BODY_BYTES + len(chunk)
