"""The pipeline: conversion, experience, the level curve, chests, and replay."""

import datetime as dt
import random

from conftest import log_workout

from app import models, progress, security
from app.activity import converted_miles
from app.config import BORDER_LEVELS, CHEST_SPACING_MI


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


def test_experience_counts_both_distance_and_time():
    # Three Miles at ten points each, plus thirty minutes at one point each.
    assert progress.workout_xp("run", 3.0, 30 * 60) == 60
    # Nine cycled miles are three Miles, so the same distance credit.
    assert progress.workout_xp("cycle", 9.0, 30 * 60) == 60
    # Time alone still counts: a workout with no distance recorded is still
    # a workout that happened.
    assert progress.workout_xp("swim", 0.0, 45 * 60) == 45


def test_the_level_curve_costs_a_hundred_more_each_time():
    assert progress.xp_to_reach(1) == 0
    assert progress.xp_to_reach(2) == 200
    assert progress.xp_to_reach(3) == 500
    assert progress.xp_to_reach(4) == 900
    assert progress.level_for_xp(0) == 1
    assert progress.level_for_xp(199) == 1
    assert progress.level_for_xp(200) == 2
    assert progress.level_for_xp(499) == 2
    assert progress.level_for_xp(500) == 3
    # The window the level bar draws.
    assert progress.level_bounds(350) == (2, 150, 300)


def test_border_tiers_arrive_at_the_documented_levels():
    assert progress.border_tier(1) == 1
    assert progress.border_tier(4) == 1
    assert progress.border_tier(5) == 2
    assert progress.border_tier(19) == 3
    assert progress.border_tier(20) == 4
    assert progress.border_tier(50) == len(BORDER_LEVELS)
    assert progress.border_tier(500) == len(BORDER_LEVELS)


def test_a_workout_credits_experience_once(signed_in, db_session, member):
    log_workout(signed_in, "run", 4.0, pace_min=15)
    body = profile(signed_in)
    # Four Miles at ten, plus sixty minutes.
    assert body["xp"] == 100
    assert body["level"] == 1
    # A second read sweeps again and must not credit the same workout twice.
    assert profile(signed_in)["xp"] == 100


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
    assert profile(signed_in)["xp"] == 25 + 60


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
    assert body["xp"] == 80 + 60
    assert body["lifetime"]["run"]["distance_mi"] == 8.0


def test_chests_drop_on_the_documented_cadence(signed_in, db_session, member):
    log_workout(signed_in, "run", 30.0, pace_min=9)
    dropped = chests(db_session, member.id)
    low, high = CHEST_SPACING_MI
    assert 30.0 / high <= len(dropped) <= 30.0 / low + 1
    assert all(row.card_id for row in dropped)


def test_the_chest_accumulator_carries_between_workouts(signed_in, db_session, member):
    log_workout(signed_in, "run", 1.0, offset_min=0)
    row = db_session.get(models.UserProgress, member.id)
    gap, banked = row.next_chest_gap_mi, row.chest_progress_mi
    assert gap is not None and gap >= CHEST_SPACING_MI[0]
    assert banked == 1.0
    log_workout(signed_in, "run", 1.0, offset_min=60)
    row = db_session.get(models.UserProgress, member.id)
    # A mile short of a chest is a mile of credit, not a fresh roll.
    assert row.next_chest_gap_mi == gap
    assert abs(row.chest_progress_mi - 2.0) < 1e-6


def test_reprocessing_the_same_history_gives_the_same_chests(signed_in, db_session, member):
    log_workout(signed_in, "walk", 6.0, offset_min=0)
    log_workout(signed_in, "run", 7.0, offset_min=200)
    first = [row.card_id for row in chests(db_session, member.id)]
    assert first, "the test needs at least one chest to be worth anything"
    xp = db_session.get(models.UserProgress, member.id).xp

    # What recompute-progress does, and the reason every roll is seeded on the
    # account and the workout rather than on the clock.
    rebuilt = progress.recompute(db_session, member.id)
    assert [row.card_id for row in chests(db_session, member.id)] == first
    assert rebuilt.xp == xp


def test_walking_rolls_bonus_chests_and_running_does_not(signed_in, db_session, member):
    """Sixty walked miles is sixty ten-percent rolls on top of the distance."""
    for day in range(3):
        db_session.add(
            models.Workout(
                user_id=member.id,
                activity="walk",
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
    progress.process_user(db_session, member.id)
    walked = len(chests(db_session, member.id))

    # The same sixty Miles run instead. Same distance credit, no gathering.
    other = db_session.query(models.User).filter(models.User.username == "admin").one()
    for day in range(3):
        db_session.add(
            models.Workout(
                user_id=other.id,
                activity="run",
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
    progress.process_user(db_session, other.id)
    assert walked > len(chests(db_session, other.id))


def test_duplicate_protection_favours_the_missing_plate():
    from app import world

    cards = world.CARDS_BY_SET["hedgerow"]
    owned = {card.id for card in cards[:-1]}
    missing = cards[-1]
    rng = random.Random("weighting")
    hits = sum(1 for _ in range(2000) if progress.choose_card(cards, owned, rng).id == missing.id)
    # One in twelve if the weighting did nothing, three in fourteen with it.
    assert 0.14 < hits / 2000 < 0.30


def test_every_set_can_come_out_of_a_chest():
    rng = random.Random("sets")
    seen = {progress.choose_set(rng).id for _ in range(2000)}
    from app import world

    assert seen == set(world.CARD_SETS)


def test_one_account_cannot_see_another(signed_in, db_session, admin, client):
    from conftest import ADMIN

    log_workout(signed_in, "run", 5.0)
    assert profile(signed_in)["xp"] > 0
    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    assert profile(signed_in)["xp"] == 0
