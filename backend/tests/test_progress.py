"""The pipeline: conversion, experience, the level curve, chests, and replay."""

import datetime as dt

import pytest
from conftest import log_workout

from app import achievements, models, progress, security
from app.activity import converted_miles
from app.config import BORDER_LEVELS, MAX_LEVEL


def profile(client) -> dict:
    response = client.get("/api/profile")
    assert response.status_code == 200, response.text
    return response.json()


def chests(db_session, user_id) -> list[models.Chest]:
    return (
        db_session.query(models.Chest)
        .filter(models.Chest.user_id == user_id)
        .order_by(models.Chest.id)
        .all()
    )


def test_conversion_rates_are_effort_equivalent():
    assert converted_miles("walk", 3.0) == 3.0
    assert converted_miles("run", 3.0) == 3.0
    assert converted_miles("cycle", 9.0) == 3.0
    assert converted_miles("swim", 0.75) == 3.0


def test_experience_is_converted_miles_and_nothing_else(signed_in):
    """XP is the distance itself, so the same Miles are worth the same whether
    they took half an hour or two, and time on its own is worth nothing."""
    log_workout(signed_in, "run", 3.0, pace_min=12, offset_min=0)
    assert profile(signed_in)["xp"] == 3.0
    # Nine cycled miles are three Miles, so the same credit again.
    log_workout(signed_in, "cycle", 9.0, pace_min=5, offset_min=200)
    assert profile(signed_in)["xp"] == 6.0
    # Ten minutes in the pool with no distance recorded earns nothing.
    log_workout(signed_in, "swim", 0.0, offset_min=400)
    assert profile(signed_in)["xp"] == 6.0


def test_the_level_curve_is_the_race_ladder_then_a_marathon_more_each_time():
    assert progress.level_cost(1) == 3.1
    assert progress.level_cost(2) == 6.2
    assert progress.level_cost(3) == 13.1
    assert progress.level_cost(4) == 26.2
    # From five on, each level costs one more marathon than the last.
    assert progress.level_cost(5) == pytest.approx(52.4)
    assert progress.level_cost(6) == pytest.approx(78.6)
    assert progress.level_cost(10) == pytest.approx(26.2 * 7)

    assert progress.xp_to_reach(0) == 0
    assert progress.xp_to_reach(1) == pytest.approx(3.1)
    assert progress.xp_to_reach(2) == pytest.approx(9.3)
    assert progress.xp_to_reach(4) == pytest.approx(48.6)
    assert progress.xp_to_reach(5) == pytest.approx(101.0)


def test_a_fresh_account_is_level_zero_and_a_5k_is_level_one():
    assert progress.level_for_xp(0.0) == 0
    assert progress.level_for_xp(3.0) == 0
    # Exactly the threshold counts, floats and all.
    assert progress.level_for_xp(3.1) == 1
    assert progress.level_for_xp(9.29) == 1
    assert progress.level_for_xp(9.3) == 2
    assert progress.level_for_xp(48.6) == 4
    assert progress.level_for_xp(100.9) == 4
    assert progress.level_for_xp(101.0) == 5

    # The window the level bar draws: 9.3 XP is level 2, with nothing into it,
    # and level 3 is worth a half marathon.
    level, into, span = progress.level_bounds(9.3)
    assert level == 2
    assert into == pytest.approx(0.0)
    assert span == pytest.approx(13.1)
    level, into, span = progress.level_bounds(15.0)
    assert (level, round(into, 1), span) == (2, 5.7, 13.1)


def test_the_level_walk_is_bounded_and_never_raises():
    # A total nobody earns must still answer, and must answer quickly.
    assert progress.level_for_xp(10**9) == MAX_LEVEL
    assert progress.level_bounds(10**9)[0] == MAX_LEVEL
    # Only a corrupted row is ever below zero, and it must not raise.
    assert progress.level_for_xp(-5.0) == 0


def test_border_tiers_arrive_at_the_documented_levels():
    assert BORDER_LEVELS == (0, 6, 10, 15, 25, 35)
    assert progress.border_tier(0) == 1
    assert progress.border_tier(5) == 1
    assert progress.border_tier(6) == 2
    assert progress.border_tier(14) == 3
    assert progress.border_tier(15) == 4
    assert progress.border_tier(35) == len(BORDER_LEVELS)
    assert progress.border_tier(500) == len(BORDER_LEVELS)


def test_a_workout_credits_experience_once(signed_in, db_session, member):
    log_workout(signed_in, "run", 4.0, pace_min=15)
    body = profile(signed_in)
    assert body["xp"] == 4.0
    # Past a 5K but not a 10K, which is level one.
    assert body["level"] == 1
    # A second read sweeps again and must not credit the same workout twice.
    assert profile(signed_in)["xp"] == 4.0


