"""Invite links: minting, revoking, claiming, and the page a link opens.

The negative cases are the point of most of this. A link works once, a link
taken back works never, and every dead code answers the welcome page with the
same sentence, whichever way it died.
"""

import datetime as dt

import pytest
from conftest import MEMBER, make_invite, make_user
from fastapi.testclient import TestClient

from app import fellowship, models, security
from app.main import app as fastapi_app
from app.routers.invites import DEAD_LINK

pytest.importorskip("PIL")


def signup(client, code: str, username="newcomer", email="newcomer@example.test"):
    return client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "newcomer-password-1",
            "email": email,
            "invite_code": code,
        },
    )


def mint(client) -> dict:
    response = client.post("/api/invites")
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# Minting, listing, revoking
# --------------------------------------------------------------------------


def test_a_minted_link_never_expires_and_carries_a_friendship(signed_in, db_session, member):
    row = mint(signed_in)
    stored = db_session.execute(
        models.Invite.__table__.select().where(models.Invite.code == row["code"])
    ).one()
    assert stored.expires_at is None
    assert stored.auto_friend is True
    assert stored.created_by == member.id
    # A listed link is always waiting: a claimed one leaves the list and a
    # revoked one is deleted, so neither state travels at all.
    assert "claimed_by" not in row
    assert "revoked_at" not in row


def test_the_list_holds_your_own_links_and_nobody_elses(signed_in, db_session, admin):
    mine = mint(signed_in)
    # A command line code, made by somebody else, and never on this screen: it
    # is an account gate belonging to whoever runs the server.
    make_invite(db_session, admin.id)
    listed = signed_in.get("/api/invites").json()
    assert [row["code"] for row in listed] == [mine["code"]]


def test_a_claimed_link_leaves_the_list(signed_in, client, outbox):
    # The friendship the link made is its record; the row itself, a spent
    # credential, has no more business on screen.
    row = mint(signed_in)
    assert signup(client, row["code"]).status_code == 201
    assert signed_in.get("/api/invites").json() == []


def test_three_links_may_wait_and_a_freed_slot_mints_again(signed_in, client, outbox):
    # The cap is a bad-actor bound, not a budget: claiming or revoking a link
    # frees its slot, so a growing club is never stuck behind it.
    rows = [mint(signed_in) for _ in range(3)]
    refused = signed_in.post("/api/invites")
    assert refused.status_code == 400
    assert "waiting" in refused.json()["detail"]
    assert signup(client, rows[0]["code"]).status_code == 201
    mint(signed_in)


def test_minting_locks_the_account_row_before_it_counts(signed_in, db_session):
    """The cap is a count and then an insert, so two mints at once could both
    count three and both write a fourth. What stops them is the row lock taken
    first, and the order is the whole of it: locked, then counted, then written.

    Pinned by the statements rather than by real threads, because the suite runs
    on SQLite, which has no FOR UPDATE to wait on and no second connection to
    wait with. What the test can prove is that the lock goes out ahead of the
    count, in the transaction the insert commits.
    """
    real_execute = db_session.execute
    seen = []

    def record(statement, *args, **kwargs):
        seen.append(str(statement))
        return real_execute(statement, *args, **kwargs)

    db_session.execute = record
    try:
        mint(signed_in)
    finally:
        db_session.execute = real_execute

    locks = [i for i, text in enumerate(seen) if "FROM users" in text and "FOR UPDATE" in text]
    counts = [i for i, text in enumerate(seen) if "FROM invites" in text]
    assert locks and counts
    assert locks[0] < counts[0]


def test_a_link_can_be_revoked_while_it_is_waiting_and_not_after(
    signed_in, client, db_session, outbox
):
    row = mint(signed_in)
    assert signed_in.post(f"/api/invites/{row['id']}/revoke").status_code == 204
    # Revoking deletes the row, so the list simply no longer carries it.
    assert signed_in.get("/api/invites").json() == []
    # Twice is the same 404 an id nobody minted gets: there is nothing left to
    # take back.
    assert signed_in.post(f"/api/invites/{row['id']}/revoke").status_code == 404

    spent = mint(signed_in)
    assert signup(client, spent["code"]).status_code == 201
    assert signed_in.post(f"/api/invites/{spent['id']}/revoke").status_code == 404


