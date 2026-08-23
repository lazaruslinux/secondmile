"""PR stamps: where a workout stood the day it arrived, written once.

The reading itself - the fastest stretch or the session's own pace - is covered
where it has always been covered, by the insights cases in test_workouts and the
storage cases in test_bests. What is held to here is the standing: that a
workout is judged against what came before it and nothing after, that a card
already stamped is never rewritten, that a walk and a run are separate records,
and that a friend sees a standing only where its owner allows it.
"""


from app import fellowship, models, security, stamps
from app.main import app as fastapi_app
from conftest import make_user
from fastapi.testclient import TestClient
from test_ingest import export, post, workout
from test_workouts import stored


def run(db_session, user_id, day, *, duration, miles, activity="run", deleted=False):
    """One workout on a given April day, written in and then judged."""
    row = stored(
        db_session,
        user_id,
        activity=activity,
        start=f"2026-04-{day:02d}T06:00:00+00:00",
        duration=duration,
        miles=miles,
    )
    if deleted:
        row.deleted_at = security.now_utc()
        db_session.flush()
    stamps.stamp(db_session, user_id, [row])
    db_session.commit()
    return row


def placed(db_session, row) -> dict[str, int]:
    return {
        stamp.tier: stamp.rank
        for stamp in db_session.query(models.WorkoutPrStamp).filter_by(workout_id=row.id)
    }


def test_the_first_qualifying_workout_is_a_best(db_session, member):
    first = run(db_session, member.id, 10, duration=1800, miles=3.5)
    assert placed(db_session, first) == {"5k": 1}


def test_a_slower_run_places_behind_and_a_faster_one_in_front(db_session, member):
    first = run(db_session, member.id, 10, duration=1800, miles=3.5)
    slower = run(db_session, member.id, 11, duration=2400, miles=3.5)
    faster = run(db_session, member.id, 12, duration=1500, miles=3.5)

    assert placed(db_session, slower) == {"5k": 2}
    assert placed(db_session, faster) == {"5k": 1}
    # The whole design in one line: the first card still says what it said.
    assert placed(db_session, first) == {"5k": 1}


def test_a_shorter_distance_is_not_ranked_at_all(db_session, member):
    """Under the shortest tier there is no record to stand in."""
    short = run(db_session, member.id, 10, duration=900, miles=2.0)
    assert placed(db_session, short) == {}


def test_fourth_place_says_nothing(db_session, member):
    for day, duration in ((10, 1500), (11, 1600), (12, 1700), (13, 1800)):
        last = run(db_session, member.id, day, duration=duration, miles=3.5)
    assert placed(db_session, last) == {}


def test_a_tie_leaves_the_earlier_workout_in_front(db_session, member):
    """The one that got there first holds the mark, which is how records read."""
    run(db_session, member.id, 10, duration=1800, miles=3.5)
    same = run(db_session, member.id, 11, duration=1800, miles=3.5)
    assert placed(db_session, same) == {"5k": 2}


def test_the_same_pace_over_different_distances_still_ranks_in_order(db_session, member):
    """The bug this case exists for: two divisions, one pace, and float noise.

    Three rides at exactly the same pace project 868.0 and 868.0000000000001 for
    the same 5K depending on which distance the division started from. Compared
    raw, the noise rather than the pace decided the place, and two rides came out
    third. Compared at the tenth every reading is shown at, they queue.
    """
    for day, duration, miles in ((10, 1764, 6.3), (11, 2016, 7.2), (12, 2268, 8.1)):
        run(db_session, member.id, day, duration=duration, miles=miles, activity="cycle")
    fourth = run(db_session, member.id, 13, duration=2520, miles=9.0, activity="cycle")

    ranks = [
        placed(db_session, row).get("5k")
        for row in db_session.query(models.Workout).order_by(models.Workout.start_ts)
    ]
    assert ranks == [1, 2, 3, None]
    # Fourth at the 10K inside them too, on the same pace, so it says nothing.
    assert placed(db_session, fourth) == {}


def test_a_walk_and_a_run_are_separate_records(db_session, member):
    run(db_session, member.id, 10, duration=1500, miles=3.5)
    walk = run(db_session, member.id, 11, duration=3600, miles=3.5, activity="walk")
    # Far slower than the run, and still this account's best walk.
    assert placed(db_session, walk) == {"5k": 1}


def test_one_workout_can_stand_in_several_tiers_longest_first(db_session, member):
    """A long run holds a standing at every distance inside it."""
    long_run = run(db_session, member.id, 10, duration=9000, miles=15.0)
    assert placed(db_session, long_run) == {"5k": 1, "10k": 1, "half": 1}

    order = stamps.for_workouts(db_session, [long_run.id])[long_run.id]
    assert [row["tier"] for row in order] == ["half", "10k", "5k"]


def test_the_better_place_is_said_before_the_longer_distance(db_session, member):
    """Rank first, distance only as the tie-break between two of the same rank."""
    run(db_session, member.id, 10, duration=3000, miles=7.0)
    mixed = run(db_session, member.id, 11, duration=3300, miles=7.0)
    # Second at the 10K it barely covers, and still nothing faster at the 5K
    # inside it, because the first run's 5K pace was quicker.
    assert placed(db_session, mixed) == {"5k": 2, "10k": 2}
    order = stamps.for_workouts(db_session, [mixed.id])[mixed.id]
    assert [row["tier"] for row in order] == ["10k", "5k"]


def test_a_taken_back_run_is_not_something_to_be_measured_against(db_session, member):
    run(db_session, member.id, 10, duration=1200, miles=3.5, deleted=True)
    later = run(db_session, member.id, 11, duration=1800, miles=3.5)
    assert placed(db_session, later) == {"5k": 1}


