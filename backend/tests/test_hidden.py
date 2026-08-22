"""Keeping one workout off the feeds, and what that does and does not touch.

The policy this file pins, in one sentence: hiding a workout is a display
decision and nothing else. Every case here is one half of that. The first half
is that it disappears from every feed surface, its owner's own included, and
that everything a friend could open on it closes with the same neutral 404 a
workout that does not exist answers. The second half is that the miles are
still miles: the experience, the medals and the totals never hear about it, and
the words already written on it are still in the table when it comes back.
"""

from conftest import log_workout
from test_fellowship import befriend, sign_in
from test_workouts import attach

from app import models


def hide(client, workout_id: int, on: bool = True):
    return client.patch(f"/api/workouts/{workout_id}", json={"hidden": on})


def feed_ids(client) -> list[int]:
    return [row["workout_id"] for row in client.get("/api/feed").json()]


def history_ids(client) -> list[int]:
    return [row["workout_id"] for row in client.get("/api/workouts").json()]


def own_row(client, workout_id: int) -> dict:
    return next(
        row for row in client.get("/api/workouts").json() if row["workout_id"] == workout_id
    )


def give_route(db_session, workout_id: int) -> None:
    db_session.add(
        models.WorkoutRoute(workout_id=workout_id, points=[[10.0, 20.0], [10.001, 20.0]])
    )
    db_session.commit()


# --------------------------------------------------------------------------
# It leaves the feeds
# --------------------------------------------------------------------------


def test_a_hidden_workout_is_off_the_feed_for_a_friend_and_for_its_owner(
    signed_in, db_session, member
):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    kept = log_workout(db_session, member.id, miles=2.0)
    gone = log_workout(db_session, member.id, miles=5.0, offset_min=60)

    assert hide(signed_in, gone.id).status_code == 200

    # The friend's feed, which is the one the switch is about.
    assert feed_ids(other_client) == [kept.id]
    # And the owner's own, on the deletion's terms: it is a disappearance from
    # every feed at once rather than only from other people's.
    assert feed_ids(signed_in) == [kept.id]


def test_a_hidden_workout_is_off_the_recent_list_on_the_profile(
    signed_in, db_session, member
):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    kept = log_workout(db_session, member.id, miles=2.0)
    gone = log_workout(db_session, member.id, miles=5.0, offset_min=60)
    hide(signed_in, gone.id)

    seen = other_client.get(f"/api/profile/{member.id}").json()["workouts"]
    assert [row["workout_id"] for row in seen] == [kept.id]
    # The owner reading their own profile sees the same list: the feed's rule
    # is the feed's rule wherever the rows are drawn.
    mine = signed_in.get(f"/api/profile/{member.id}").json()["workouts"]
    assert [row["workout_id"] for row in mine] == [kept.id]


def test_a_picture_on_a_hidden_workout_is_off_the_profile_strip(
    signed_in, db_session, member
):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    workout = log_workout(db_session, member.id, miles=2.0)
    created = attach(signed_in, workout.id)
    assert created.status_code == 201, created.text

    hide(signed_in, workout.id)

    strip = other_client.get(f"/api/profile/{member.id}").json()["recent_photos"]
    # Nothing rather than a tile whose picture would answer 404 underneath it.
    assert strip == []


# --------------------------------------------------------------------------
# It stays in its own history
# --------------------------------------------------------------------------


def test_the_owner_still_has_it_in_their_history_and_the_row_says_so(
    signed_in, db_session, member
):
    workout = log_workout(db_session, member.id, miles=5.0)
    hide(signed_in, workout.id)

    assert history_ids(signed_in) == [workout.id]
    assert own_row(signed_in, workout.id)["hidden"] is True


def test_a_workout_nobody_has_hidden_says_that_too(signed_in, db_session, member):
    workout = log_workout(db_session, member.id, miles=5.0)
    assert own_row(signed_in, workout.id)["hidden"] is False


def test_a_friend_is_never_told_whether_a_workout_is_hidden(
    signed_in, db_session, member
):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    log_workout(db_session, member.id, miles=2.0)

    row = other_client.get("/api/feed").json()[0]
    assert "hidden" not in row
    seen = other_client.get(f"/api/profile/{member.id}").json()["workouts"][0]
    assert "hidden" not in seen


# --------------------------------------------------------------------------
# The reading gates
# --------------------------------------------------------------------------


def test_a_friend_cannot_open_the_details_the_route_or_a_photo_of_a_hidden_workout(
    signed_in, db_session, member
):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    workout = log_workout(db_session, member.id, miles=5.0)
    give_route(db_session, workout.id)
    photo_id = attach(signed_in, workout.id).json()["id"]

    # Everything opens while it is on the feed, so what follows means something.
    assert other_client.get(f"/api/workouts/{workout.id}/details").status_code == 200
    assert other_client.get(f"/api/workouts/{workout.id}/route").status_code == 200
    assert (
        other_client.get(f"/api/workouts/{workout.id}/photos/{photo_id}").status_code == 200
    )
    assert other_client.get(f"/api/workouts/{workout.id}/notes").status_code == 200

    hide(signed_in, workout.id)

    for path in (
        f"/api/workouts/{workout.id}/details",
        f"/api/workouts/{workout.id}/route",
        f"/api/workouts/{workout.id}/photos/{photo_id}",
        f"/api/workouts/{workout.id}/notes",
    ):
        refused = other_client.get(path)
        assert refused.status_code == 404, path

    # The owner opens every one of them exactly as before: it is off their
    # friends' feeds rather than out of their own history.
    assert signed_in.get(f"/api/workouts/{workout.id}/details").status_code == 200
    assert signed_in.get(f"/api/workouts/{workout.id}/route").status_code == 200
    assert (
        signed_in.get(f"/api/workouts/{workout.id}/photos/{photo_id}").status_code == 200
    )
    assert signed_in.get(f"/api/workouts/{workout.id}/notes").status_code == 200


