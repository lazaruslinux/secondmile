"""Deleting a workout, putting it back, and what is purged in the end.

The policy this file pins, in one sentence: deleting takes back the miles and
never what the miles became. Every case here is one half of that, and the
chest and grove ones are the reason the delete path does not call
progress.recompute.
"""

import datetime as dt
import os

import pytest
from conftest import let_a_moment_pass, log_workout, make_user, neutral_start
from test_fellowship import befriend, sign_in
from test_ingest import export, post, workout as entry
from test_routemaps import line
from test_workouts import attach

from app import history, models, photos, progress, routemaps, security, videos
from app.config import CHEST_LADDER, DELETED_WORKOUT_RETENTION_DAYS


@pytest.fixture()
def mate(client, db_session):
    """A second signed-in account with a cookie jar of its own, borrowed from
    the fellowship cases rather than written a second time."""
    return sign_in(db_session, "mate")


def chest_count(db_session, user_id: int) -> int:
    return (
        db_session.query(models.Chest).filter(models.Chest.user_id == user_id).count()
    )


def progress_of(db_session, user_id: int) -> models.UserProgress:
    db_session.expire_all()
    return db_session.get(models.UserProgress, user_id)


def medal_ids(db_session, user_id: int) -> set[str]:
    db_session.expire_all()
    earned = {
        row.badge_id
        for row in db_session.query(models.BadgeEarn).filter(
            models.BadgeEarn.user_id == user_id
        )
    }
    return earned | {
        row.badge_id
        for row in db_session.query(models.WeeklyBadgeEarn).filter(
            models.WeeklyBadgeEarn.user_id == user_id
        )
    }


def deleted_days_ago(db_session, workout: models.Workout, days: int) -> None:
    """Age one deletion, because the suite's clock cannot move. Written
    straight onto the row: the endpoint always stamps the deletion now."""
    workout.deleted_at = security.now_utc() - dt.timedelta(days=days)
    db_session.commit()


# --------------------------------------------------------------------------
# It disappears
# --------------------------------------------------------------------------


def test_deleting_takes_the_workout_out_of_every_screen_it_was_on(
    signed_in, db_session, member
):
    kept = log_workout(db_session, member.id, miles=2.0)
    gone = log_workout(db_session, member.id, miles=5.0, offset_min=60)

    assert signed_in.delete(f"/api/workouts/{gone.id}").status_code == 204

    assert [row["workout_id"] for row in signed_in.get("/api/workouts").json()] == [kept.id]
    assert [row["workout_id"] for row in signed_in.get("/api/feed").json()] == [kept.id]
    profile = signed_in.get("/api/profile").json()
    assert profile["lifetime"]["run"]["distance_mi"] == 2.0
    assert profile["lifetime"]["run"]["workouts"] == 1
    assert profile["week"]["run"]["distance_mi"] == 2.0
    # The weekly totals behind the Almanac read the same column.
    weeks = signed_in.get("/api/workouts/weeks").json()
    assert weeks[0]["activities"]["run"]["distance_mi"] == 2.0
    # And the row itself is still there, holding the date of the deletion.
    db_session.expire_all()
    assert db_session.get(models.Workout, gone.id).deleted_at is not None


def test_a_deleted_workout_is_in_the_deleted_section_with_its_days(
    signed_in, db_session, member
):
    workout = log_workout(db_session, member.id, miles=4.0)
    signed_in.delete(f"/api/workouts/{workout.id}")

    rows = signed_in.get("/api/workouts/deleted").json()
    assert len(rows) == 1
    assert rows[0]["workout_id"] == workout.id
    assert rows[0]["activity"] == "run"
    assert rows[0]["distance_mi"] == 4.0
    # The whole window, because the day it was deleted in counts.
    assert rows[0]["days_left"] == DELETED_WORKOUT_RETENTION_DAYS
    # Nothing to draw: no photos, no route, no medals, no encouragement.
    assert set(rows[0]) == {
        "workout_id",
        "activity",
        "start_ts",
        "distance_mi",
        "duration_s",
        "title",
        "deleted_at",
        "days_left",
    }
    assert signed_in.get("/api/workouts/deleted").json()[0]["days_left"] == 30


