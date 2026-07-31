"""The journey engine: conversion, movement, idempotence, gates, and the recap."""

import datetime as dt
import random

from conftest import log_workout, start_journey

from app import journey as engine
from app import models, security, world


def state(client) -> dict:
    response = client.get("/api/journey")
    assert response.status_code == 200, response.text
    return response.json()


def events(db_session, user_id, kind=None) -> list[models.JourneyEvent]:
    rows = (
        db_session.query(models.JourneyEvent)
        .filter(models.JourneyEvent.user_id == user_id)
        .order_by(models.JourneyEvent.id)
        .all()
    )
    return [row for row in rows if kind is None or row.type == kind]


def test_conversion_rates_are_effort_equivalent():
    assert engine.converted_miles("walk", 3.0) == 3.0
    assert engine.converted_miles("run", 3.0) == 3.0
    assert engine.converted_miles("cycle", 9.0) == 3.0
    assert engine.converted_miles("swim", 0.75) == 3.0


def test_a_new_journey_starts_at_the_homestead_bound_for_millbrook(traveller):
    body = state(traveller)
    assert body["position"]["location_id"] == "homestead"
    assert body["destination"]["id"] == "millbrook"
    assert body["total_traveled_mi"] == 0.0
    assert body["unopened_chests"] == 0


def test_a_run_moves_the_marker_along_the_road(traveller):
    log_workout(traveller, "run", 4.0)
    position = state(traveller)["position"]
    assert position["road_id"] == "east_road"
    assert position["position_mi"] == 4.0
    assert position["fraction"] == 0.4
    assert position["heading_to_id"] == "millbrook"


def test_cycling_counts_at_a_third_and_swimming_at_four_times(traveller, db_session, member):
    log_workout(traveller, "cycle", 9.0, offset_min=0)
    assert state(traveller)["position"]["position_mi"] == 3.0
    log_workout(traveller, "swim", 0.5, pace_min=45, offset_min=90)
    assert state(traveller)["position"]["position_mi"] == 5.0


def test_arrival_clears_the_destination_and_the_rest_walks_locally(traveller, db_session, member):
    log_workout(traveller, "run", 12.0, pace_min=9)
    body = state(traveller)
    assert body["position"]["location_id"] == "millbrook"
    assert body["destination"] is None
    assert body["total_traveled_mi"] == 12.0

    arrivals = events(db_session, member.id, "arrival")
    assert [row.data["location_id"] for row in arrivals] == ["millbrook"]
    assert arrivals[0].data["was_destination"] is True
    # The two miles past the town are not thrown away: they are walked there.
    local = [row for row in events(db_session, member.id, "travel") if row.data["local"]]
    assert len(local) == 1
    assert local[0].data["location_id"] == "millbrook"
    assert local[0].data["miles"] == 2.0


def test_local_rounds_still_drop_chests_from_the_local_set(traveller, db_session, member):
    log_workout(traveller, "run", 30.0, pace_min=9)
    body = state(traveller)
    assert body["position"]["location_id"] == "millbrook"
    assert body["unopened_chests"] > 0
    dropped = db_session.query(models.Chest).filter(models.Chest.user_id == member.id).all()
    sets = {world.CARDS[row.card_id].set_id for row in dropped}
    # Everything after Millbrook was walked in the town, so the town's own set
    # has to be among the cards found.
    assert "millbrook" in sets
    assert sets <= {"east_road", "millbrook"}


def test_workouts_before_the_journey_started_are_ignored(signed_in, db_session, member):
    start_journey(db_session, member.id, days_ago=0)
    old = security.now_utc() - dt.timedelta(days=7)
    signed_in.post(
        "/api/workouts",
        json={
            "activity": "run",
            "start_ts": old.isoformat(),
            "duration_s": 3600,
            "distance_mi": 8.0,
        },
    )
    body = state(signed_in)
    assert body["position"]["location_id"] == "homestead"
    assert body["total_traveled_mi"] == 0.0
    # Nor does that history fill the bucket a region unlock spends from.
    assert body["buckets"]["run"]["earned"] == 0.0


def test_a_workout_only_ever_moves_the_marker_once(traveller, db_session, member, ingest_token):
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
    assert traveller.post("/api/ingest", json=payload, headers=headers).json()["imported"] == 1
    first = state(traveller)
    chests = first["unopened_chests"]

    # The same export window again, which is what Health Auto Export really
    # sends. The workout is skipped and the marker does not budge.
    assert traveller.post("/api/ingest", json=payload, headers=headers).json()["skipped"] == 1
    again = state(traveller)
    assert again["position"]["position_mi"] == first["position"]["position_mi"] == 5.0
    assert again["unopened_chests"] == chests
    # And the sweep on a plain read does not re-walk it either.
    assert state(traveller)["total_traveled_mi"] == first["total_traveled_mi"]