def test_a_workout_only_ever_counts_once_however_it_arrives(
    signed_in, db_session, member, ingest_token
):
    payload = {
        "data": {
            "workouts": [
                {
                    "name": "Outdoor Run",
                    "start": (security.now_utc() - dt.timedelta(hours=3)).isoformat(),
                    "duration": 2700,
                    "distance": {"qty": 5.0, "units": "mi"},
                }
            ]
        }
    }
    headers = {"Authorization": f"Bearer {ingest_token}"}
    assert signed_in.post("/api/ingest", json=payload, headers=headers).json()["imported"] == 1
    first = profile(signed_in)
    assert first["xp"] > 0
    dropped = len(chests(db_session, member.id))

    # The same export window again, which is what Health Auto Export really
    # sends. The workout is skipped and nothing moves.
    assert signed_in.post("/api/ingest", json=payload, headers=headers).json()["skipped"] == 1
    again = profile(signed_in)
    assert again["xp"] == first["xp"]
    assert len(chests(db_session, member.id)) == dropped


def test_the_sweep_credits_a_workout_written_straight_into_the_database(
    signed_in, db_session, member
):
    db_session.add(
        models.Workout(
            user_id=member.id,
            activity="walk",
            start_ts=security.now_utc() - dt.timedelta(hours=2),
            duration_s=3600,
            distance_mi=2.5,
            active_kcal=180.0,
            avg_hr=None,
            source="sync",
            flags={},
            created_at=security.now_utc(),
        )
    )
    db_session.commit()
    assert profile(signed_in)["xp"] == 2.5


def test_workouts_from_before_the_account_still_count(signed_in, db_session, member):
    """No start gate any more: a profile counts a lifetime, not a window."""
    old = security.now_utc() - dt.timedelta(days=400)
    db_session.add(
        models.Workout(
            user_id=member.id,
            activity="run",
            start_ts=old,
            duration_s=3600,
            distance_mi=8.0,
            active_kcal=800.0,
            avg_hr=None,
            source="sync",
            flags={},
            created_at=security.now_utc(),
        )
    )
    db_session.commit()
    body = profile(signed_in)
    assert body["xp"] == 8.0
    assert body["lifetime"]["run"]["distance_mi"] == 8.0


def test_reprocessing_the_same_history_gives_the_same_chests(signed_in, db_session, member):
    log_workout(signed_in, "walk", 6.0, offset_min=0)
    log_workout(signed_in, "run", 7.0, offset_min=200)
    first = [row.tier for row in chests(db_session, member.id)]
    assert first, "the test needs at least one chest to be worth anything"
    xp = db_session.get(models.UserProgress, member.id).xp

    # What recompute-progress does. The ladder is fixed, so the same history
    # climbs it the same way every time.
    rebuilt = progress.recompute(db_session, member.id)
    assert [row.tier for row in chests(db_session, member.id)] == first
    assert rebuilt.xp == xp


def test_walking_and_running_the_same_distance_find_the_same_chests(
    signed_in, db_session, member
):
    """The old walked-mile bonus roll is gone: the ladder is the whole cadence,
    and a Mile is a Mile whichever way it was covered."""
    other = db_session.query(models.User).filter(models.User.username == "admin").one()
    for user_id, activity in ((member.id, "walk"), (other.id, "run")):
        for day in range(3):
            db_session.add(
                models.Workout(
                    user_id=user_id,
                    activity=activity,
                    start_ts=security.now_utc() - dt.timedelta(hours=3 + day * 24),
                    duration_s=6 * 3600,
                    distance_mi=20.0,
                    active_kcal=1400.0,
                    avg_hr=None,
                    source="sync",
                    flags={},
                    created_at=security.now_utc(),
                )
            )
        db_session.commit()
        progress.process_user(db_session, user_id)
    assert [row.tier for row in chests(db_session, member.id)] == [
        row.tier for row in chests(db_session, other.id)
    ]


# --------------------------------------------------------------------------
# Race badges
# --------------------------------------------------------------------------


def badge_rows(db_session, user_id) -> list[models.BadgeEarn]:
    return (
        db_session.query(models.BadgeEarn)
        .filter(models.BadgeEarn.user_id == user_id)
        .order_by(models.BadgeEarn.id)
        .all()
    )