def test_the_deleted_section_is_empty_for_somebody_who_has_deleted_nothing(
    signed_in, db_session, member
):
    log_workout(db_session, member.id)
    assert signed_in.get("/api/workouts/deleted").json() == []


def test_a_deleted_week_loses_its_diamond_and_can_break_the_streak(
    signed_in, db_session, member
):
    workout = log_workout(db_session, member.id, miles=3.0)
    assert any(signed_in.get("/api/profile").json()["week_days"])

    signed_in.delete(f"/api/workouts/{workout.id}")

    profile = signed_in.get("/api/profile").json()
    assert profile["week_days"] == [False] * 7
    assert profile["streak_weeks"] == 0


# --------------------------------------------------------------------------
# What the miles are worth, both ways
# --------------------------------------------------------------------------


def test_experience_and_the_level_come_off_and_come_back(signed_in, db_session, member):
    # Two runs past the first four levels between them, so the level moves.
    log_workout(db_session, member.id, miles=30.0)
    big = log_workout(db_session, member.id, miles=30.0, offset_min=600)
    before = signed_in.get("/api/profile").json()
    assert before["level"] >= 4

    signed_in.delete(f"/api/workouts/{big.id}")
    during = signed_in.get("/api/profile").json()
    assert during["xp"] == 30.0
    assert during["level"] < before["level"]

    assert signed_in.post(f"/api/workouts/{big.id}/restore").status_code == 200
    after = signed_in.get("/api/profile").json()
    assert after["xp"] == before["xp"]
    assert after["level"] == before["level"]


def test_a_medal_the_deleted_run_earned_goes_with_it_and_comes_back(
    signed_in, db_session, member
):
    """A race medal belongs to the run. The week's medal is a total, so it
    recomputes down to whatever the surviving days add up to."""
    # A walk, so the only race medal in this case is the one on the run below.
    log_workout(db_session, member.id, activity="walk", miles=8.0)
    race = log_workout(db_session, member.id, miles=13.5, offset_min=300)
    assert medal_ids(db_session, member.id) == {"race_half", "weekly_15"}

    signed_in.delete(f"/api/workouts/{race.id}")
    # The half went with the run; the week is back down to eight miles, which
    # earns nothing, so the weekly row is gone too.
    assert medal_ids(db_session, member.id) == set()

    signed_in.post(f"/api/workouts/{race.id}/restore")
    assert medal_ids(db_session, member.id) == {"race_half", "weekly_15"}


def test_the_weekly_medal_falls_back_to_the_rung_the_week_still_reaches(
    signed_in, db_session, member
):
    log_workout(db_session, member.id, activity="walk", miles=11.0)
    extra = log_workout(db_session, member.id, activity="walk", miles=9.0, offset_min=200)
    # One row per family per week, upgraded in place, so twenty miles wears the
    # fifteen rather than both.
    assert medal_ids(db_session, member.id) == {"weekly_15"}

    signed_in.delete(f"/api/workouts/{extra.id}")
    assert medal_ids(db_session, member.id) == {"weekly_10"}


# --------------------------------------------------------------------------
# Spent stays spent: chests and the grove
# --------------------------------------------------------------------------


