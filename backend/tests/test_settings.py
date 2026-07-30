"""Ingest token status and rotation, and the units preference."""

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
    assert response.json() == {"units": "metric"}
    assert signed_in.get("/api/auth/me").json()["units"] == "metric"

    back = signed_in.patch("/api/settings", json={"units": "imperial"})
    assert back.json() == {"units": "imperial"}


def test_units_rejects_anything_else(signed_in):
    assert signed_in.patch("/api/settings", json={"units": "furlongs"}).status_code == 400


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