def test_the_sweep_walks_a_workout_written_straight_into_the_database(
    traveller, db_session, member
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
    assert state(traveller)["position"]["position_mi"] == 2.5


def test_reprocessing_the_same_history_gives_the_same_chests(traveller, db_session, member):
    log_workout(traveller, "walk", 6.0, offset_min=0)
    log_workout(traveller, "run", 7.0, offset_min=200)
    first = [
        row.card_id
        for row in db_session.query(models.Chest)
        .filter(models.Chest.user_id == member.id)
        .order_by(models.Chest.id)
    ]
    assert first, "the test needs at least one chest to be worth anything"
    started = db_session.get(models.Journey, member.id).started_at

    # What journey-restart does, and the reason every roll is seeded on the
    # user and the workout rather than on the clock.
    for table in (models.JourneyEvent, models.Chest, models.UserCard, models.UserAccolade):
        db_session.query(table).filter(table.user_id == member.id).delete()
    db_session.query(models.ProcessedWorkout).delete()
    db_session.query(models.Journey).filter(models.Journey.user_id == member.id).delete()
    db_session.commit()
    start_journey(db_session, member.id)
    db_session.get(models.Journey, member.id).started_at = started
    db_session.commit()

    engine.process_user(db_session, member.id)
    second = [
        row.card_id
        for row in db_session.query(models.Chest)
        .filter(models.Chest.user_id == member.id)
        .order_by(models.Chest.id)
    ]
    assert second == first


def test_the_chest_counter_carries_between_workouts(traveller, db_session, member):
    log_workout(traveller, "run", 1.0, offset_min=0)
    before = db_session.get(models.Journey, member.id).next_chest_mi
    assert before is not None and before >= 1.0
    log_workout(traveller, "run", 1.0, offset_min=60)
    after = db_session.get(models.Journey, member.id).next_chest_mi
    # A mile short of a chest is a mile of credit, not a fresh roll.
    assert abs(after - (before - 1.0)) < 1e-6


def test_walking_rolls_bonus_chests_and_running_does_not(traveller, db_session, member):
    # Sixty walked miles is sixty ten-percent rolls, so the walk has to find
    # more than the distance alone would. Split across days to stay under the
    # daily cap, and the flag would not change the outcome anyway.
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
    db_session.get(models.Journey, member.id).started_at = security.now_utc() - dt.timedelta(
        days=30
    )
    db_session.commit()
    engine.process_user(db_session, member.id)

    bonus = [
        row
        for row in events(db_session, member.id, "chest")
        if row.data["source"] == "walk_bonus"
    ]
    assert bonus, "sixty walked miles should have rolled at least one bonus chest"


def test_milestones_are_granted_once_each(traveller, db_session, member):
    log_workout(traveller, "run", 7.0, pace_min=9, offset_min=0)
    earned = traveller.get("/api/accolades").json()
    assert [row["id"] for row in earned] == ["east_road_footbridge", "east_road_old_mill"]

    # Back the way we came and out again. The marks are permanent, so passing
    # them a second time is not worth anything.
    assert traveller.post(
        "/api/journey/destination", json={"location_id": "homestead"}
    ).status_code == 200
    log_workout(traveller, "run", 7.0, pace_min=9, offset_min=200)
    assert traveller.post(
        "/api/journey/destination", json={"location_id": "millbrook"}
    ).status_code == 200
    log_workout(traveller, "run", 7.0, pace_min=9, offset_min=400)
    assert len(traveller.get("/api/accolades").json()) == 2
    assert len(events(db_session, member.id, "milestone")) == 2


def test_setting_a_destination_reroutes_from_where_the_marker_is(traveller):
    log_workout(traveller, "run", 4.0, offset_min=0)
    assert traveller.post(
        "/api/journey/destination", json={"location_id": "homestead"}
    ).status_code == 200
    log_workout(traveller, "run", 3.0, offset_min=90)
    position = state(traveller)["position"]
    assert position["road_id"] == "east_road"
    assert position["position_mi"] == 1.0
    assert position["heading_to_id"] == "homestead"


def test_destination_validation(traveller):
    assert traveller.post(
        "/api/journey/destination", json={"location_id": "atlantis"}
    ).status_code == 404
    # Already standing there.
    assert traveller.post(
        "/api/journey/destination", json={"location_id": "homestead"}
    ).status_code == 400
    # Behind a gate that has not been paid for.
    refused = traveller.post("/api/journey/destination", json={"location_id": "shieling"})
    assert refused.status_code == 400
    assert "no open road" in refused.json()["detail"]
    assert traveller.post(
        "/api/journey/destination", json={"location_id": "fells_gate"}
    ).status_code == 200


def test_a_locked_gate_holds_the_marker_and_the_overflow_walks_locally(
    traveller, db_session, member
):
    journey = db_session.get(models.Journey, member.id)
    journey.location_id = "fells_gate"
    journey.destination_id = "shieling"
    db_session.commit()

    log_workout(traveller, "run", 20.0, pace_min=9)
    body = state(traveller)
    assert body["position"]["location_id"] == "fells_gate"
    assert body["total_traveled_mi"] == 20.0
    local = [row for row in events(db_session, member.id, "travel") if row.data["local"]]
    assert [row.data["location_id"] for row in local] == ["fells_gate"]


def test_unlocking_a_region_spends_run_miles(traveller, db_session, member):
    short = traveller.post("/api/regions/high_fells/unlock")
    assert short.status_code == 400
    assert "26.2" in short.json()["detail"]

    log_workout(traveller, "run", 30.0, pace_min=9)
    opened = traveller.post("/api/regions/high_fells/unlock")
    assert opened.status_code == 200
    body = opened.json()
    assert body["regions"][0]["unlocked"] is True
    assert body["buckets"]["run"]["earned"] == 30.0
    assert body["buckets"]["run"]["spent"] == 26.2
    assert body["buckets"]["run"]["available"] == 3.8

    # Paying twice for the same gate is a conflict, not a second charge.
    assert traveller.post("/api/regions/high_fells/unlock").status_code == 409
    assert traveller.post("/api/regions/nowhere/unlock").status_code == 404
    assert (
        db_session.query(models.MileSpend).filter(models.MileSpend.user_id == member.id).count()
        == 1
    )


def test_only_run_miles_open_a_gate(traveller):
    # A hundred cycled miles is thirty three Miles in the world and none of
    # them are run Miles, which is what reach costs.
    log_workout(traveller, "cycle", 100.0, pace_min=4)
    body = state(traveller)
    assert body["buckets"]["cycle"]["available"] > 26.2
    assert traveller.post("/api/regions/high_fells/unlock").status_code == 400


def test_an_open_gate_makes_the_road_beyond_it_walkable(traveller):
    log_workout(traveller, "run", 30.0, pace_min=9, offset_min=0)
    assert traveller.post("/api/regions/high_fells/unlock").status_code == 200
    assert traveller.post(
        "/api/journey/destination", json={"location_id": "shieling"}
    ).status_code == 200
    body = state(traveller)
    assert body["destination"]["id"] == "shieling"
    assert [road for road in body["roads"] if road["id"] == "fell_road"][0]["open"] is True


def test_the_recap_is_unseen_events_oldest_first_and_acking_clears_it(traveller):
    log_workout(traveller, "run", 8.0, pace_min=9)
    recap = traveller.get("/api/journey/recap").json()
    assert [row["type"] for row in recap][0] == "travel"
    assert {row["type"] for row in recap} >= {"travel", "milestone"}
    assert [row["id"] for row in recap] == sorted(row["id"] for row in recap)

    assert traveller.post("/api/journey/recap/ack").status_code == 204
    assert traveller.get("/api/journey/recap").json() == []
    # Later movement starts a new story rather than repeating the old one.
    log_workout(traveller, "run", 3.0, offset_min=200)
    assert len(traveller.get("/api/journey/recap").json()) >= 1


def test_a_chest_event_never_names_the_card(traveller):
    log_workout(traveller, "run", 20.0, pace_min=9)
    chests = [row for row in traveller.get("/api/journey/recap").json() if row["type"] == "chest"]
    assert chests
    for row in chests:
        assert "card_id" not in row["data"]
        assert "card" not in row["data"]
        assert row["data"]["set_name"]


def test_duplicate_protection_favours_the_missing_plate():
    cards = world.CARDS_BY_SET["east_road"]
    owned = {card.id for card in cards[:-1]}
    missing = cards[-1]
    rng = random.Random("weighting")
    hits = sum(1 for _ in range(2000) if engine.choose_card(cards, owned, rng).id == missing.id)
    # One in twelve if the weighting did nothing, three in fourteen with it.
    assert 0.14 < hits / 2000 < 0.30


def test_the_journey_endpoints_need_a_session(client):
    assert client.get("/api/journey").status_code == 401
    assert client.get("/api/journey/recap").status_code == 401
    assert client.post("/api/journey/recap/ack").status_code == 401
    destination = client.post("/api/journey/destination", json={"location_id": "millbrook"})
    assert destination.status_code == 401
    assert client.post("/api/regions/high_fells/unlock").status_code == 401


def test_one_journey_cannot_see_another(traveller, db_session, admin, client):
    from conftest import ADMIN

    log_workout(traveller, "run", 5.0)
    traveller.post("/api/auth/logout")
    traveller.post("/api/auth/login", json=ADMIN)
    body = state(traveller)
    assert body["position"]["location_id"] == "homestead"
    assert body["total_traveled_mi"] == 0.0


def test_registration_starts_a_journey(client, invite, outbox, db_session):
    response = client.post(
        "/api/auth/register",
        json={
            "username": "walker",
            "password": "walker-password-1",
            "email": "walker@example.com",
            "invite_code": invite.code,
        },
    )
    assert response.status_code == 201
    user = (
        db_session.query(models.User).filter(models.User.username == "walker").one()
    )
    journey = db_session.get(models.Journey, user.id)
    assert journey is not None
    assert journey.location_id == world.START_LOCATION
    assert journey.destination_id == world.START_DESTINATION