def test_deleting_never_re_drops_a_chest_and_never_takes_one_away(
    signed_in, db_session, member
):
    """The policy in one case. The chests already dropped stay, opened or not,
    and the ladder underneath is what recomputes."""
    log_workout(db_session, member.id, miles=6.0)
    gone = log_workout(db_session, member.id, miles=6.0, offset_min=120)
    held = chest_count(db_session, member.id)
    assert held >= 2
    # One of them opened, with an item in the satchel to show for it, which is
    # exactly what a rebuild-from-scratch would hand out a second time.
    chest = (
        db_session.query(models.Chest)
        .filter(models.Chest.user_id == member.id)
        .order_by(models.Chest.id)
        .first()
    )
    progress.open_chest(db_session, member.id, chest)
    db_session.commit()
    items = db_session.query(models.SatchelItem).count()

    signed_in.delete(f"/api/workouts/{gone.id}")

    db_session.expire_all()
    assert chest_count(db_session, member.id) == held
    assert db_session.query(models.SatchelItem).count() == items
    assert db_session.get(models.Chest, chest.id).opened_at is not None
    # And nothing new: the surviving miles no longer cover the chests already
    # dropped, so the ladder is parked past the last of them with nothing on it.
    row = progress_of(db_session, member.id)
    assert row.chest_progress_mi == 0.0
    assert row.cycle_pos == held % len(CHEST_LADDER)
    assert signed_in.get("/api/chests").status_code == 200
    assert chest_count(db_session, member.id) == held


def test_the_ladder_pays_for_the_chests_already_held_before_dropping_another(
    signed_in, db_session, member
):
    """The other half of no-re-drop: miles added after a deletion have to get
    honestly past what has already been paid out before a chest falls."""
    log_workout(db_session, member.id, miles=6.0)
    gone = log_workout(db_session, member.id, miles=6.0, offset_min=120)
    held = chest_count(db_session, member.id)
    signed_in.delete(f"/api/workouts/{gone.id}")

    # A step's worth of new miles at the parked position. The first of them
    # goes on the step nobody has been paid for, so exactly one chest lands.
    _tier, _name, cost = CHEST_LADDER[held % len(CHEST_LADDER)]
    log_workout(db_session, member.id, miles=cost, offset_min=400)
    assert chest_count(db_session, member.id) == held + 1


def test_a_lifted_chest_keeps_its_gift_and_the_gift_is_not_spent_twice(
    signed_in, db_session, member, mate
):
    other, _client = mate
    befriend(db_session, member, other)
    anointing = models.Anointing(
        from_user_id=other.id,
        to_user_id=member.id,
        created_at=security.now_utc(),
        consumed_at=None,
    )
    db_session.add(anointing)
    db_session.commit()

    gone = log_workout(db_session, member.id, miles=6.0)
    db_session.expire_all()
    assert anointing.consumed_at is not None
    lifted = anointing.consumed_chest_id
    assert lifted is not None

    signed_in.delete(f"/api/workouts/{gone.id}")

    db_session.expire_all()
    assert anointing.consumed_at is not None
    assert anointing.consumed_chest_id == lifted
    assert db_session.get(models.Chest, lifted).from_anointing_id == anointing.id


def test_the_grove_keeps_its_growth_and_a_restore_does_not_credit_it_twice(
    signed_in, db_session, member
):
    """The deliberate asymmetry. Growth already in a plant stays when the miles
    that grew it are taken back, so putting them back must not grow it again."""
    planting = models.Planting(
        user_id=member.id,
        species="strawberry",
        rarity="common",
        planted_at=security.now_utc() - dt.timedelta(days=30),
        growth_mi=0.0,
        matured_at=None,
        level_at_ack=0,
    )
    db_session.add(planting)
    db_session.commit()

    workout = log_workout(db_session, member.id, miles=9.0)
    db_session.expire_all()
    grown = planting.growth_mi
    assert grown == pytest.approx(9.0)

    signed_in.delete(f"/api/workouts/{workout.id}")
    db_session.expire_all()
    assert planting.growth_mi == pytest.approx(grown)

    signed_in.post(f"/api/workouts/{workout.id}/restore")
    db_session.expire_all()
    assert planting.growth_mi == pytest.approx(grown)