def test_a_link_belongs_to_whoever_minted_it(signed_in, db_session):
    row = mint(signed_in)
    make_user(db_session, "mate", "mate-password-1")
    other_client = TestClient(fastapi_app)
    assert (
        other_client.post(
            "/api/auth/login", json={"username": "mate", "password": "mate-password-1"}
        ).status_code
        == 204
    )
    # Somebody else's code is not on your screen, and not yours to take back.
    assert other_client.get("/api/invites").json() == []
    assert other_client.post(f"/api/invites/{row['id']}/revoke").status_code == 404


def test_the_link_endpoints_need_a_session(client):
    client.cookies.clear()
    assert client.get("/api/invites").status_code == 401
    assert client.post("/api/invites").status_code == 401
    assert client.post("/api/invites/1/revoke").status_code == 401


# --------------------------------------------------------------------------
# Claiming
# --------------------------------------------------------------------------


def test_claiming_a_link_makes_the_two_accounts_friends(
    signed_in, client, db_session, member, outbox
):
    row = mint(signed_in)
    assert signup(client, row["code"]).status_code == 201
    newcomer = db_session.execute(
        models.User.__table__.select().where(models.User.username == "newcomer")
    ).one()
    # The mutual shape, which reads as friends from either end.
    assert fellowship.are_friends(db_session, member.id, newcomer.id)
    assert fellowship.are_friends(db_session, newcomer.id, member.id)
    # And it is on the inviter's list once, not twice.
    assert [card["username"] for card in signed_in.get("/api/friends").json()["friends"]] == [
        "newcomer"
    ]


def test_a_command_line_code_makes_no_friendship(client, db_session, admin, invite, outbox):
    assert signup(client, invite.code).status_code == 201
    newcomer = db_session.execute(
        models.User.__table__.select().where(models.User.username == "newcomer")
    ).one()
    assert not fellowship.are_friends(db_session, admin.id, newcomer.id)


def test_a_link_works_once(signed_in, client, db_session, outbox):
    row = mint(signed_in)
    assert signup(client, row["code"]).status_code == 201
    again = signup(client, row["code"], username="second", email="second@example.test")
    assert again.status_code == 400
    assert again.json() == {"detail": "Invite code is not valid."}
    assert (
        db_session.execute(
            models.User.__table__.select().where(models.User.username == "second")
        ).one_or_none()
        is None
    )


def test_two_registrations_racing_one_link_leave_one_account(signed_in, db_session, outbox):
    """The conditional UPDATE, exercised the only way a test can: the row is
    claimed underneath the request between its read and its write."""
    row = mint(signed_in)
    invite_id = signed_in.get("/api/invites").json()[0]["id"]
    other = make_user(db_session, "rival", "rival-password-1")

    real_execute = db_session.execute
    fired = {"done": False}

    def claim_underneath(statement, *args, **kwargs):
        # Just before the UPDATE goes out, somebody else takes the code.
        if not fired["done"] and "UPDATE invites" in str(statement):
            fired["done"] = True
            db_session.execute = real_execute
            real_execute(
                models.Invite.__table__.update()
                .where(models.Invite.id == invite_id)
                .values(used_by=other.id)
            )
            db_session.execute = claim_underneath
        return real_execute(statement, *args, **kwargs)

    db_session.execute = claim_underneath
    client = TestClient(fastapi_app)
    try:
        refused = signup(client, row["code"])
    finally:
        db_session.execute = real_execute
    assert refused.status_code == 400
    assert refused.json() == {"detail": "Invite code is not valid."}
    assert fired["done"]
    # The loser's account is not left behind by the rollback.
    assert (
        db_session.execute(
            models.User.__table__.select().where(models.User.username == "newcomer")
        ).one_or_none()
        is None
    )


