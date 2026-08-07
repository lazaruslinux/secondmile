"""Friends, the feed, encouragement, renown, and what the recap makes of it.

Every account and every workout here is invented. The privacy rules are the
point of most of these cases: a friend sees a headline and a stranger sees
nothing, and both of those are asserted against the whole response rather than
against the one field that happens to be wrong today.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config, fellowship, models, security
from app.main import app as fastapi_app
from conftest import make_user

# What a feed row is allowed to carry for somebody else's workout. Asserted as
# a whole set: a new field leaking heart rate or pace has to fail this.
FRIEND_ROW_KEYS = {
    "workout_id",
    "user",
    "activity",
    "start_ts",
    "distance_mi",
    "duration_s",
    "race_badge",
    "has_route",
    "source",
    "own",
    "encouragement",
}


def sign_in(db_session, username: str) -> tuple[models.User, TestClient]:
    """A second account with a cookie jar of its own."""
    password = f"{username}-password-1"
    user = make_user(db_session, username, password)
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 204, response.text
    return user, client


def post_workout(client, *, activity="run", miles=3.5, offset_min=0, avg_hr=142.0) -> dict:
    start = security.now_utc() - dt.timedelta(hours=12) + dt.timedelta(minutes=offset_min)
    body = {
        "activity": activity,
        "start_ts": start.isoformat(),
        "duration_s": int(miles * 10 * 60),
        "distance_mi": miles,
        "active_kcal": 300.0,
        "avg_hr": avg_hr,
    }
    response = client.post("/api/workouts", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def befriend(db_session, first: models.User, second: models.User, status="accepted") -> None:
    db_session.add(
        models.Friendship(
            requester_id=first.id,
            addressee_id=second.id,
            status=status,
            created_at=security.now_utc(),
        )
    )
    db_session.commit()


def renown_of(db_session, user: models.User) -> int:
    db_session.expire_all()
    row = db_session.get(models.UserProgress, user.id)
    return 0 if row is None else row.renown


@pytest.fixture()
def mate(client, db_session) -> tuple[models.User, TestClient]:
    """A second signed-in account, not yet anybody's friend."""
    return sign_in(db_session, "mate")


# --------------------------------------------------------------------------
# Invites and the friends list
# --------------------------------------------------------------------------


def test_the_whole_friendship_lifecycle(signed_in, db_session, member, mate):
    other, other_client = mate

    assert signed_in.post("/api/friends/invite", json={"username": "mate"}).status_code == 204
    mine = signed_in.get("/api/friends").json()
    assert mine["friends"] == []
    assert [card["username"] for card in mine["pending_out"]] == ["mate"]
    theirs = other_client.get("/api/friends").json()
    assert [card["username"] for card in theirs["pending_in"]] == [member.username]

    assert other_client.post(f"/api/friends/{member.id}/accept").status_code == 204
    mine = signed_in.get("/api/friends").json()
    assert [card["username"] for card in mine["friends"]] == ["mate"]
    assert mine["pending_out"] == []
    assert [card["username"] for card in other_client.get("/api/friends").json()["friends"]] == [
        member.username
    ]

    # One verb undoes it from either side.
    assert signed_in.delete(f"/api/friends/{other.id}").status_code == 204
    assert signed_in.get("/api/friends").json()["friends"] == []
    assert other_client.get("/api/friends").json()["friends"] == []


def test_a_friend_card_carries_no_counts_and_no_renown(signed_in, db_session, member, mate):
    other, _ = mate
    befriend(db_session, member, other)
    db_session.add(
        models.UserProgress(
            user_id=other.id,
            xp=0.0,
            level=0,
            chest_progress_mi=0.0,
            renown=40,
            updated_at=security.now_utc(),
        )
    )
    db_session.commit()

    card = signed_in.get("/api/friends").json()["friends"][0]
    assert set(card) == {
        "user_id",
        "username",
        "display_name",
        "has_avatar",
        "border_tier",
        "flourish",
    }
    assert card["display_name"] is None
    assert card["flourish"] == 2


def test_an_invite_never_says_whether_the_name_existed(signed_in, mate):
    assert (
        signed_in.post("/api/friends/invite", json={"username": "nobody-here"}).status_code
        == 204
    )
    # And nothing was written for a name that does not exist.
    assert signed_in.get("/api/friends").json()["pending_out"] == []
    # A duplicate and a reverse duplicate are both quiet no-ops.
    signed_in.post("/api/friends/invite", json={"username": "mate"})
    signed_in.post("/api/friends/invite", json={"username": "MATE"})
    assert len(signed_in.get("/api/friends").json()["pending_out"]) == 1