def test_a_friend_cannot_hype_or_write_on_a_hidden_workout(signed_in, db_session, member):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    workout = log_workout(db_session, member.id, miles=5.0)
    hide(signed_in, workout.id)

    cheer = other_client.post(
        f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"}
    )
    assert cheer.status_code == 404
    note = other_client.post(
        f"/api/workouts/{workout.id}/encourage",
        json={"kind": "note", "body": "Strong one."},
    )
    assert note.status_code == 404


def test_the_hypes_and_notes_already_written_wait_and_come_back(
    signed_in, db_session, member
):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    workout = log_workout(db_session, member.id, miles=5.0)
    assert (
        other_client.post(
            f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"}
        ).status_code
        == 201
    )
    assert (
        other_client.post(
            f"/api/workouts/{workout.id}/encourage",
            json={"kind": "note", "body": "Strong one."},
        ).status_code
        == 201
    )

    hide(signed_in, workout.id)

    # Nothing is deleted by hiding: the rows are where they were.
    assert db_session.query(models.Encouragement).count() == 2
    # And the owner still reads them on their own card.
    said = own_row(signed_in, workout.id)["encouragement"]
    assert said["hype_count"] == 1 and said["note_count"] == 1

    hide(signed_in, workout.id, on=False)

    back = other_client.get("/api/feed").json()[0]
    assert back["workout_id"] == workout.id
    assert back["encouragement"]["hype_count"] == 1
    assert back["encouragement"]["note_count"] == 1
    assert back["encouragement"]["cheered_by_me"] is True


# --------------------------------------------------------------------------
# The switch itself
# --------------------------------------------------------------------------


def test_hiding_and_unhiding_are_the_same_act_from_both_sides(
    signed_in, db_session, member
):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    workout = log_workout(db_session, member.id, miles=5.0)

    hidden = hide(signed_in, workout.id)
    assert hidden.status_code == 200
    assert hidden.json()["hidden"] is True
    assert feed_ids(other_client) == []

    shown = hide(signed_in, workout.id, on=False)
    assert shown.status_code == 200
    assert shown.json()["hidden"] is False
    assert feed_ids(other_client) == [workout.id]


def test_a_sent_null_is_refused_because_a_yes_or_no_has_no_empty_state(
    signed_in, db_session, member
):
    workout = log_workout(db_session, member.id, miles=5.0)
    refused = signed_in.patch(f"/api/workouts/{workout.id}", json={"hidden": None})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Hidden is yes or no."
    db_session.expire_all()
    assert db_session.get(models.Workout, workout.id).hidden_from_feed is False


def test_an_edit_that_says_nothing_about_it_leaves_it_where_it_is(
    signed_in, db_session, member
):
    workout = log_workout(db_session, member.id, miles=5.0)
    hide(signed_in, workout.id)

    titled = signed_in.patch(f"/api/workouts/{workout.id}", json={"title": "Long way"})
    assert titled.status_code == 200
    assert titled.json()["title"] == "Long way"
    assert titled.json()["hidden"] is True


def test_nobody_can_hide_a_workout_that_is_not_theirs(signed_in, db_session, member):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    workout = log_workout(db_session, member.id, miles=5.0)

    assert hide(other_client, workout.id).status_code == 404
    db_session.expire_all()
    assert db_session.get(models.Workout, workout.id).hidden_from_feed is False


# --------------------------------------------------------------------------
# It still counts
# --------------------------------------------------------------------------


def test_hiding_takes_nothing_back_from_the_game(signed_in, db_session, member):
    log_workout(db_session, member.id, miles=2.0)
    workout = log_workout(db_session, member.id, miles=5.0, offset_min=60)
    before = signed_in.get("/api/profile").json()

    hide(signed_in, workout.id)

    after = signed_in.get("/api/profile").json()
    assert after["xp"] == before["xp"]
    assert after["level"] == before["level"]
    assert after["lifetime"]["run"]["distance_mi"] == before["lifetime"]["run"]["distance_mi"]
    assert after["lifetime"]["run"]["workouts"] == before["lifetime"]["run"]["workouts"]
    assert after["week"]["run"]["distance_mi"] == before["week"]["run"]["distance_mi"]
    # The weekly totals behind the Almanac read the same column.
    weeks = signed_in.get("/api/workouts/weeks").json()
    assert weeks[0]["activities"]["run"]["distance_mi"] == 7.0
    # And so do the medals it earned.
    db_session.expire_all()
    assert db_session.query(models.BadgeEarn).count() > 0


# --------------------------------------------------------------------------
# Alongside the deletion
# --------------------------------------------------------------------------


def test_deleting_and_restoring_a_hidden_workout_leaves_it_hidden(
    signed_in, db_session, member
):
    workout = log_workout(db_session, member.id, miles=5.0)
    hide(signed_in, workout.id)

    assert signed_in.delete(f"/api/workouts/{workout.id}").status_code == 204
    db_session.expire_all()
    assert db_session.get(models.Workout, workout.id).hidden_from_feed is True

    put_back = signed_in.post(f"/api/workouts/{workout.id}/restore")
    assert put_back.status_code == 200
    assert put_back.json()["hidden"] is True
    db_session.expire_all()
    assert db_session.get(models.Workout, workout.id).hidden_from_feed is True
    # Back in the history and still off the feed, which is where it was.
    assert history_ids(signed_in) == [workout.id]
    assert feed_ids(signed_in) == []