def test_a_sync_stamps_what_it_imports_in_time_order(signed_in, ingest_token, db_session):
    """One export, two workouts, the later one posted first.

    The reason the stamping happens after the whole loop rather than inside it:
    an export carries a week in whatever order the phone assembled it, and the
    faster run here arrived second in the payload and first in the day.
    """
    assert (
        post(
            signed_in,
            ingest_token,
            export(
                workout("Outdoor Run", "2026-07-21T06:00:00+00:00", 2400, 3.5, 300, 150),
                workout("Outdoor Run", "2026-07-20T06:00:00+00:00", 1800, 3.5, 300, 150),
            ),
        ).json()["imported"]
        == 2
    )
    rows = {
        row.start_ts.day: row
        for row in db_session.query(models.Workout).order_by(models.Workout.start_ts)
    }
    assert placed(db_session, rows[20]) == {"5k": 1}
    assert placed(db_session, rows[21]) == {"5k": 2}


def test_a_measured_stretch_is_what_is_ranked_where_there_is_one(
    signed_in, ingest_token, db_session
):
    """A fast 5K inside a long steady run beats a shorter run's whole-session pace."""
    steady = workout("Outdoor Run", "2026-07-20T06:00:00+00:00", 1800, 3.5, 300, 150)
    assert post(signed_in, ingest_token, export(steady)).json()["imported"] == 1

    # Ten minutes at a third of a mile inside an otherwise slow hour: the 5K
    # stretch in it is far quicker than anything the session averaged.
    surge = workout("Outdoor Run", "2026-07-21T06:00:00+00:00", 3600, 6.0, 500, 150)
    surge["walkingAndRunningDistance"] = [
        {"date": f"2026-07-21T06:{m:02d}:00+00:00", "qty": 0.35 if m < 10 else 0.04, "units": "mi"}
        for m in range(60)
    ]
    assert post(signed_in, ingest_token, export(surge)).json()["imported"] == 1

    rows = {
        row.start_ts.day: row
        for row in db_session.query(models.Workout).order_by(models.Workout.start_ts)
    }
    assert placed(db_session, rows[21])["5k"] == 1
    assert placed(db_session, rows[20]) == {"5k": 1}


def test_the_backfill_replays_a_history_into_the_standings_it_held(db_session, member):
    """Old cards get the place they held then, not the one they would hold now."""
    first = stored(db_session, member.id, start="2026-04-10T06:00:00+00:00", duration=1800, miles=3.5)
    second = stored(db_session, member.id, start="2026-04-11T06:00:00+00:00", duration=1500, miles=3.5)
    db_session.commit()
    assert db_session.query(models.WorkoutPrStamp).count() == 0

    assert stamps.rebuild(db_session, member.id) == 2
    db_session.commit()
    assert placed(db_session, first) == {"5k": 1}
    assert placed(db_session, second) == {"5k": 1}

    # Twice over an unchanged history is the same answer.
    stamps.rebuild(db_session, member.id)
    db_session.commit()
    assert placed(db_session, first) == {"5k": 1}
    assert db_session.query(models.WorkoutPrStamp).count() == 2


def test_the_backfill_leaves_another_account_alone(db_session, member, admin):
    mine = run(db_session, member.id, 10, duration=1800, miles=3.5)
    theirs = stored(db_session, admin.id, start="2026-04-10T06:00:00+00:00", duration=1800, miles=3.5)
    db_session.commit()

    stamps.rebuild(db_session, admin.id)
    db_session.commit()
    assert placed(db_session, theirs) == {"5k": 1}
    assert placed(db_session, mine) == {"5k": 1}


def test_it_is_a_fourth_switch_and_it_is_off_to_begin_with(signed_in):
    assert "personal_records" in fellowship.HIDEABLE
    assert signed_in.get("/api/auth/me").json()["hidden_from_friends"] == []
    saved = signed_in.patch("/api/settings", json={"hidden_from_friends": ["personal_records"]})
    assert saved.status_code == 200
    assert saved.json()["hidden_from_friends"] == ["personal_records"]


def test_a_friend_sees_a_standing_until_its_owner_says_otherwise(
    db_session, member, signed_in
):
    """Hidden from a friend, and never hidden from the person whose history it is."""
    run(db_session, member.id, 10, duration=1800, miles=3.5)
    mate = make_user(db_session, "mate", "mate-password-1")
    db_session.add(
        models.Friendship(
            requester_id=member.id,
            addressee_id=mate.id,
            status="accepted",
            created_at=security.now_utc(),
        )
    )
    db_session.commit()

    # Its own client: the signed_in fixture and the shared one are the same
    # object, so logging the friend in on it would replace the session the
    # setting below is saved through.
    theirs = TestClient(fastapi_app)
    assert (
        theirs.post(
            "/api/auth/login", json={"username": "mate", "password": "mate-password-1"}
        ).status_code
        == 204
    )
    assert theirs.get("/api/feed").json()[0]["records"] == [{"tier": "5k", "rank": 1}]

    assert (
        signed_in.patch(
            "/api/settings", json={"hidden_from_friends": ["personal_records"]}
        ).status_code
        == 200
    )
    assert "records" not in theirs.get("/api/feed").json()[0]
    # Their own history is untouched: hiding a thing from yourself is not a
    # privacy setting.
    assert signed_in.get("/api/workouts").json()[0]["records"] == [{"tier": "5k", "rank": 1}]


def test_a_card_with_nothing_to_say_carries_no_field_at_all(db_session, member, signed_in):
    """Absent rather than empty: an empty list is still a sentence about somebody."""
    stored(db_session, member.id, start="2026-04-10T06:00:00+00:00", duration=900, miles=2.0)
    db_session.commit()
    assert "records" not in signed_in.get("/api/workouts").json()[0]
