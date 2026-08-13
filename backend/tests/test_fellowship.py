"""Friends, the feed, encouragement, renown, and what the recap makes of it.

Every account and every workout here is invented. The privacy rules are the
point of most of these cases: a friend sees a headline and a stranger sees
nothing, and both of those are asserted against the whole response rather than
against the one field that happens to be wrong today.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config, fellowship, models, progress, security
from app.main import app as fastapi_app
from app.routers.fellowship import MAX_OUTBOUND_INVITES, TOO_MANY_INVITES
from conftest import LETTER_KEYS, let_a_moment_pass, make_user, neutral_start

# The photo upload helper, borrowed rather than written twice: what a friend
# sees of a picture is tested here, and how one is stored is tested there.
from test_workouts import attach, attach_video

# What a feed row carries for somebody else's workout when they have hidden
# nothing, which is every account until it says otherwise. Asserted as a whole
# set: a new field joining the row has to be typed here to pass.
FRIEND_ROW_KEYS = {
    "workout_id",
    "user",
    "activity",
    # Never kept back: it qualifies the activity rather than saying anything
    # about a body, and the card draws a treadmill from it.
    "indoor",
    "start_ts",
    "distance_mi",
    "duration_s",
    # The two the owner may keep back. Sent by default: a friend sees what you
    # did, and the switches for these are in Settings.
    "avg_hr",
    "active_kcal",
    "medals",
    "has_route",
    # The words, the pictures, and the video are on a friend's row in full: a
    # post is something somebody chose to write, not something read off their
    # body.
    "title",
    "post",
    "photos",
    "videos",
    "source",
    # What it was done in, or null. Never kept back: shoes are a fact about the
    # kit rather than a number about a body, and the size behind them is on the
    # gear card either way.
    "gear",
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


def post_workout(
    db_session,
    user_id: int,
    *,
    activity="run",
    miles=3.5,
    offset_min=0,
    avg_hr=142.0,
    active_kcal=300.0,
) -> models.Workout:
    """One workout written straight in and credited, the way a sync would.

    It carries energy and a heart rate on purpose: several of the cases below
    are about which of those a friend is told, and a row that never held the
    numbers would pass them whatever the serializer sends.
    """
    row = models.Workout(
        user_id=user_id,
        activity=activity,
        start_ts=neutral_start() + dt.timedelta(minutes=offset_min),
        duration_s=int(miles * 10 * 60),
        distance_mi=miles,
        active_kcal=active_kcal,
        avg_hr=avg_hr,
        source="sync",
        flags={},
        created_at=security.now_utc(),
    )
    db_session.add(row)
    db_session.commit()
    # Medals are read off the table rather than recomputed, so the pipeline has
    # to have run before a feed row can name one.
    progress.process_user(db_session, user_id)
    return row


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
# The roster search
# --------------------------------------------------------------------------


def test_a_member_is_found_by_username_and_by_the_name_they_go_by(signed_in, db_session):
    other, other_client = sign_in(db_session, "aroweing")
    other_client.patch("/api/profile", json={"first_name": "Ada", "last_name": "Rowe"})

    for query in ("arow", "AROW", "ada", "rowe", "ada row"):
        found = signed_in.get("/api/members", params={"q": query})
        assert found.status_code == 200, query
        assert [row["user_id"] for row in found.json()] == [other.id], query
    # And what comes back is the restricted card, said outright.
    row = signed_in.get("/api/members", params={"q": "ada"}).json()[0]
    assert row["restricted"] is True
    assert row["display_name"] == "Ada Rowe"
    assert row["friendship"] == "none"
    assert "level" not in row and "miles" not in row and "medals" not in row


def test_a_search_is_not_a_way_to_read_the_roster(signed_in, db_session):
    sign_in(db_session, "mate")
    sign_in(db_session, "other")
    # Nothing at all for an empty query or a single letter: a roster is not
    # something to scroll, and one character is scrolling it.
    assert signed_in.get("/api/members").json() == []
    assert signed_in.get("/api/members", params={"q": ""}).json() == []
    assert signed_in.get("/api/members", params={"q": "m"}).json() == []
    assert signed_in.get("/api/members", params={"q": "  m  "}).json() == []
    # And a wildcard is a letter like any other rather than a pattern.
    assert signed_in.get("/api/members", params={"q": "%%"}).json() == []


def test_a_search_never_finds_yourself(signed_in, db_session, member):
    assert signed_in.get("/api/members", params={"q": member.username}).json() == []


def test_a_friend_is_found_and_the_card_says_so(signed_in, db_session, member):
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    row = signed_in.get("/api/members", params={"q": "mate"}).json()[0]
    assert row["friendship"] == "friends"


def test_a_search_caps_what_it_answers_and_counts_nothing(signed_in, db_session):
    # Accounts rather than sessions: none of these has to sign in for a search
    # to find them, and twenty-one sign-ins would spend the login allowance.
    for index in range(21):
        make_user(db_session, f"walker{index:02d}", f"walker{index:02d}-password-1")
    found = signed_in.get("/api/members", params={"q": "walker"})
    rows = found.json()
    assert len(rows) == 20
    # By name, so the same search twice reads the same way round.
    assert [row["username"] for row in rows] == sorted(row["username"] for row in rows)
    # No total anywhere: a list is a list, not a count of what it left out.
    assert isinstance(rows, list)


def test_the_search_is_for_members_only(client, db_session, member):
    """Signed out is nothing at all. The room is one somebody was let into."""
    client.cookies.clear()
    assert client.get("/api/members", params={"q": "run"}).status_code == 401


def test_the_invite_form_still_proves_nothing_a_search_does_not(signed_in, db_session):
    """R16 survives untouched. The 204 answers the same for a name that exists
    and one that does not, which is the same answer it always gave."""
    sign_in(db_session, "realname")
    real = signed_in.post("/api/friends/invite", json={"username": "realname"})
    invented = signed_in.post("/api/friends/invite", json={"username": "nobodyatall"})
    assert real.status_code == invented.status_code == 204
    assert real.content == invented.content


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
        "displayed_badges",
    }
    assert card["display_name"] is None
    assert card["flourish"] == 2


def test_an_invite_never_says_whether_the_name_existed(signed_in, mate):
    assert (
        signed_in.post("/api/friends/invite", json={"username": "nobody-here"}).status_code
        == 204
    )
    # The name is on the sent list because it was typed, not because anybody
    # answers to it. That is the whole of the fix: the list is a record of what
    # the sender did, and reading it back tells them nothing new.
    assert signed_in.get("/api/friends").json()["pending_out"] == [{"username": "nobody-here"}]
    # A duplicate and a reverse duplicate are both quiet no-ops.
    signed_in.post("/api/friends/invite", json={"username": "mate"})
    signed_in.post("/api/friends/invite", json={"username": "MATE"})
    assert signed_in.get("/api/friends").json()["pending_out"] == [
        {"username": "mate"},
        {"username": "nobody-here"},
    ]


def test_the_sent_list_reads_the_same_for_a_real_name_and_an_invented_one(
    signed_in, db_session, mate
):
    """The oracle, closed. Invite, read, cancel, repeat is what walking the
    username space looked like, so the two runs of it have to be identical
    byte for byte: the only thing that differs is the name that was typed."""

    def run(name: str) -> tuple[int, object, int]:
        sent = signed_in.post("/api/friends/invite", json={"username": name})
        listed = signed_in.get("/api/friends").json()["pending_out"]
        cancelled = signed_in.delete(f"/api/friends/invites/{name}")
        assert signed_in.get("/api/friends").json()["pending_out"] == []
        return sent.status_code, listed, cancelled.status_code

    real = run("mate")
    invented = run("nobody-here")
    assert real == (204, [{"username": "mate"}], 204)
    # The same status codes and the same shape, and the name in it is the one
    # that went in. Nothing here can tell the two accounts apart.
    assert invented == (204, [{"username": "nobody-here"}], 204)
    # The friendship row was still written for the one that resolved, so the
    # invite itself was really sent while the list said nothing about it.
    assert db_session.query(models.Friendship).count() == 0


def test_a_declined_invite_stays_on_the_sent_list(signed_in, db_session, member, mate):
    """A decline is not news the sender gets. Leaving the name where it was is
    what keeps absence from being an answer."""
    other, other_client = mate
    signed_in.post("/api/friends/invite", json={"username": "mate"})
    assert other_client.delete(f"/api/friends/{member.id}").status_code == 204

    assert other_client.get("/api/friends").json()["pending_in"] == []
    assert db_session.query(models.Friendship).count() == 0
    assert signed_in.get("/api/friends").json()["pending_out"] == [{"username": "mate"}]


def test_accepting_takes_the_name_off_the_sent_list(signed_in, member, mate):
    other, other_client = mate
    signed_in.post("/api/friends/invite", json={"username": "mate"})
    # Both of them asked, which is the case where a second row is left behind.
    other_client.post("/api/friends/invite", json={"username": member.username})
    assert other_client.post(f"/api/friends/{member.id}/accept").status_code == 204

    assert signed_in.get("/api/friends").json()["pending_out"] == []
    assert other_client.get("/api/friends").json()["pending_out"] == []


def test_cancelling_takes_back_the_invite_the_other_side_is_holding(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    signed_in.post("/api/friends/invite", json={"username": "mate"})
    assert [card["username"] for card in other_client.get("/api/friends").json()["pending_in"]] == [
        member.username
    ]

    assert signed_in.delete("/api/friends/invites/MATE").status_code == 204
    assert signed_in.get("/api/friends").json()["pending_out"] == []
    assert other_client.get("/api/friends").json()["pending_in"] == []
    assert db_session.query(models.Friendship).count() == 0
    # Cancelling something that was never sent is the same 204, said to nobody.
    assert signed_in.delete("/api/friends/invites/nobody-here").status_code == 204


def test_cancelling_never_ends_a_friendship(signed_in, db_session, member, mate):
    """The cancel verb is for invites only. Unfriending is the other one, and a
    name typed into this one must not quietly do it."""
    other, other_client = mate
    befriend(db_session, member, other)
    assert signed_in.delete("/api/friends/invites/mate").status_code == 204
    assert [card["username"] for card in signed_in.get("/api/friends").json()["friends"]] == [
        "mate"
    ]


def test_the_sent_list_stops_at_a_hundred_names(signed_in, db_session, member):
    # Written straight in rather than sent one at a time: a hundred invites is
    # ten times what the invite limiter allows in a minute, and the cap being
    # tested here is the other one.
    for index in range(MAX_OUTBOUND_INVITES):
        db_session.add(
            models.OutboundInvite(
                user_id=member.id, username=f"name-{index}", created_at=security.now_utc()
            )
        )
    db_session.commit()

    refused = signed_in.post("/api/friends/invite", json={"username": "one-too-many"})
    assert refused.status_code == 400
    assert refused.json() == {"detail": TOO_MANY_INVITES}
    assert len(signed_in.get("/api/friends").json()["pending_out"]) == MAX_OUTBOUND_INVITES
    # Room again the moment one is cancelled.
    assert signed_in.delete("/api/friends/invites/name-0").status_code == 204
    assert (
        signed_in.post("/api/friends/invite", json={"username": "one-too-many"}).status_code == 204
    )


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


def test_a_stranger_sees_nothing_of_yours(signed_in, db_session, member, mate):
    _, other_client = mate
    post_workout(db_session, member.id)
    assert other_client.get("/api/feed").json() == []


def test_a_pending_invite_shows_nothing_either(signed_in, db_session, member, mate):
    _, other_client = mate
    post_workout(db_session, member.id)
    signed_in.post("/api/friends/invite", json={"username": "mate"})
    assert other_client.get("/api/feed").json() == []


def test_a_friend_sees_the_whole_workout_by_default(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    workout = post_workout(db_session, member.id, miles=3.5)

    rows = other_client.get("/api/feed").json()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == FRIEND_ROW_KEYS
    assert row["own"] is False
    assert row["workout_id"] == workout.id
    assert row["distance_mi"] == 3.5
    assert row["duration_s"] == 2100
    # Nothing hidden, so the numbers a body was making are on the row: this is
    # the default every account starts at.
    assert row["avg_hr"] == 142.0
    assert row["active_kcal"] == 300.0
    assert row["medals"] == ["race_5k"]
    assert row["user"]["username"] == member.username
    assert row["encouragement"] == {"cheers": 0, "notes": 0, "cheered_by_me": False}
    # What is on nobody's row but their own, spelled out so a future field
    # cannot quietly join the row.
    for withheld in ("flags", "pace", "xp", "gear_id"):
        assert withheld not in row


def test_your_own_rows_keep_their_experience(signed_in, db_session, member):
    post_workout(db_session, member.id, activity="walk", miles=2.0)
    row = signed_in.get("/api/feed").json()[0]
    assert row["own"] is True
    assert row["xp"] == 2.0
    # The gear id rides with the experience: both are the owner's alone, one
    # because it is what the workout earned and one because it only ever fills
    # the owner's own picker.
    assert set(row) == FRIEND_ROW_KEYS | {"xp", "gear_id"}


def test_the_feed_mixes_both_accounts_newest_first(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    post_workout(db_session, member.id, offset_min=0)
    post_workout(db_session, other.id, offset_min=30)
    post_workout(db_session, member.id, offset_min=60)

    rows = signed_in.get("/api/feed").json()
    assert [row["own"] for row in rows] == [True, False, True]
    assert rows[0]["start_ts"] > rows[1]["start_ts"] > rows[2]["start_ts"]


def test_the_feed_pages_with_the_before_cursor(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    post_workout(db_session, member.id, offset_min=0)
    post_workout(db_session, other.id, offset_min=30)

    rows = signed_in.get("/api/feed").json()
    older = signed_in.get("/api/feed", params={"before": rows[0]["start_ts"]}).json()
    assert [row["workout_id"] for row in older] == [rows[1]["workout_id"]]
    assert signed_in.get("/api/feed", params={"before": "not-a-timestamp"}).status_code == 400


def test_the_feed_stops_at_one_page(signed_in, db_session, member):
    for offset in range(22):
        post_workout(db_session, member.id, miles=1.0, offset_min=offset * 5)
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
    workout = post_workout(db_session, member.id)
    _add_route(db_session, workout.id)

    assert signed_in.get("/api/feed").json()[0]["has_route"] is True
    response = other_client.get(f"/api/workouts/{workout.id}/route")
    assert response.status_code == 200
    assert response.json()["points"] == [[10.0, 20.0], [10.001, 20.0]]


def test_a_stranger_still_cannot(signed_in, db_session, member, mate):
    _, other_client = mate
    workout = post_workout(db_session, member.id)
    _add_route(db_session, workout.id)
    assert other_client.get(f"/api/workouts/{workout.id}/route").status_code == 404


def test_a_pending_invite_does_not_open_a_route(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other, status="pending")
    workout = post_workout(db_session, member.id)
    _add_route(db_session, workout.id)
    assert other_client.get(f"/api/workouts/{workout.id}/route").status_code == 404


# --------------------------------------------------------------------------
# What the owner keeps back
# --------------------------------------------------------------------------

# Numbers that appear nowhere else in a response, so a case can look for them
# in the raw text rather than only in the keys it thought to check.
TELLTALE_HR = 163.0
TELLTALE_KCAL = 777.0


def hide(client_holding_session, *fields: str) -> None:
    """Whoever holds that session asks for those fields to be kept back, through
    the endpoint the screen uses rather than by writing the column."""
    response = client_holding_session.patch(
        "/api/settings", json={"hidden_from_friends": list(fields)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["hidden_from_friends"] == list(fields)


def test_a_hidden_field_is_nowhere_in_what_a_friend_receives(
    signed_in, db_session, member, mate
):
    """The whole point of the round, asserted against the text of the response.

    Read as a string rather than as keys: a field dropped from the row but
    still carried under some other name, or inside the person card, would pass
    a key check and fail this one.
    """
    other, other_client = mate
    befriend(db_session, member, other)
    post_workout(db_session, member.id, avg_hr=TELLTALE_HR, active_kcal=TELLTALE_KCAL)
    hide(signed_in, "avg_hr", "active_kcal")

    response = other_client.get("/api/feed")
    row = response.json()[0]
    assert set(row) == FRIEND_ROW_KEYS - {"avg_hr", "active_kcal"}
    assert "avg_hr" not in response.text
    assert "active_kcal" not in response.text
    assert str(TELLTALE_HR) not in response.text
    assert str(TELLTALE_KCAL) not in response.text
    # Nothing else went with them: the card still says what they did.
    assert row["distance_mi"] == 3.5
    assert row["duration_s"] == 2100


def test_hiding_one_leaves_the_others_alone(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    post_workout(db_session, member.id, avg_hr=TELLTALE_HR, active_kcal=TELLTALE_KCAL)
    hide(signed_in, "avg_hr")

    row = other_client.get("/api/feed").json()[0]
    assert "avg_hr" not in row
    assert row["active_kcal"] == TELLTALE_KCAL


def test_hiding_takes_nothing_off_your_own_rows(signed_in, db_session, member):
    """Hiding something from your friends is not hiding it from yourself."""
    post_workout(db_session, member.id, avg_hr=TELLTALE_HR, active_kcal=TELLTALE_KCAL)
    hide(signed_in, "avg_hr", "active_kcal", "route")

    row = signed_in.get("/api/feed").json()[0]
    assert row["own"] is True
    assert row["avg_hr"] == TELLTALE_HR
    assert row["active_kcal"] == TELLTALE_KCAL


def test_a_hidden_route_is_neither_drawn_nor_served(signed_in, db_session, member, mate):
    """Two halves of one rule: the card is told there is no line to draw, and
    the endpoint behind it refuses the line as well. Either alone would leave
    the map one request away."""
    other, other_client = mate
    befriend(db_session, member, other)
    workout = post_workout(db_session, member.id)
    _add_route(db_session, workout.id)
    hide(signed_in, "route")

    assert other_client.get("/api/feed").json()[0]["has_route"] is False
    assert other_client.get(f"/api/workouts/{workout.id}/route").status_code == 404
    # Still yours to look at, on your own card and from the endpoint.
    assert signed_in.get("/api/feed").json()[0]["has_route"] is True
    assert signed_in.get(f"/api/workouts/{workout.id}/route").status_code == 200


def test_hiding_the_route_leaves_the_line_readable_to_nobody_else(
    signed_in, db_session, member, mate
):
    """The coordinates themselves, looked for in the text of both responses: a
    route that stopped being announced but was still shipped inside the row
    would be the same leak with a quieter name on it."""
    other, other_client = mate
    befriend(db_session, member, other)
    workout = post_workout(db_session, member.id)
    _add_route(db_session, workout.id)
    hide(signed_in, "route")

    for response in (
        other_client.get("/api/feed"),
        other_client.get(f"/api/profile/{member.id}"),
    ):
        assert "10.001" not in response.text
        assert "points" not in response.text


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
    workout = post_workout(db_session, member.id)

    response = theirs.post(f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"})
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


def test_only_one_cheer_each(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    assert theirs.post(f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"}).status_code == 201
    again = theirs.post(f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"})
    assert again.status_code == 409


def test_notes_are_not_limited_to_one(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    for body in ("Good week.", "See you Saturday."):
        response = theirs.post(
            f"/api/workouts/{workout.id}/encourage", json={"kind": "note", "body": body}
        )
        assert response.status_code == 201
    assert response.json()["encouragement"]["notes"] == 2


def test_a_note_needs_words_and_has_a_ceiling(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    url = f"/api/workouts/{workout.id}/encourage"
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


def test_encouragement_is_refused_where_it_does_not_belong(signed_in, db_session, member, mate):
    other, other_client = mate
    own = post_workout(db_session, member.id)
    assert (
        signed_in.post(f"/api/workouts/{own.id}/encourage", json={"kind": "cheer"}).status_code
        == 400
    )
    # A stranger's workout answers the same way a workout that never existed
    # does, so an id cannot be walked to find out whose it is.
    assert (
        other_client.post(f"/api/workouts/{own.id}/encourage", json={"kind": "cheer"}).status_code
        == 404
    )
    assert (
        other_client.post("/api/workouts/424242/encourage", json={"kind": "cheer"}).status_code
        == 404
    )
    assert (
        signed_in.post(f"/api/workouts/{own.id}/encourage", json={"kind": "clap"}).status_code
        == 400
    )


def test_the_owner_reads_the_notes_on_their_own_workout(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    # One writer with a name to go by and one without, so the list is asserted
    # to name people the way every other card does.
    other.first_name = "Ada"
    other.last_name = "Rowe"
    db_session.commit()
    third, third_client = sign_in(db_session, "neighbour")
    befriend(db_session, member, third)

    url = f"/api/workouts/{workout.id}/encourage"
    assert theirs.post(url, json={"kind": "note", "body": "Strong finish."}).status_code == 201
    # The clock is pinned, so the first note is aged to make it the older one
    # rather than a row sharing a timestamp with the second.
    let_a_moment_pass(db_session)
    assert (
        third_client.post(url, json={"kind": "note", "body": "See you Saturday."}).status_code
        == 201
    )
    # Wordless, so it counts on the card and belongs nowhere in this list.
    assert theirs.post(url, json={"kind": "cheer"}).status_code == 201

    response = mine.get(f"/api/workouts/{workout.id}/notes")
    assert response.status_code == 200
    rows = response.json()
    named = [(row["user"]["display_name"] or row["user"]["username"], row["body"]) for row in rows]
    assert named == [
        ("Ada Rowe", "Strong finish."),
        ("neighbour", "See you Saturday."),
    ]
    assert rows[0]["created_at"] < rows[1]["created_at"]
    # Enough of a person to draw the frame beside the words and to open their
    # profile from it, which is the whole reason the block is here.
    assert rows[0]["user"]["user_id"] == other.id
    assert rows[0]["user"]["has_avatar"] is False
    assert "border_tier" in rows[0]["user"] and "flourish" in rows[0]["user"]


def test_the_words_on_a_workout_are_read_by_whoever_can_see_it(friends, db_session):
    """The club reversal: a comment is part of the card rather than a letter to
    the runner, so everybody whose feed the workout reaches reads the thread."""
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    assert (
        theirs.post(
            f"/api/workouts/{workout.id}/encourage",
            json={"kind": "note", "body": "Good week."},
        ).status_code
        == 201
    )
    # The friend who wrote it reads it back under the card it is on.
    read = theirs.get(f"/api/workouts/{workout.id}/notes")
    assert read.status_code == 200
    assert [row["body"] for row in read.json()] == ["Good week."]
    # A member who cannot see the workout is answered exactly as before.
    _, outsider = sign_in(db_session, "stranger")
    assert outsider.get(f"/api/workouts/{workout.id}/notes").status_code == 404
    # The same answer a workout that never existed gets, so an id cannot be
    # walked to find out whose it is.
    assert mine.get("/api/workouts/424242/notes").status_code == 404
    assert (
        outsider.get(f"/api/workouts/{workout.id}/notes").content
        == outsider.get("/api/workouts/424242/notes").content
    )


def test_a_deleted_workout_takes_its_thread_with_it(friends, db_session):
    """The reading gate is the feed's, and a deleted workout is on nobody's."""
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    assert (
        theirs.post(
            f"/api/workouts/{workout.id}/encourage",
            json={"kind": "note", "body": "Good week."},
        ).status_code
        == 201
    )
    assert mine.delete(f"/api/workouts/{workout.id}").status_code == 204
    assert theirs.get(f"/api/workouts/{workout.id}/notes").status_code == 404
    assert mine.get(f"/api/workouts/{workout.id}/notes").status_code == 404


def test_a_viewer_who_cannot_see_a_workout_cannot_write_on_it_either(friends, db_session):
    """Writing did not widen with reading. Visibility still equals friendship,
    so a member who is not the owner's friend is refused the same 404."""
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    _, outsider = sign_in(db_session, "stranger")
    assert (
        outsider.post(
            f"/api/workouts/{workout.id}/encourage",
            json={"kind": "note", "body": "Hello."},
        ).status_code
        == 404
    )


