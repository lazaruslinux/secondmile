"""Ingest token status and rotation, the units preference, and the list of
fields an account keeps back from its friends."""

from app import models, security


def test_token_status_before_and_after_rotation(signed_in):
    before = signed_in.get("/api/settings/ingest-token").json()
    assert before == {"exists": False, "rotated_at": None}

    rotated = signed_in.post("/api/settings/ingest-token/rotate")
    assert rotated.status_code == 200
    assert len(rotated.json()["token"]) >= 32

    after = signed_in.get("/api/settings/ingest-token").json()
    assert after["exists"] is True
    assert after["rotated_at"] is not None


def test_the_plaintext_token_is_never_stored_or_shown_again(signed_in, db_session, member):
    token = signed_in.post("/api/settings/ingest-token/rotate").json()["token"]
    row = db_session.get(models.IngestToken, member.id)
    assert row.token_hash == security.hash_token(token)
    assert token not in row.token_hash
    # The status endpoint says whether one exists, never what it is.
    assert "token" not in signed_in.get("/api/settings/ingest-token").json()


def test_rotation_replaces_rather_than_accumulates(signed_in, db_session, member):
    signed_in.post("/api/settings/ingest-token/rotate")
    signed_in.post("/api/settings/ingest-token/rotate")
    assert db_session.query(models.IngestToken).count() == 1


def test_units_toggle(signed_in):
    response = signed_in.patch("/api/settings", json={"units": "metric"})
    assert response.status_code == 200
    assert response.json()["units"] == "metric"
    assert signed_in.get("/api/auth/me").json()["units"] == "metric"

    back = signed_in.patch("/api/settings", json={"units": "imperial"})
    assert back.json()["units"] == "imperial"


def test_units_rejects_anything_else(signed_in):
    assert signed_in.patch("/api/settings", json={"units": "furlongs"}).status_code == 400


def test_nothing_is_hidden_from_friends_until_somebody_says_so(signed_in):
    assert signed_in.get("/api/auth/me").json()["hidden_from_friends"] == []


def test_hidden_fields_are_saved_and_read_back(signed_in):
    response = signed_in.patch("/api/settings", json={"hidden_from_friends": ["route"]})
    assert response.status_code == 200
    assert response.json()["hidden_from_friends"] == ["route"]
    assert signed_in.get("/api/auth/me").json()["hidden_from_friends"] == ["route"]

    # An empty list is how the switches all go back off.
    cleared = signed_in.patch("/api/settings", json={"hidden_from_friends": []})
    assert cleared.json()["hidden_from_friends"] == []


def test_hidden_fields_come_back_in_one_order(signed_in):
    """Whatever order they were sent in, and without a repeat, so the switches
    read the same way on every screen that draws them."""
    response = signed_in.patch(
        "/api/settings",
        json={"hidden_from_friends": ["route", "avg_hr", "route"]},
    )
    assert response.json()["hidden_from_friends"] == ["avg_hr", "route"]


def test_an_unknown_hidden_field_is_refused(signed_in):
    """Refused rather than dropped: a client told it may hide something would
    otherwise show a switch that quietly does nothing."""
    response = signed_in.patch("/api/settings", json={"hidden_from_friends": ["pace"]})
    assert response.status_code == 400
    response = signed_in.patch("/api/settings", json={"hidden_from_friends": ["photos"]})
    assert response.status_code == 400
    assert signed_in.get("/api/auth/me").json()["hidden_from_friends"] == []


def test_changing_settings_is_rate_limited(signed_in):
    """The same per-user allowance the profile edits are counted against."""
    seen = {
        signed_in.patch("/api/settings", json={"units": "metric"}).status_code
        for _ in range(20)
    }
    assert 429 in seen


def test_settings_need_a_session(client):
    assert client.get("/api/settings/ingest-token").status_code == 401
    assert client.post("/api/settings/ingest-token/rotate").status_code == 401
    assert client.patch("/api/settings", json={"units": "metric"}).status_code == 401


def test_tokens_are_per_user(signed_in, client, db_session, admin, member):
    from conftest import ADMIN

    member_token = signed_in.post("/api/settings/ingest-token/rotate").json()["token"]
    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    admin_token = signed_in.post("/api/settings/ingest-token/rotate").json()["token"]

    assert member_token != admin_token
    assert db_session.query(models.IngestToken).count() == 2