def test_renown_is_untouched_by_a_deletion(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    workout = log_workout(db_session, member.id)
    other_client.post(f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"})
    before = progress_of(db_session, other.id).renown
    assert before > 0

    signed_in.delete(f"/api/workouts/{workout.id}")
    assert progress_of(db_session, other.id).renown == before


# --------------------------------------------------------------------------
# What a friend sees, which is nothing
# --------------------------------------------------------------------------


@pytest.fixture()
def shared(signed_in, db_session, member, mate, photo_dir):
    """A workout of the member's with a picture, a video and a route on it,
    and one friend who can see all three until it is deleted."""
    other, other_client = mate
    befriend(db_session, member, other)
    workout = log_workout(db_session, member.id, miles=3.0)
    photo_id = attach(signed_in, workout.id).json()["id"]
    # The video row is written straight in with a file beside it: what is being
    # tested is the gate in front of it, not the encoder.
    video = models.WorkoutVideo(workout_id=workout.id, created_at=security.now_utc())
    db_session.add(video)
    db_session.commit()
    os.makedirs(os.path.dirname(videos.path_for(workout.id, video.id)), exist_ok=True)
    with open(videos.path_for(workout.id, video.id), "wb") as out:
        out.write(b"mp4")
    with open(videos.poster_path_for(workout.id, video.id), "wb") as out:
        out.write(b"jpg")
    assert routemaps.store_route(db_session, workout.id, line(40))
    db_session.commit()
    return signed_in, workout, photo_id, video.id, other_client


def test_a_friend_loses_the_card_and_every_sub_resource_at_once(shared, db_session):
    mine, workout, photo_id, video_id, theirs = shared
    # Everything answers before the deletion, so the 404s below mean something.
    assert theirs.get("/api/feed").json()[0]["workout_id"] == workout.id
    assert theirs.get(f"/api/workouts/{workout.id}/route").status_code == 200
    assert theirs.get(f"/api/workouts/{workout.id}/photos/{photo_id}").status_code == 200
    assert theirs.get(f"/api/workouts/{workout.id}/videos/{video_id}").status_code == 200

    mine.delete(f"/api/workouts/{workout.id}")

    assert theirs.get("/api/feed").json() == []
    for path in (
        f"/api/workouts/{workout.id}/route",
        f"/api/workouts/{workout.id}/photos/{photo_id}",
        f"/api/workouts/{workout.id}/videos/{video_id}",
        f"/api/workouts/{workout.id}/videos/{video_id}/poster",
        f"/api/workouts/{workout.id}/notes",
    ):
        assert theirs.get(path).status_code == 404, path
    # And nothing about it is on their view of the profile either.
    seen = theirs.get(f"/api/profile/{workout.user_id}").json()
    assert seen["workouts"] == []
    assert seen["recent_photos"] == []
    assert seen["lifetime"] == {}


def test_the_owner_gets_the_same_404_on_the_media_of_their_own_deleted_workout(shared):
    """The Deleted section draws no pictures, so there is one rule rather than
    a viewer test in front of every file."""
    mine, workout, photo_id, video_id, _theirs = shared
    mine.delete(f"/api/workouts/{workout.id}")

    for path in (
        f"/api/workouts/{workout.id}/route",
        f"/api/workouts/{workout.id}/photos/{photo_id}",
        f"/api/workouts/{workout.id}/videos/{video_id}",
        f"/api/workouts/{workout.id}/videos/{video_id}/poster",
        f"/api/workouts/{workout.id}/notes",
    ):
        assert mine.get(path).status_code == 404, path
    # And it cannot be titled or added to while it is gone.
    assert mine.patch(f"/api/workouts/{workout.id}", json={"title": "no"}).status_code == 404


def test_the_media_all_answer_again_once_it_is_restored(shared):
    mine, workout, photo_id, video_id, theirs = shared
    mine.delete(f"/api/workouts/{workout.id}")
    assert mine.post(f"/api/workouts/{workout.id}/restore").status_code == 200

    assert theirs.get(f"/api/workouts/{workout.id}/route").status_code == 200
    assert theirs.get(f"/api/workouts/{workout.id}/photos/{photo_id}").status_code == 200
    assert theirs.get(f"/api/workouts/{workout.id}/videos/{video_id}").status_code == 200
    assert theirs.get("/api/feed").json()[0]["workout_id"] == workout.id


def test_nobody_can_encourage_a_deleted_workout(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    workout = log_workout(db_session, member.id)
    signed_in.delete(f"/api/workouts/{workout.id}")

    response = other_client.post(
        f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"}
    )
    assert response.status_code == 404


def test_hype_and_comments_are_hidden_with_it_and_whole_when_it_returns(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    befriend(db_session, member, other)
    workout = log_workout(db_session, member.id)
    other_client.post(f"/api/workouts/{workout.id}/encourage", json={"kind": "cheer"})
    other_client.post(
        f"/api/workouts/{workout.id}/encourage", json={"kind": "note", "body": "strong"}
    )

    signed_in.delete(f"/api/workouts/{workout.id}")
    assert signed_in.get(f"/api/workouts/{workout.id}/notes").status_code == 404
    # Hidden, not thrown away: the rows are still there to come back.
    assert db_session.query(models.Encouragement).count() == 2

    restored = signed_in.post(f"/api/workouts/{workout.id}/restore").json()
    assert restored["encouragement"] == {"cheers": 1, "notes": 1, "cheered_by_me": False}
    assert [row["body"] for row in signed_in.get(f"/api/workouts/{workout.id}/notes").json()] == [
        "strong"
    ]


def test_deleting_is_owner_only_and_says_nothing_about_whose_workout_it_was(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    mine = log_workout(db_session, member.id)
    befriend(db_session, member, other)

    # A friend, and the same account with no friendship at all, and an id
    # nobody owns: one sentence for all of them, on both endpoints.
    stranger = make_user(db_session, "stranger", "stranger-password-1")
    assert stranger.id
    for path in (f"/api/workouts/{mine.id}", "/api/workouts/999999"):
        answer = other_client.delete(path)
        assert answer.status_code == 404
        assert answer.json()["detail"] == "No such workout."
    assert other_client.post(f"/api/workouts/{mine.id}/restore").status_code == 404
    assert other_client.post("/api/workouts/999999/restore").status_code == 404
    # And it really is still there.
    db_session.expire_all()
    assert db_session.get(models.Workout, mine.id).deleted_at is None


def test_deleting_twice_is_the_same_answer_and_keeps_the_first_date(
    signed_in, db_session, member
):
    workout = log_workout(db_session, member.id)
    signed_in.delete(f"/api/workouts/{workout.id}")
    db_session.expire_all()
    first = db_session.get(models.Workout, workout.id).deleted_at

    assert signed_in.delete(f"/api/workouts/{workout.id}").status_code == 204
    db_session.expire_all()
    assert db_session.get(models.Workout, workout.id).deleted_at == first


def test_delete_and_restore_are_rate_limited(signed_in, db_session, member):
    rows = [log_workout(db_session, member.id, offset_min=n * 20) for n in range(11)]
    codes = [signed_in.delete(f"/api/workouts/{row.id}").status_code for row in rows]
    assert codes[:10] == [204] * 10
    assert codes[10] == 429
    # One budget for the pair, so the restore is refused as well.
    assert signed_in.post(f"/api/workouts/{rows[0].id}/restore").status_code == 429


# --------------------------------------------------------------------------
# Several at once
# --------------------------------------------------------------------------


def test_a_batch_deletes_all_of_them_and_leaves_the_rest(signed_in, db_session, member):
    """Select mode's whole job: several workouts out in one act, answered with
    the Deleted rows so the tab can count them without asking again."""
    kept = log_workout(db_session, member.id, miles=2.0)
    first = log_workout(db_session, member.id, miles=5.0, offset_min=60)
    second = log_workout(db_session, member.id, miles=4.0, offset_min=120)

    answer = signed_in.post("/api/workouts/delete", json={"ids": [first.id, second.id]})
    assert answer.status_code == 200
    # Newest first, the order the Deleted list draws them in, with the days
    # left on each one.
    rows = answer.json()
    assert [row["workout_id"] for row in rows] == [second.id, first.id]
    assert [row["days_left"] for row in rows] == [DELETED_WORKOUT_RETENTION_DAYS] * 2

    assert [row["workout_id"] for row in signed_in.get("/api/workouts").json()] == [kept.id]
    deleted = signed_in.get("/api/workouts/deleted").json()
    assert [row["workout_id"] for row in deleted] == [second.id, first.id]


def test_a_batch_rebuilds_the_totals_once_and_correctly(
    signed_in, db_session, member, monkeypatch
):
    """One rebuild for the batch, and the arithmetic afterwards is the same as
    deleting them one at a time would have left."""
    log_workout(db_session, member.id, activity="walk", miles=8.0)
    race = log_workout(db_session, member.id, miles=13.5, offset_min=300)
    extra = log_workout(db_session, member.id, miles=20.0, offset_min=600)
    assert "race_half" in medal_ids(db_session, member.id)
    before = signed_in.get("/api/profile").json()

    calls = []
    real = progress.rebuild_from_surviving
    monkeypatch.setattr(
        progress,
        "rebuild_from_surviving",
        lambda db, user_id: (calls.append(user_id), real(db, user_id))[1],
    )
    assert (
        signed_in.post("/api/workouts/delete", json={"ids": [race.id, extra.id]}).status_code
        == 200
    )
    assert calls == [member.id]
    after = signed_in.get("/api/profile").json()
    assert after["xp"] == 8.0
    assert after["level"] < before["level"]
    # The race medal went with its run and the week fell back to what the walk
    # still reaches, exactly as the single delete leaves it.
    assert medal_ids(db_session, member.id) == set()

    # And every one of them is still restorable on its own.
    assert signed_in.post(f"/api/workouts/{race.id}/restore").status_code == 200
    assert signed_in.post(f"/api/workouts/{extra.id}/restore").status_code == 200
    assert signed_in.get("/api/profile").json()["xp"] == before["xp"]
    assert "race_half" in medal_ids(db_session, member.id)
    assert signed_in.get("/api/workouts/deleted").json() == []


def test_a_batch_holding_one_bad_id_deletes_nothing_and_says_nothing(
    signed_in, db_session, member, mate
):
    """No partial success and no oracle. A stranger's id, an id nobody owns,
    and one already deleted all answer the same 404 for the whole call, and the
    good ids in the same batch are untouched."""
    other, _other_client = mate
    mine = log_workout(db_session, member.id, miles=3.0)
    also_mine = log_workout(db_session, member.id, miles=4.0, offset_min=60)
    theirs = log_workout(db_session, other.id, miles=5.0)
    already = log_workout(db_session, member.id, miles=6.0, offset_min=120)
    assert signed_in.delete(f"/api/workouts/{already.id}").status_code == 204

    for batch in ([mine.id, theirs.id], [mine.id, 999999], [mine.id, already.id]):
        answer = signed_in.post("/api/workouts/delete", json={"ids": batch})
        assert answer.status_code == 404
        assert answer.json()["detail"] == "No such workout."

    db_session.expire_all()
    assert db_session.get(models.Workout, mine.id).deleted_at is None
    assert db_session.get(models.Workout, also_mine.id).deleted_at is None
    assert db_session.get(models.Workout, theirs.id).deleted_at is None


def test_a_batch_refuses_an_empty_list_and_an_enormous_one(signed_in):
    assert signed_in.post("/api/workouts/delete", json={"ids": []}).status_code == 400
    huge = signed_in.post("/api/workouts/delete", json={"ids": list(range(1, 500))})
    assert huge.status_code == 400


def test_a_batch_counts_as_one_delete_against_the_limiter(signed_in, db_session, member):
    """The cap is ten of these a minute. It counts calls, not workouts, so a
    tidy-up of thirty rows in three batches is three of the ten."""
    rows = [log_workout(db_session, member.id, offset_min=n * 20) for n in range(22)]
    ids = [row.id for row in rows]
    for start in range(0, 20, 2):
        answer = signed_in.post("/api/workouts/delete", json={"ids": ids[start : start + 2]})
        assert answer.status_code == 200
    # Ten calls spent, twenty workouts gone, and the eleventh call refused.
    assert len(signed_in.get("/api/workouts/deleted").json()) == 20
    assert signed_in.post("/api/workouts/delete", json={"ids": ids[20:]}).status_code == 429


# --------------------------------------------------------------------------
# The letter
# --------------------------------------------------------------------------


def test_the_letter_drops_a_deleted_workout_and_does_not_re_report_a_restored_one(
    signed_in, db_session, member
):
    kept = log_workout(db_session, member.id, miles=2.0)
    gone = log_workout(db_session, member.id, miles=4.0, offset_min=120)
    letter = signed_in.get("/api/recap").json()
    assert letter["workouts_total"] == 2
    assert signed_in.post("/api/recap/ack").status_code == 204

    # Both are old news now. Deleting one changes nothing about that, and
    # putting it back does not make it news again.
    signed_in.delete(f"/api/workouts/{gone.id}")
    assert signed_in.get("/api/recap").json()["workouts_total"] == 0
    signed_in.post(f"/api/workouts/{gone.id}/restore")
    after = signed_in.get("/api/recap").json()
    assert after["workouts_total"] == 0
    assert after["medals"] == []

    # A letter written while it is deleted counts only what is left.
    signed_in.delete(f"/api/workouts/{kept.id}")
    let_a_moment_pass(db_session)
    fresh = log_workout(db_session, member.id, miles=1.0, offset_min=300)
    assert fresh.id
    assert signed_in.get("/api/recap").json()["miles"]["run"] == 1.0


# --------------------------------------------------------------------------
# The window, the purge, and the tombstone
# --------------------------------------------------------------------------


def test_a_workout_past_the_window_leaves_the_deleted_section_and_cannot_return(
    signed_in, db_session, member
):
    workout = log_workout(db_session, member.id)
    signed_in.delete(f"/api/workouts/{workout.id}")
    deleted_days_ago(db_session, workout, DELETED_WORKOUT_RETENTION_DAYS + 1)

    assert signed_in.get("/api/workouts/deleted").json() == []
    assert signed_in.post(f"/api/workouts/{workout.id}/restore").status_code == 404
    # Still hidden, and still there.
    assert signed_in.get("/api/workouts").json() == []
    db_session.expire_all()
    assert db_session.get(models.Workout, workout.id) is not None


def test_the_last_day_still_counts_and_the_day_after_does_not(
    signed_in, db_session, member
):
    workout = log_workout(db_session, member.id)
    signed_in.delete(f"/api/workouts/{workout.id}")
    deleted_days_ago(db_session, workout, DELETED_WORKOUT_RETENTION_DAYS - 1)

    rows = signed_in.get("/api/workouts/deleted").json()
    assert rows[0]["days_left"] == 1
    assert signed_in.post(f"/api/workouts/{workout.id}/restore").status_code == 200


def test_the_purge_takes_the_files_and_the_words_and_keeps_the_row(
    signed_in, db_session, member, mate, photo_dir
):
    other, other_client = mate
    befriend(db_session, member, other)
    workout = log_workout(db_session, member.id, miles=3.0)
    signed_in.patch(f"/api/workouts/{workout.id}", json={"title": "morning", "post": "good one"})
    photo_id = attach(signed_in, workout.id).json()["id"]
    other_client.post(
        f"/api/workouts/{workout.id}/encourage", json={"kind": "note", "body": "nice"}
    )
    video = models.WorkoutVideo(workout_id=workout.id, created_at=security.now_utc())
    db_session.add(video)
    db_session.commit()
    os.makedirs(os.path.dirname(videos.path_for(workout.id, video.id)), exist_ok=True)
    for path in (
        videos.path_for(workout.id, video.id),
        videos.poster_path_for(workout.id, video.id),
    ):
        with open(path, "wb") as out:
            out.write(b"x")
    assert routemaps.store_route(db_session, workout.id, line(40))
    db_session.commit()
    picture = photos.path_for(workout.id, photo_id)
    assert os.path.isfile(picture)

    signed_in.delete(f"/api/workouts/{workout.id}")
    deleted_days_ago(db_session, workout, DELETED_WORKOUT_RETENTION_DAYS + 1)
    assert history.purge_expired(db_session, member.id) == 1
    db_session.commit()

    assert not os.path.isfile(picture)
    assert not os.path.isfile(videos.path_for(workout.id, video.id))
    assert not os.path.isfile(videos.poster_path_for(workout.id, video.id))
    assert db_session.query(models.WorkoutPhoto).count() == 0
    assert db_session.query(models.WorkoutVideo).count() == 0
    assert db_session.query(models.WorkoutRoute).count() == 0
    assert db_session.query(models.Encouragement).count() == 0
    # The tombstone: the row, its dedupe key, and nothing worth keeping.
    db_session.expire_all()
    row = db_session.get(models.Workout, workout.id)
    assert row is not None
    assert row.title is None and row.post is None
    assert row.deleted_at is not None
    # Renown already paid for the note stays paid.
    assert progress_of(db_session, other.id).renown > 0


def test_the_purge_leaves_a_workout_still_inside_its_window_alone(
    signed_in, db_session, member, photo_dir
):
    workout = log_workout(db_session, member.id)
    photo_id = attach(signed_in, workout.id).json()["id"]
    signed_in.delete(f"/api/workouts/{workout.id}")
    deleted_days_ago(db_session, workout, DELETED_WORKOUT_RETENTION_DAYS - 1)

    assert history.purge_expired(db_session, member.id) == 0
    assert os.path.isfile(photos.path_for(workout.id, photo_id))
    # And restoring it inside the window really does bring the picture back.
    assert signed_in.post(f"/api/workouts/{workout.id}/restore").json()["photos"] == [photo_id]


def test_the_purge_runs_on_the_next_sync_and_only_once(
    signed_in, db_session, member, ingest_token, photo_dir
):
    workout = log_workout(db_session, member.id)
    attach(signed_in, workout.id)
    signed_in.delete(f"/api/workouts/{workout.id}")
    deleted_days_ago(db_session, workout, DELETED_WORKOUT_RETENTION_DAYS + 1)

    payload = export(entry("Outdoor Walk", "2026-04-14T06:12:00+00:00", 2400.0, 2.1, 190))
    assert post(signed_in, ingest_token, payload).status_code == 200
    db_session.expire_all()
    assert db_session.query(models.WorkoutPhoto).count() == 0

    # A second sync has nothing left to take off that row, so it does not walk
    # the tombstone again.
    assert history.purge_expired(db_session, member.id) == 0


def test_the_tombstone_blocks_the_same_session_being_imported_again(
    signed_in, db_session, member, ingest_token
):
    """The reason the row is kept forever. The phone exports overlapping
    windows, so a deleted workout would otherwise walk back in on the next
    catch-up sync and be credited all over again."""
    payload = export(entry("Outdoor Run", "2026-04-14T06:12:00+00:00", 1800.0, 3.0, 300))
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1
    workout = db_session.query(models.Workout).one()

    signed_in.delete(f"/api/workouts/{workout.id}")
    deleted_days_ago(db_session, workout, DELETED_WORKOUT_RETENTION_DAYS + 1)

    # The same export again, after the purge has emptied the row.
    again = post(signed_in, ingest_token, payload)
    assert again.json() == {"imported": 0, "skipped": 1, "flagged": 0, "ignored": 0}
    db_session.expire_all()
    assert db_session.query(models.Workout).count() == 1
    assert db_session.get(models.Workout, workout.id).deleted_at is not None
    assert signed_in.get("/api/workouts").json() == []
    assert signed_in.get("/api/profile").json()["xp"] == 0.0


def test_a_deleted_day_no_longer_flags_the_next_workout_over_the_cap(
    signed_in, db_session, member
):
    """The daily cap is a doubt about the day's numbers. A day whose bogus ride
    has been taken back is not a doubtful day any more."""
    start = neutral_start()
    bogus = log_workout(db_session, member.id, activity="cycle", miles=190.0)
    signed_in.delete(f"/api/workouts/{bogus.id}")

    from app.activity import over_daily_cap

    assert not over_daily_cap(db_session, member.id, "cycle", start)