def test_a_workout_nobody_wrote_on_answers_an_empty_list(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    assert (
        theirs.post(
            f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"}
        ).status_code
        == 201
    )
    response = mine.get(f"/api/workouts/{workout.id}/notes")
    assert response.status_code == 200
    assert response.json() == []


def test_reading_notes_needs_a_session(client, db_session, member):
    workout = post_workout(db_session, member.id)
    assert client.get(f"/api/workouts/{workout.id}/notes").status_code == 401


# --------------------------------------------------------------------------
# Renown and the flourish
# --------------------------------------------------------------------------


def test_flourish_stages_follow_the_thresholds():
    assert config.FLOURISH_RENOWN == (10, 40, 120)
    for renown, stage in ((0, 0), (9, 0), (10, 1), (39, 1), (40, 2), (119, 2), (120, 3), (9999, 3)):
        assert fellowship.flourish_stage(renown) == stage


def test_giving_earns_renown_and_receiving_earns_none(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    theirs.post(f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"})
    assert renown_of(db_session, other) == config.RENOWN_CHEER
    assert renown_of(db_session, member) == 0


def test_the_second_cheer_of_the_week_still_arrives_but_pays_nothing(friends, db_session):
    mine, member, theirs, other = friends
    first = post_workout(db_session, member.id, offset_min=0)
    second = post_workout(db_session, member.id, offset_min=30)
    theirs.post(f"/api/workouts/{first.id}/encourage", json={"kind": "cheer"})
    response = theirs.post(f"/api/workouts/{second.id}/encourage", json={"kind": "cheer"})

    assert response.status_code == 201
    assert response.json()["encouragement"]["cheers"] == 1
    assert renown_of(db_session, other) == config.RENOWN_CHEER
    assert [row.earned_renown for row in db_session.query(models.Encouragement).all()] == [
        True,
        False,
    ]


def test_notes_and_cheers_diminish_on_their_own_tracks(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    url = f"/api/workouts/{workout.id}/encourage"
    theirs.post(url, json={"kind": "cheer"})
    theirs.post(url, json={"kind": "note", "body": "Strong week."})
    assert renown_of(db_session, other) == config.RENOWN_CHEER + config.RENOWN_NOTE
    theirs.post(url, json={"kind": "note", "body": "Again on Sunday?"})
    assert renown_of(db_session, other) == config.RENOWN_CHEER + config.RENOWN_NOTE


def test_renown_comes_back_once_the_window_has_passed(friends, db_session):
    mine, member, theirs, other = friends
    first = post_workout(db_session, member.id, offset_min=0)
    second = post_workout(db_session, member.id, offset_min=30)
    theirs.post(f"/api/workouts/{first.id}/encourage", json={"kind": "cheer"})

    # Age the earning row past the window rather than waiting a week for it.
    row = db_session.query(models.Encouragement).one()
    row.created_at = security.now_utc() - dt.timedelta(
        days=config.RENOWN_WINDOW_DAYS, hours=1
    )
    db_session.commit()

    theirs.post(f"/api/workouts/{second.id}/encourage", json={"kind": "cheer"})
    assert renown_of(db_session, other) == 2 * config.RENOWN_CHEER


def test_a_refused_cheer_pays_nothing(friends, db_session):
    mine, member, theirs, other = friends
    first = post_workout(db_session, member.id, offset_min=0)
    theirs.post(f"/api/workouts/{first.id}/encourage", json={"kind": "cheer"})
    # Aged out of the window, so a second earning cheer would be allowed; the
    # duplicate is refused by the index before it can be one.
    row = db_session.query(models.Encouragement).one()
    row.created_at = security.now_utc() - dt.timedelta(
        days=config.RENOWN_WINDOW_DAYS, hours=1
    )
    db_session.commit()

    assert (
        theirs.post(
            f"/api/workouts/{first.id}/encourage", json={"kind": "cheer"}
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
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    theirs.post(f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"})
    for path in ("/api/profile", "/api/friends", "/api/feed", "/api/recap"):
        assert "renown" not in theirs.get(path).text


# --------------------------------------------------------------------------
# The recap letter
# --------------------------------------------------------------------------


def test_the_letter_reads_in_order_and_carries_the_words(friends, db_session):
    mine, member, theirs, other = friends
    first = post_workout(db_session, member.id, offset_min=0)
    second = post_workout(db_session, member.id, offset_min=30)
    theirs.post(f"/api/workouts/{first.id}/encourage", json={"kind": "cheer"})
    theirs.post(f"/api/workouts/{second.id}/encourage", json={"kind": "cheer"})
    theirs.post(
        f"/api/workouts/{first.id}/encourage",
        json={"kind": "note", "body": "That hill is horrible. Well done."},
    )

    letter = mine.get("/api/recap").json()
    assert list(letter) == LETTER_KEYS
    received = letter["encouragement"]
    assert received["cheer_count"] == 2
    assert sorted(row["workout_id"] for row in received["cheers"]) == sorted(
        [first.id, second.id]
    )
    assert len(received["notes"]) == 1
    assert received["notes"][0]["body"] == "That hill is horrible. Well done."
    assert received["notes"][0]["username"] == "mate"
    assert received["notes"][0]["workout_id"] == first.id


def test_the_letter_forgets_what_has_been_acknowledged(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(db_session, member.id)
    theirs.post(f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"})
    assert mine.get("/api/recap").json()["encouragement"]["cheer_count"] == 1
    assert mine.post("/api/recap/ack").status_code == 204
    quiet = mine.get("/api/recap").json()["encouragement"]
    assert quiet == {"cheers": [], "cheer_count": 0, "notes": []}


def test_the_letter_says_when_the_flourish_grew(friends, db_session):
    mine, member, theirs, other = friends
    workout = post_workout(db_session, other.id)
    first = mine.get("/api/recap").json()
    assert (first["flourish_stage"], first["flourish_rose"]) == (0, False)
    mine.post("/api/recap/ack")
    let_a_moment_pass(db_session)

    # Just short of the first stage, so one note carries them over it.
    row = db_session.get(models.UserProgress, member.id)
    row.renown = config.FLOURISH_RENOWN[0] - config.RENOWN_NOTE
    db_session.commit()
    mine.post(
        f"/api/workouts/{workout.id}/encourage",
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
    post_workout(db_session, other.id, miles=4.0)

    row = signed_in.get("/api/feed").json()[0]
    assert set(row) == FRIEND_ROW_KEYS
    # The username stays: it is the login and the invite identity, and it is
    # what a card falls back to when nobody has given a name.
    assert row["user"]["username"] == "mate"
    assert row["user"]["display_name"] == "Sam Fields"


def test_a_person_with_no_name_given_has_none(signed_in, db_session, member, mate):
    other, theirs = mate
    befriend(db_session, member, other)
    post_workout(db_session, other.id, miles=2.0)
    assert signed_in.get("/api/feed").json()[0]["user"]["display_name"] is None


def test_the_friends_list_carries_the_same_name(signed_in, db_session, member, mate):
    other, _ = mate
    befriend(db_session, member, other)
    other.first_name = "Sam"
    db_session.commit()
    assert signed_in.get("/api/friends").json()["friends"][0]["display_name"] == "Sam"


def test_a_display_name_is_the_halves_that_are_there():
    assert fellowship.display_name("Avery", "Case") == "Avery Case"
    assert fellowship.display_name("Avery", None) == "Avery"
    assert fellowship.display_name(None, "Case") == "Case"
    assert fellowship.display_name(None, None) is None
    assert fellowship.display_name("  ", "") is None


def test_the_email_change_limiter_is_registered_for_the_reset():
    from app import throttle

    names = {limiter.name for limiter in throttle._ALL_LIMITERS}
    assert "email-change" in names
    assert throttle.email_change_limiter.max_attempts == 3


# --------------------------------------------------------------------------
# The medals a person wears
# --------------------------------------------------------------------------

# Everything a person card is allowed to carry, asserted as a whole set so a
# field cannot quietly leave it either.
PERSON_CARD_KEYS = {
    "user_id",
    "username",
    "display_name",
    "has_avatar",
    "border_tier",
    "flourish",
    "displayed_badges",
}


def wear(db_session, user: models.User, *badge_ids: str) -> None:
    """Fill somebody's slots straight from the column, rather than through the
    profile, which would first make them earn each one."""
    user.displayed_badges = list(badge_ids)
    db_session.commit()


def test_a_feed_row_carries_the_medals_that_person_chose(
    signed_in, db_session, member, mate
):
    other, theirs = mate
    befriend(db_session, member, other)
    wear(db_session, other, "race_half", "weekly_25")
    post_workout(db_session, other.id, miles=4.0)

    card = signed_in.get("/api/feed").json()[0]["user"]
    # Slot order, kept as stored: the client draws them left to right.
    assert card["displayed_badges"] == ["race_half", "weekly_25"]


def test_your_own_row_carries_yours(signed_in, db_session, member):
    wear(db_session, member, "weekly_10")
    post_workout(db_session, member.id, miles=2.0)
    row = signed_in.get("/api/feed").json()[0]
    assert row["own"] is True
    assert row["user"]["displayed_badges"] == ["weekly_10"]


def test_wearing_none_reads_as_an_empty_list(signed_in, db_session, member, mate):
    """Never null: the frontend defaults this field, and a null would make the
    two halves disagree about what "no medals" looks like."""
    other, theirs = mate
    befriend(db_session, member, other)
    post_workout(db_session, other.id, miles=2.0)

    card = signed_in.get("/api/feed").json()[0]["user"]
    assert card["displayed_badges"] == []
    assert isinstance(card["displayed_badges"], list)


def test_the_friends_list_carries_them_too(signed_in, db_session, member, mate):
    other, _ = mate
    befriend(db_session, member, other)
    wear(db_session, other, "night_owl")
    assert signed_in.get("/api/friends").json()["friends"][0]["displayed_badges"] == [
        "night_owl"
    ]


def test_the_medals_join_the_card_without_disturbing_it(
    signed_in, db_session, member, mate
):
    """The whole card, asserted at once: the six fields that were there before
    still read the same, and the medals a workout earned are a separate thing
    on a separate key."""
    other, theirs = mate
    befriend(db_session, member, other)
    other.first_name, other.last_name = "Sam", "Fields"
    wear(db_session, other, "early_riser")
    post_workout(db_session, other.id, miles=3.5)

    row = signed_in.get("/api/feed").json()[0]
    assert set(row["user"]) == PERSON_CARD_KEYS
    assert row["user"] == {
        "user_id": other.id,
        "username": "mate",
        "display_name": "Sam Fields",
        "has_avatar": False,
        "border_tier": 1,
        "flourish": 0,
        "displayed_badges": ["early_riser"],
    }
    # Earned by that run, not chosen for the profile, and untouched by any of
    # this.
    assert row["medals"] == ["race_5k"]


# --------------------------------------------------------------------------
# What a friend sees of a post


def test_a_friend_sees_the_title_the_post_and_the_photos(signed_in, db_session, member, mate):
    """A post is a deliberate share, so all three cross to a friend's feed in
    full. This is the one part of somebody else's workout that does."""
    other, theirs = mate
    befriend(db_session, member, other)
    workout = post_workout(db_session, other.id, miles=4.0)
    theirs.patch(
        f"/api/workouts/{workout.id}",
        json={"title": "Round the reservoir", "post": "Wind the whole way back."},
    )
    photo_id = attach(theirs, workout.id).json()["id"]

    row = signed_in.get("/api/feed").json()[0]
    assert row["workout_id"] == workout.id
    assert row["own"] is False
    assert row["title"] == "Round the reservoir"
    assert row["post"] == "Wind the whole way back."
    assert row["photos"] == [photo_id]
    # And the picture itself is readable, which is what the ids are for.
    served = signed_in.get(f"/api/workouts/{workout.id}/photos/{photo_id}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"


def test_your_own_feed_row_carries_them_too(signed_in, db_session, member):
    workout = post_workout(db_session, member.id, miles=2.0)
    signed_in.patch(f"/api/workouts/{workout.id}", json={"title": "Before work"})
    photo_id = attach(signed_in, workout.id).json()["id"]
    row = signed_in.get("/api/feed").json()[0]
    assert row["own"] is True
    assert row["title"] == "Before work"
    assert row["post"] is None
    assert row["photos"] == [photo_id]


def test_a_stranger_cannot_read_a_photo(signed_in, db_session, member, mate):
    """No friendship, so the same 404 a photo that does not exist gets. A
    pending invite is not a friendship either."""
    other, theirs = mate
    workout = post_workout(db_session, other.id, miles=3.0)
    photo_id = attach(theirs, workout.id).json()["id"]

    stranger = signed_in.get(f"/api/workouts/{workout.id}/photos/{photo_id}")
    assert stranger.status_code == 404
    assert stranger.json() == {"detail": "No such photo."}

    befriend(db_session, member, other, status="pending")
    assert signed_in.get(f"/api/workouts/{workout.id}/photos/{photo_id}").status_code == 404


def test_a_friend_sees_the_video_and_can_play_it(signed_in, db_session, member, mate):
    """A video crosses on the post's terms, exactly as a photograph does: it
    was put there to be seen, and the ids on the row are what fetch it."""
    other, theirs = mate
    befriend(db_session, member, other)
    workout = post_workout(db_session, other.id, miles=4.0)
    video_id = attach_video(theirs, workout.id).json()["id"]

    row = signed_in.get("/api/feed").json()[0]
    assert row["videos"] == [video_id]

    served = signed_in.get(f"/api/workouts/{workout.id}/videos/{video_id}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "video/mp4"
    # In ranges to a friend as much as to the owner, or their phone will not
    # play it either.
    part = signed_in.get(
        f"/api/workouts/{workout.id}/videos/{video_id}", headers={"Range": "bytes=0-99"}
    )
    assert part.status_code == 206
    poster = signed_in.get(f"/api/workouts/{workout.id}/videos/{video_id}/poster")
    assert poster.status_code == 200


def test_a_stranger_cannot_read_a_video(signed_in, db_session, member, mate):
    """The photo endpoint's answer, word for word: no friendship, so the same
    404 a video that does not exist gets, and a pending invite is not a
    friendship. The poster is gated with it, because a poster is a picture of
    the video."""
    other, theirs = mate
    workout = post_workout(db_session, other.id, miles=3.0)
    video_id = attach_video(theirs, workout.id).json()["id"]

    stranger = signed_in.get(f"/api/workouts/{workout.id}/videos/{video_id}")
    assert stranger.status_code == 404
    assert stranger.json() == {"detail": "No such video."}
    poster = signed_in.get(f"/api/workouts/{workout.id}/videos/{video_id}/poster")
    assert poster.status_code == 404
    assert poster.json() == {"detail": "No such video."}
    # A stranger asking for a range is answered the same way, not with a 206 of
    # somebody else's video.
    ranged = signed_in.get(
        f"/api/workouts/{workout.id}/videos/{video_id}", headers={"Range": "bytes=0-99"}
    )
    assert ranged.status_code == 404

    befriend(db_session, member, other, status="pending")
    assert signed_in.get(f"/api/workouts/{workout.id}/videos/{video_id}").status_code == 404


def test_a_friend_still_cannot_write_on_your_workout(signed_in, db_session, member, mate):
    other, theirs = mate
    befriend(db_session, member, other)
    workout = post_workout(db_session, member.id, miles=2.0)
    assert theirs.patch(
        f"/api/workouts/{workout.id}", json={"title": "mine now"}
    ).status_code == 404
    assert attach(theirs, workout.id).status_code == 404
    assert attach_video(theirs, workout.id).status_code == 404


def test_the_media_limiters_are_registered_for_the_reset():
    from app import throttle

    names = {limiter.name for limiter in throttle._ALL_LIMITERS}
    assert {"workout-edit", "photo", "video"} <= names
    assert throttle.workout_edit_limiter.max_attempts == 30
    assert throttle.photo_limiter.max_attempts == 10
    # Tighter than the photos', because every accepted call re-encodes.
    assert throttle.video_limiter.max_attempts == 5