def test_a_revoked_link_mints_nothing(signed_in, client, db_session, outbox):
    row = mint(signed_in)
    assert signed_in.post(f"/api/invites/{row['id']}/revoke").status_code == 204
    refused = signup(client, row["code"])
    assert refused.status_code == 400
    assert refused.json() == {"detail": "Invite code is not valid."}
    assert (
        db_session.execute(
            models.User.__table__.select().where(models.User.username == "newcomer")
        ).one_or_none()
        is None
    )


def test_a_dated_code_still_runs_out(client, db_session, admin, outbox):
    """Null expiry is what a minted link has; the command line's codes keep
    their date and keep expiring on it."""
    stale = make_invite(db_session, admin.id)
    db_session.execute(
        models.Invite.__table__.update()
        .where(models.Invite.id == stale.id)
        .values(expires_at=security.now_utc() - dt.timedelta(days=1))
    )
    db_session.commit()
    assert signup(client, stale.code).status_code == 400


# --------------------------------------------------------------------------
# The welcome page
# --------------------------------------------------------------------------


def test_a_live_link_says_who_sent_it(signed_in, client, db_session, member):
    signed_in.patch("/api/profile", json={"first_name": "Ada", "last_name": "Rowe"})
    row = mint(signed_in)
    client.cookies.clear()
    body = client.get(f"/api/invites/{row['code']}/welcome")
    assert body.status_code == 200
    assert body.json() == {
        "inviter_display_name": "Ada Rowe",
        "inviter_has_avatar": False,
        "inviter_avatar_version": None,
        "inviter_border_tier": 1,
        "inviter_flourish": 0,
    }


def test_an_inviter_with_no_name_is_introduced_by_their_username(signed_in, client):
    row = mint(signed_in)
    client.cookies.clear()
    body = client.get(f"/api/invites/{row['code']}/welcome").json()
    assert body["inviter_display_name"] == MEMBER["username"]


def test_the_four_dead_codes_answer_identically(signed_in, client, db_session, admin, outbox):
    """Claimed, revoked, expired, never minted. Four endings, one answer: a
    link that no longer works does not go on to say what became of it."""
    claimed = mint(signed_in)
    assert signup(client, claimed["code"]).status_code == 201

    revoked = mint(signed_in)
    assert signed_in.post(f"/api/invites/{revoked['id']}/revoke").status_code == 204

    expired = make_invite(db_session, admin.id)
    expired.expires_at = security.now_utc() - dt.timedelta(days=1)
    db_session.commit()
    # The suite shares one session across every request, so a row the app
    # updated through the core is still cached here. Production gives each
    # request a session of its own and never sees this.
    db_session.expire_all()

    client.cookies.clear()
    answers = [
        client.get(f"/api/invites/{code}/welcome")
        for code in (claimed["code"], revoked["code"], expired.code, "never-existed-at-all")
    ]
    for answer in answers:
        assert answer.status_code == 404
        assert answer.json() == {"detail": DEAD_LINK}
    assert len({answer.content for answer in answers}) == 1


def test_the_welcome_page_needs_no_session(signed_in, client):
    row = mint(signed_in)
    client.cookies.clear()
    assert client.get(f"/api/invites/{row['code']}/welcome").status_code == 200


def test_the_face_on_the_welcome_page_rides_on_the_code(signed_in, client, db_session):
    from test_profile import image_bytes, upload

    upload(signed_in, image_bytes())
    row = mint(signed_in)
    client.cookies.clear()
    assert client.get(f"/api/invites/{row['code']}/welcome").json()["inviter_has_avatar"] is True
    assert client.get(f"/api/invites/{row['code']}/avatar").status_code == 200
    # A dead code is the same 404 the sentence beside it gets.
    dead = client.get("/api/invites/never-existed-at-all/avatar")
    assert dead.status_code == 404
    assert dead.json() == {"detail": DEAD_LINK}


def test_an_inviter_with_no_picture_is_the_same_404(signed_in, client):
    row = mint(signed_in)
    client.cookies.clear()
    refused = client.get(f"/api/invites/{row['code']}/avatar")
    assert refused.status_code == 404
    assert refused.json() == {"detail": DEAD_LINK}