def test_a_reverse_invite_is_a_no_op_rather_than_a_second_row(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    signed_in.post("/api/friends/invite", json={"username": "mate"})
    assert (
        other_client.post(
            "/api/friends/invite", json={"username": member.username}
        ).status_code
        == 204
    )
    assert db_session.query(models.Friendship).count() == 1
    # The original invite still needs answering; it was not silently accepted.
    assert other_client.get("/api/friends").json()["friends"] == []


def test_inviting_yourself_is_refused(signed_in, member):
    response = signed_in.post("/api/friends/invite", json={"username": member.username})
    assert response.status_code == 400


def test_accepting_an_invite_nobody_sent_is_a_404(signed_in, mate):
    other, _ = mate
    assert signed_in.post(f"/api/friends/{other.id}/accept").status_code == 404


def test_removing_nothing_still_answers_204(signed_in, mate):
    other, _ = mate
    assert signed_in.delete(f"/api/friends/{other.id}").status_code == 204
    assert signed_in.delete("/api/friends/424242").status_code == 204


def test_only_the_addressee_can_accept(signed_in, db_session, member, mate):
    other, _ = mate
    signed_in.post("/api/friends/invite", json={"username": "mate"})
    # The person who asked cannot answer their own invite.
    assert signed_in.post(f"/api/friends/{other.id}/accept").status_code == 404
    assert db_session.query(models.Friendship).one().status == "pending"


def test_the_feed_needs_a_session(client):
    assert client.get("/api/feed").status_code == 401


# --------------------------------------------------------------------------
# The feed
# --------------------------------------------------------------------------


def test_a_stranger_sees_nothing_of_yours(signed_in, mate):
    _, other_client = mate
    post_workout(signed_in)
    assert other_client.get("/api/feed").json() == []


def test_a_pending_invite_shows_nothing_either(signed_in, mate):
    _, other_client = mate
    post_workout(signed_in)
    signed_in.post("/api/friends/invite", json={"username": "mate"})
    assert other_client.get("/api/feed").json() == []


def test_a_friend_sees_the_headline_and_nothing_behind_it(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    befriend(db_session, member, other)
    workout = post_workout(signed_in, miles=3.5)

    rows = other_client.get("/api/feed").json()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == FRIEND_ROW_KEYS
    assert row["own"] is False
    assert row["workout_id"] == workout["id"]
    assert row["distance_mi"] == 3.5
    assert row["duration_s"] == 2100
    assert row["race_badge"] == "race_5k"
    assert row["user"]["username"] == member.username
    assert row["encouragement"] == {"cheers": 0, "notes": 0, "cheered_by_me": False}
    # The things a friend is never told, spelled out so a future field cannot
    # quietly join the row.
    for hidden in ("avg_hr", "active_kcal", "flags", "pace", "xp"):
        assert hidden not in row


def test_your_own_rows_keep_their_experience(signed_in):
    post_workout(signed_in, activity="walk", miles=2.0)
    row = signed_in.get("/api/feed").json()[0]
    assert row["own"] is True
    assert row["xp"] == 2.0
    assert set(row) == FRIEND_ROW_KEYS | {"xp"}


def test_the_feed_mixes_both_accounts_newest_first(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    post_workout(signed_in, offset_min=0)
    post_workout(other_client, offset_min=30)
    post_workout(signed_in, offset_min=60)

    rows = signed_in.get("/api/feed").json()
    assert [row["own"] for row in rows] == [True, False, True]
    assert rows[0]["start_ts"] > rows[1]["start_ts"] > rows[2]["start_ts"]


def test_the_feed_pages_with_the_before_cursor(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    post_workout(signed_in, offset_min=0)
    post_workout(other_client, offset_min=30)

    rows = signed_in.get("/api/feed").json()
    older = signed_in.get("/api/feed", params={"before": rows[0]["start_ts"]}).json()
    assert [row["workout_id"] for row in older] == [rows[1]["workout_id"]]
    assert signed_in.get("/api/feed", params={"before": "not-a-timestamp"}).status_code == 400


def test_the_feed_stops_at_one_page(signed_in):
    for offset in range(22):
        post_workout(signed_in, miles=1.0, offset_min=offset * 5)
    assert len(signed_in.get("/api/feed").json()) == 20


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def _add_route(db_session, workout_id: int) -> None:
    db_session.add(
        models.WorkoutRoute(workout_id=workout_id, points=[[10.0, 20.0], [10.001, 20.0]])
    )
    db_session.commit()


def test_a_friend_can_read_your_route(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    workout = post_workout(signed_in)
    _add_route(db_session, workout["id"])

    assert signed_in.get("/api/feed").json()[0]["has_route"] is True
    response = other_client.get(f"/api/workouts/{workout['id']}/route")
    assert response.status_code == 200
    assert response.json()["points"] == [[10.0, 20.0], [10.001, 20.0]]


def test_a_stranger_still_cannot(signed_in, db_session, mate):
    _, other_client = mate
    workout = post_workout(signed_in)
    _add_route(db_session, workout["id"])
    assert other_client.get(f"/api/workouts/{workout['id']}/route").status_code == 404


def test_a_pending_invite_does_not_open_a_route(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other, status="pending")
    workout = post_workout(signed_in)
    _add_route(db_session, workout["id"])
    assert other_client.get(f"/api/workouts/{workout['id']}/route").status_code == 404


# --------------------------------------------------------------------------
# Encouragement
# --------------------------------------------------------------------------


@pytest.fixture()
def friends(signed_in, db_session, member, mate):
    """The member and one friend, both signed in, already accepted."""
    other, other_client = mate
    befriend(db_session, member, other)
    return signed_in, member, other_client, other


def test_a_cheer_is_wordless_and_counted(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(mine)

    response = theirs.post(f"/api/workouts/{workout['id']}/encourage", json={"kind": "cheer"})
    assert response.status_code == 201
    assert response.json()["encouragement"] == {
        "cheers": 1,
        "notes": 0,
        "cheered_by_me": True,
    }
    assert db_session.query(models.Encouragement).one().body is None
    # The owner sees the count but has not cheered it themselves.
    assert mine.get("/api/feed").json()[0]["encouragement"] == {
        "cheers": 1,
        "notes": 0,
        "cheered_by_me": False,
    }


def test_only_one_cheer_each(friends):
    mine, _, theirs, _ = friends
    workout = post_workout(mine)
    assert theirs.post(f"/api/workouts/{workout['id']}/encourage", json={"kind": "cheer"}).status_code == 201
    again = theirs.post(f"/api/workouts/{workout['id']}/encourage", json={"kind": "cheer"})
    assert again.status_code == 409


def test_notes_are_not_limited_to_one(friends):
    mine, _, theirs, _ = friends
    workout = post_workout(mine)
    for body in ("Good week.", "See you Saturday."):
        response = theirs.post(
            f"/api/workouts/{workout['id']}/encourage", json={"kind": "note", "body": body}
        )
        assert response.status_code == 201
    assert response.json()["encouragement"]["notes"] == 2


def test_a_note_needs_words_and_has_a_ceiling(friends):
    mine, _, theirs, _ = friends
    workout = post_workout(mine)
    url = f"/api/workouts/{workout['id']}/encourage"
    assert theirs.post(url, json={"kind": "note"}).status_code == 400
    assert theirs.post(url, json={"kind": "note", "body": "   "}).status_code == 400
    assert (
        theirs.post(
            url, json={"kind": "note", "body": "x" * (config.NOTE_MAX_CHARS + 1)}
        ).status_code
        == 400
    )
    assert (
        theirs.post(
            url, json={"kind": "note", "body": "x" * config.NOTE_MAX_CHARS}
        ).status_code
        == 201
    )


def test_encouragement_is_refused_where_it_does_not_belong(signed_in, mate, db_session):
    other, other_client = mate
    own = post_workout(signed_in)
    assert (
        signed_in.post(f"/api/workouts/{own['id']}/encourage", json={"kind": "cheer"}).status_code
        == 400
    )
    # A stranger's workout answers the same way a workout that never existed
    # does, so an id cannot be walked to find out whose it is.
    assert (
        other_client.post(f"/api/workouts/{own['id']}/encourage", json={"kind": "cheer"}).status_code
        == 404
    )
    assert (
        other_client.post("/api/workouts/424242/encourage", json={"kind": "cheer"}).status_code
        == 404
    )
    assert (
        signed_in.post(f"/api/workouts/{own['id']}/encourage", json={"kind": "clap"}).status_code
        == 400
    )


# --------------------------------------------------------------------------
# Renown and the flourish
# --------------------------------------------------------------------------


def test_flourish_stages_follow_the_thresholds():
    assert config.FLOURISH_RENOWN == (10, 40, 120)
    for renown, stage in ((0, 0), (9, 0), (10, 1), (39, 1), (40, 2), (119, 2), (120, 3), (9999, 3)):
        assert fellowship.flourish_stage(renown) == stage


def test_giving_earns_renown_and_receiving_earns_none(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(mine)
    theirs.post(f"/api/workouts/{workout['id']}/encourage", json={"kind": "cheer"})
    assert renown_of(db_session, other) == config.RENOWN_CHEER
    assert renown_of(db_session, member) == 0


def test_the_second_cheer_of_the_week_still_arrives_but_pays_nothing(friends, db_session):
    mine, _, theirs, other = friends
    first = post_workout(mine, offset_min=0)
    second = post_workout(mine, offset_min=30)
    theirs.post(f"/api/workouts/{first['id']}/encourage", json={"kind": "cheer"})
    response = theirs.post(f"/api/workouts/{second['id']}/encourage", json={"kind": "cheer"})

    assert response.status_code == 201
    assert response.json()["encouragement"]["cheers"] == 1
    assert renown_of(db_session, other) == config.RENOWN_CHEER
    assert [row.earned_renown for row in db_session.query(models.Encouragement).all()] == [
        True,
        False,
    ]


def test_notes_and_cheers_diminish_on_their_own_tracks(friends, db_session):
    mine, _, theirs, other = friends
    workout = post_workout(mine)
    url = f"/api/workouts/{workout['id']}/encourage"
    theirs.post(url, json={"kind": "cheer"})
    theirs.post(url, json={"kind": "note", "body": "Strong week."})
    assert renown_of(db_session, other) == config.RENOWN_CHEER + config.RENOWN_NOTE
    theirs.post(url, json={"kind": "note", "body": "Again on Sunday?"})
    assert renown_of(db_session, other) == config.RENOWN_CHEER + config.RENOWN_NOTE


def test_renown_comes_back_once_the_window_has_passed(friends, db_session):
    mine, _, theirs, other = friends
    first = post_workout(mine, offset_min=0)
    second = post_workout(mine, offset_min=30)
    theirs.post(f"/api/workouts/{first['id']}/encourage", json={"kind": "cheer"})

    # Age the earning row past the window rather than waiting a week for it.
    row = db_session.query(models.Encouragement).one()
    row.created_at = security.now_utc() - dt.timedelta(
        days=config.RENOWN_WINDOW_DAYS, hours=1
    )
    db_session.commit()

    theirs.post(f"/api/workouts/{second['id']}/encourage", json={"kind": "cheer"})
    assert renown_of(db_session, other) == 2 * config.RENOWN_CHEER


def test_a_refused_cheer_pays_nothing(friends, db_session):
    mine, _, theirs, other = friends
    first = post_workout(mine, offset_min=0)
    theirs.post(f"/api/workouts/{first['id']}/encourage", json={"kind": "cheer"})
    # Aged out of the window, so a second earning cheer would be allowed; the
    # duplicate is refused by the index before it can be one.
    row = db_session.query(models.Encouragement).one()
    row.created_at = security.now_utc() - dt.timedelta(
        days=config.RENOWN_WINDOW_DAYS, hours=1
    )
    db_session.commit()

    assert (
        theirs.post(
            f"/api/workouts/{first['id']}/encourage", json={"kind": "cheer"}
        ).status_code
        == 409
    )
    assert renown_of(db_session, other) == config.RENOWN_CHEER
    assert db_session.query(models.Encouragement).count() == 1


def test_your_own_profile_carries_your_flourish_stage(friends, db_session):
    mine, member, _, _ = friends
    assert mine.get("/api/profile").json()["flourish"] == 0
    row = db_session.get(models.UserProgress, member.id)
    row.renown = config.FLOURISH_RENOWN[1]
    db_session.commit()
    assert mine.get("/api/profile").json()["flourish"] == 2


def test_no_response_ever_carries_the_renown_number(friends, db_session):
    mine, _, theirs, other = friends
    workout = post_workout(mine)
    theirs.post(f"/api/workouts/{workout['id']}/encourage", json={"kind": "cheer"})
    for path in ("/api/profile", "/api/friends", "/api/feed", "/api/recap"):
        assert "renown" not in theirs.get(path).text


# --------------------------------------------------------------------------
# The recap letter
# --------------------------------------------------------------------------


def test_the_letter_reads_in_order_and_carries_the_words(friends, db_session):
    mine, _, theirs, _ = friends
    first = post_workout(mine, offset_min=0)
    second = post_workout(mine, offset_min=30)
    theirs.post(f"/api/workouts/{first['id']}/encourage", json={"kind": "cheer"})
    theirs.post(f"/api/workouts/{second['id']}/encourage", json={"kind": "cheer"})
    theirs.post(
        f"/api/workouts/{first['id']}/encourage",
        json={"kind": "note", "body": "That hill is horrible. Well done."},
    )

    letter = mine.get("/api/recap").json()
    assert list(letter) == [
        "since",
        "miles",
        "encouragement",
        "race_badges",
        "achievements",
        "chests",
        "flourish_stage",
        "flourish_rose",
    ]
    received = letter["encouragement"]
    assert received["cheer_count"] == 2
    assert sorted(row["workout_id"] for row in received["cheers"]) == sorted(
        [first["id"], second["id"]]
    )
    assert len(received["notes"]) == 1
    assert received["notes"][0]["body"] == "That hill is horrible. Well done."
    assert received["notes"][0]["username"] == "mate"
    assert received["notes"][0]["workout_id"] == first["id"]


def test_the_letter_forgets_what_has_been_acknowledged(friends, db_session):
    mine, _, theirs, _ = friends
    workout = post_workout(mine)
    theirs.post(f"/api/workouts/{workout['id']}/encourage", json={"kind": "cheer"})
    assert mine.get("/api/recap").json()["encouragement"]["cheer_count"] == 1
    assert mine.post("/api/recap/ack").status_code == 204
    quiet = mine.get("/api/recap").json()["encouragement"]
    assert quiet == {"cheers": [], "cheer_count": 0, "notes": []}


def test_the_letter_says_when_the_flourish_grew(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(theirs)
    first = mine.get("/api/recap").json()
    assert (first["flourish_stage"], first["flourish_rose"]) == (0, False)
    mine.post("/api/recap/ack")

    # Just short of the first stage, so one note carries them over it.
    row = db_session.get(models.UserProgress, member.id)
    row.renown = config.FLOURISH_RENOWN[0] - config.RENOWN_NOTE
    db_session.commit()
    mine.post(
        f"/api/workouts/{workout['id']}/encourage",
        json={"kind": "note", "body": "Good to see you back out."},
    )

    grown = mine.get("/api/recap").json()
    assert (grown["flourish_stage"], grown["flourish_rose"]) == (1, True)
    mine.post("/api/recap/ack")
    # Still stage one afterwards, and no longer news.
    settled = mine.get("/api/recap").json()
    assert (settled["flourish_stage"], settled["flourish_rose"]) == (1, False)


def test_the_new_limiters_are_registered_for_the_reset():
    from app import throttle

    names = {limiter.name for limiter in throttle._ALL_LIMITERS}
    assert {"invite", "encourage"} <= names
    assert throttle.invite_limiter.max_attempts == 10
    assert throttle.encourage_limiter.max_attempts == 30


# --------------------------------------------------------------------------
# The name a person appears under
# --------------------------------------------------------------------------


def test_a_feed_row_carries_the_display_name_of_whoever_ran(signed_in, db_session, member, mate):
    other, theirs = mate
    befriend(db_session, member, other)
    other.first_name, other.last_name = "Sam", "Fields"
    db_session.commit()
    post_workout(theirs, miles=4.0)

    row = signed_in.get("/api/feed").json()[0]
    assert set(row) == FRIEND_ROW_KEYS
    # The username stays: it is the login and the invite identity, and it is
    # what a card falls back to when nobody has given a name.
    assert row["user"]["username"] == "mate"
    assert row["user"]["display_name"] == "Sam Fields"


def test_a_person_with_no_name_given_has_none(signed_in, db_session, member, mate):
    other, theirs = mate
    befriend(db_session, member, other)
    post_workout(theirs, miles=2.0)
    assert signed_in.get("/api/feed").json()[0]["user"]["display_name"] is None


def test_the_friends_list_carries_the_same_name(signed_in, db_session, member, mate):
    other, _ = mate
    befriend(db_session, member, other)
    other.first_name = "Sam"
    db_session.commit()
    assert signed_in.get("/api/friends").json()["friends"][0]["display_name"] == "Sam"


def test_a_display_name_is_the_halves_that_are_there():
    assert fellowship.display_name("Justin", "Case") == "Justin Case"
    assert fellowship.display_name("Justin", None) == "Justin"
    assert fellowship.display_name(None, "Case") == "Case"
    assert fellowship.display_name(None, None) is None
    assert fellowship.display_name("  ", "") is None


def test_the_email_change_limiter_is_registered_for_the_reset():
    from app import throttle

    names = {limiter.name for limiter in throttle._ALL_LIMITERS}
    assert "email-change" in names
    assert throttle.email_change_limiter.max_attempts == 3