def stored_run(db_session, user_id, miles, *, duration_s=None, activity="run", offset_h=1):
    """One run written straight in, so the test picks its own numbers."""
    row = models.Workout(
        user_id=user_id,
        activity=activity,
        start_ts=security.now_utc() - dt.timedelta(hours=offset_h),
        duration_s=duration_s if duration_s is not None else int(miles * 9 * 60) or 600,
        distance_mi=miles,
        active_kcal=100.0,
        avg_hr=None,
        source="sync",
        flags={},
        created_at=security.now_utc(),
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_a_run_earns_only_its_highest_race_badge(signed_in, db_session, member):
    """A marathon is a marathon, not also a 5K and a 10K and a half."""
    stored_run(db_session, member.id, 26.3, offset_h=5)
    progress.process_user(db_session, member.id)
    rows = badge_rows(db_session, member.id)
    assert [row.badge_id for row in rows] == ["race_marathon"]


def test_each_race_distance_earns_its_own_badge(signed_in, db_session, member):
    for offset, (miles, expected) in enumerate(
        (
            (3.1, "race_5k"),
            (6.2, "race_10k"),
            (13.1, "race_half"),
            (26.2, "race_marathon"),
            (31.1, "race_ultra"),
        )
    ):
        row = stored_run(db_session, member.id, miles, offset_h=offset + 1)
        progress.process_user(db_session, member.id)
        earned = {badge.workout_id: badge.badge_id for badge in badge_rows(db_session, member.id)}
        assert earned[row.id] == expected, miles


def test_a_run_short_of_the_threshold_earns_nothing(signed_in, db_session, member):
    stored_run(db_session, member.id, 3.09)
    progress.process_user(db_session, member.id)
    assert badge_rows(db_session, member.id) == []


def test_race_badges_repeat_and_carry_the_day_of_the_run(signed_in, db_session, member):
    first = stored_run(db_session, member.id, 4.0, offset_h=48)
    second = stored_run(db_session, member.id, 5.0, offset_h=2)
    progress.process_user(db_session, member.id)
    rows = badge_rows(db_session, member.id)
    assert [row.badge_id for row in rows] == ["race_5k", "race_5k"]
    # The date on the badge is the date of the run, never the clock.
    assert {row.workout_id: row.earned_at for row in rows} == {
        first.id: first.start_ts,
        second.id: second.start_ts,
    }


def test_only_running_earns_a_race_badge_this_round(signed_in, db_session, member):
    for offset, activity in enumerate(("walk", "cycle", "swim")):
        stored_run(
            db_session, member.id, 30.0, activity=activity, duration_s=6 * 3600, offset_h=offset + 1
        )
    progress.process_user(db_session, member.id)
    assert badge_rows(db_session, member.id) == []


def test_a_run_flagged_impossible_earns_nothing(signed_in, db_session, member):
    """Ten miles in twenty minutes is not a race, whatever the watch says."""
    created = signed_in.post(
        "/api/workouts",
        json={
            "activity": "run",
            "start_ts": (security.now_utc() - dt.timedelta(hours=4)).isoformat(),
            "duration_s": 20 * 60,
            "distance_mi": 10.0,
        },
    )
    assert created.status_code == 201
    assert created.json()["flags"]["impossible_pace"] is True
    assert created.json()["race_badge"] is None
    assert badge_rows(db_session, member.id) == []


def test_a_manually_entered_run_earns_its_badge(signed_in, db_session, member):
    created = log_workout(signed_in, "run", 6.5, pace_min=10)
    assert created["race_badge"] == "race_10k"
    assert [row.badge_id for row in badge_rows(db_session, member.id)] == ["race_10k"]


def test_a_replayed_history_earns_the_same_badges_once(signed_in, db_session, member):
    stored_run(db_session, member.id, 13.5, offset_h=30)
    stored_run(db_session, member.id, 3.5, offset_h=6)
    progress.process_user(db_session, member.id)
    before = [(row.badge_id, row.workout_id, row.earned_at) for row in badge_rows(db_session, member.id)]
    assert len(before) == 2

    # A sweep that finds nothing new must not award anything again.
    progress.process_user(db_session, member.id)
    assert len(badge_rows(db_session, member.id)) == 2

    # And a full rebuild returns exactly the same rows, dates included.
    progress.recompute(db_session, member.id)
    after = [(row.badge_id, row.workout_id, row.earned_at) for row in badge_rows(db_session, member.id)]
    assert after == before


def test_the_profile_lists_every_race_badge_with_its_count(signed_in, db_session, member):
    stored_run(db_session, member.id, 3.2, offset_h=30)
    stored_run(db_session, member.id, 3.4, offset_h=6)
    body = profile(signed_in)
    rows = {row["id"]: row for row in body["race_badges"]}
    assert list(rows) == [badge.id for badge in achievements.RACE_BADGES]
    assert rows["race_5k"]["count"] == 2
    assert rows["race_5k"]["first_earned_at"] < rows["race_5k"]["last_earned_at"]
    assert rows["race_marathon"] == {
        "id": "race_marathon",
        "name": "Marathon",
        "distance_mi": 26.2,
        "count": 0,
        "first_earned_at": None,
        "last_earned_at": None,
    }


def test_a_race_badge_can_be_worn_in_a_slot(signed_in, db_session, member):
    refused = signed_in.patch("/api/profile", json={"displayed_badges": ["race_ultra"]})
    assert refused.status_code == 400

    log_workout(signed_in, "run", 13.2, pace_min=9)
    accepted = signed_in.patch("/api/profile", json={"displayed_badges": ["race_half"]})
    assert accepted.status_code == 200
    assert accepted.json()["displayed_badges"] == ["race_half"]


def test_one_account_cannot_see_another(signed_in, db_session, admin, client):
    from conftest import ADMIN

    log_workout(signed_in, "run", 5.0)
    assert profile(signed_in)["xp"] > 0
    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    other = profile(signed_in)
    assert other["xp"] == 0
    assert all(row["count"] == 0 for row in other["race_badges"])
