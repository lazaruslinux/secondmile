"""Route lines: trimming, thinning, the sync path, the endpoint, and the backfill.

Every coordinate here is invented. The trim is the whole privacy story of this
feature, so the fixtures are built from round numbers whose distances are easy
to check by hand: at these latitudes a thousandth of a degree north is about
111 metres, which makes the two hundred metre radius fall between the first and
the second point of a line stepping by 0.001.
"""

import argparse

import pytest

from app import models, routemaps
from conftest import make_user

# One degree of latitude is roughly 111.19 km anywhere.
_M_PER_MILLI_DEG = 111.19


def line(count: int, *, step: float = 0.001, lat: float = 10.0, lon: float = 20.0) -> list[dict]:
    """A straight synthetic trace heading north, in the shape the export sends."""
    return [
        {
            "latitude": round(lat + index * step, 7),
            "longitude": lon,
            "altitude": 100.0,
            "speed": 2.5,
            "horizontalAccuracy": 4.0,
        }
        for index in range(count)
    ]


def zigzag(count: int, *, step: float = 0.0005, swing: float = 0.0004) -> list[dict]:
    """A trace that corners constantly, so thinning has real work to do."""
    return [
        {
            "latitude": round(10.0 + index * step, 7),
            "longitude": round(20.0 + (swing if index % 2 else -swing), 7),
        }
        for index in range(count)
    ]


def export(*workouts) -> dict:
    return {"data": {"workouts": list(workouts)}}


def workout(name, start, duration, miles=2.0, route=None) -> dict:
    entry = {
        "name": name,
        "start": start,
        "duration": duration,
        "distance": {"qty": miles, "units": "mi"},
        "activeEnergyBurned": {"qty": 200, "units": "kcal"},
    }
    if route is not None:
        entry["route"] = route
    return entry


def post(client, token, payload):
    return client.post("/api/ingest", json=payload, headers={"Authorization": f"Bearer {token}"})


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------


def test_haversine_matches_the_degree_of_latitude():
    metres = routemaps.haversine_m((10.0, 20.0), (10.001, 20.0))
    assert abs(metres - _M_PER_MILLI_DEG) < 1.0


def test_both_ends_are_trimmed_away():
    points = routemaps.read_points(line(60))
    kept = routemaps.trim_ends(points)
    # 0.001 of a degree is 111 m and 0.002 is 222 m, so exactly two points at
    # each end fall inside the two hundred metre radius.
    assert len(kept) == 56
    assert kept[0] == (10.002, 20.0)
    assert kept[-1] == (10.057, 20.0)
    assert routemaps.haversine_m(kept[0], points[0]) > routemaps.TRIM_RADIUS_M
    assert routemaps.haversine_m(kept[-1], points[-1]) > routemaps.TRIM_RADIUS_M


def test_a_point_near_the_end_is_dropped_even_from_the_middle():
    """An out-and-back past the door loses the middle stretch too."""
    out = line(20)
    back = list(reversed(out))
    kept = routemaps.trim_ends(routemaps.read_points(out + back))
    # The turn is far away, the fold in the middle is at the start point.
    assert all(point[0] > 10.0018 for point in kept)


def test_a_short_route_vanishes_entirely():
    """A loop that starts and ends at home stores nothing at all."""
    assert routemaps.route_points(line(12, step=0.0005)) is None
    assert routemaps.route_points(line(3)) is None
    assert routemaps.route_points([]) is None


def test_thinning_respects_the_budget_and_keeps_the_ends():
    points = routemaps.read_points(zigzag(3000))
    thinned = routemaps.simplify(points)
    assert len(thinned) <= routemaps.MAX_ROUTE_POINTS
    assert thinned[0] == points[0]
    assert thinned[-1] == points[-1]
    assert thinned == sorted(thinned)


def test_a_long_route_survives_the_whole_pipeline():
    stored = routemaps.route_points(zigzag(10000))
    assert stored is not None
    assert len(stored) <= routemaps.MAX_ROUTE_POINTS
    # Stored as plain [lat, lon] pairs rounded to five decimals.
    assert all(len(pair) == 2 for pair in stored)
    assert all(round(value, routemaps.COORD_DECIMALS) == value for pair in stored for value in pair)


def test_a_straight_line_is_not_padded_out_to_the_budget():
    """Nothing is kept that the line already passes through."""
    stored = routemaps.route_points(line(400))
    assert stored is not None
    assert len(stored) == 2


def test_an_enormous_trace_is_strided_down_before_any_work(monkeypatch):
    """The ceiling on raw points keeps the shape and both of its ends."""
    monkeypatch.setattr(routemaps, "MAX_RAW_POINTS", 10)
    raw = line(100)
    points = routemaps.read_points(raw)
    assert len(points) <= 10
    assert points[0] == (10.0, 20.0)
    assert points[-1] == (raw[-1]["latitude"], 20.0)


def test_malformed_points_are_skipped_not_fatal():
    raw = [
        {"latitude": 10.0, "longitude": 20.0},
        "not a point",
        {"latitude": "north", "longitude": 20.0},
        {"longitude": 20.0},
        {"latitude": 999.0, "longitude": 20.0},
        {"latitude": True, "longitude": 20.0},
        {"latitude": 10.001, "longitude": 20.0},
    ]
    assert routemaps.read_points(raw) == [(10.0, 20.0), (10.001, 20.0)]
    assert routemaps.read_points("a string") == []
    assert routemaps.read_points(None) == []


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------


def test_a_synced_workout_stores_its_route(signed_in, ingest_token, db_session):
    payload = export(
        workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, route=line(60))
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1

    stored = db_session.query(models.WorkoutRoute).one()
    assert stored.workout_id == db_session.query(models.Workout).one().id
    assert 10 <= len(stored.points) <= routemaps.MAX_ROUTE_POINTS
    # The stored line starts past the trim radius, not at the first fix.
    assert stored.points[0] == [10.002, 20.0]


def test_a_workout_without_a_route_stores_none(signed_in, ingest_token, db_session):
    payload = export(workout("Outdoor Walk", "2026-07-20T06:12:00+00:00", 2400, 2.1))
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1
    assert db_session.query(models.WorkoutRoute).count() == 0


def test_a_broken_route_never_costs_the_workout(signed_in, ingest_token, db_session):
    payload = export(
        workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, route="not a list"),
        workout("Outdoor Walk", "2026-07-20T08:00:00+00:00", 2400, 2.1, route=[{"lat": 1}]),
        workout("Indoor Cycle", "2026-07-20T09:00:00+00:00", 1800, 6.0, route=[]),
    )
    response = post(signed_in, ingest_token, payload)
    assert response.json() == {"imported": 3, "skipped": 0, "flagged": 0, "ignored": 0}
    assert db_session.query(models.WorkoutRoute).count() == 0


def test_the_response_shape_is_unchanged_by_routes(signed_in, ingest_token, db_session):
    payload = export(
        workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, route=line(60))
    )
    assert set(post(signed_in, ingest_token, payload).json()) == {
        "imported",
        "skipped",
        "flagged",
        "ignored",
    }
    # The tally lives in the log instead, where a self-hoster can find it.
    assert db_session.query(models.IngestLog).one().result["routes_stored"] == 1


def test_a_skipped_duplicate_leaves_the_route_alone(signed_in, ingest_token, db_session):
    first = export(
        workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, route=line(60))
    )
    assert post(signed_in, ingest_token, first).json()["imported"] == 1
    stored = list(db_session.query(models.WorkoutRoute).one().points)

    # The same workout again, with a different trace attached to it.
    second = export(
        workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, route=line(60, lon=30.0))
    )
    assert post(signed_in, ingest_token, second).json()["skipped"] == 1
    assert db_session.query(models.WorkoutRoute).count() == 1
    assert db_session.query(models.WorkoutRoute).one().points == stored


# --------------------------------------------------------------------------
# The endpoint
# --------------------------------------------------------------------------


def test_history_rows_say_whether_they_have_a_route(signed_in, ingest_token):
    payload = export(
        workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, route=line(60)),
        workout("Outdoor Walk", "2026-07-20T08:00:00+00:00", 2400, 2.1),
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 2

    rows = signed_in.get("/api/workouts").json()
    assert {row["activity"]: row["has_route"] for row in rows} == {"run": True, "walk": False}


def test_a_workout_that_carried_no_trace_has_no_route(signed_in, db_session, member):
    from conftest import log_workout

    row = log_workout(db_session, member.id)
    assert signed_in.get("/api/workouts").json()[0]["has_route"] is False
    assert signed_in.get(f"/api/workouts/{row.id}/route").status_code == 404


def test_the_route_endpoint_returns_the_stored_points(signed_in, ingest_token, db_session):
    payload = export(
        workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, route=line(60))
    )
    post(signed_in, ingest_token, payload)
    workout_id = db_session.query(models.Workout).one().id

    response = signed_in.get(f"/api/workouts/{workout_id}/route")
    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["points"]
    assert body["points"] == db_session.query(models.WorkoutRoute).one().points


def test_a_route_is_not_readable_without_a_session(client, signed_in, ingest_token, db_session):
    post(
        signed_in,
        ingest_token,
        export(workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, route=line(60))),
    )
    workout_id = db_session.query(models.Workout).one().id
    signed_in.post("/api/auth/logout")
    assert signed_in.get(f"/api/workouts/{workout_id}/route").status_code == 401


def test_another_account_cannot_read_your_route(signed_in, ingest_token, db_session):
    post(
        signed_in,
        ingest_token,
        export(workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, route=line(60))),
    )
    workout_id = db_session.query(models.Workout).one().id

    make_user(db_session, "stranger", "stranger-password-1")
    signed_in.post("/api/auth/logout")
    signed_in.post(
        "/api/auth/login", json={"username": "stranger", "password": "stranger-password-1"}
    )
    # The same 404 a missing route gets: nothing here says the workout exists.
    assert signed_in.get(f"/api/workouts/{workout_id}/route").status_code == 404


def test_an_unknown_workout_id_is_a_plain_404(signed_in):
    assert signed_in.get("/api/workouts/424242/route").status_code == 404


# --------------------------------------------------------------------------
# The backfill
# --------------------------------------------------------------------------


def _backfill(db_session, monkeypatch, username="runner"):
    import manage

    monkeypatch.setattr(manage, "_session", lambda: db_session)
    manage.cmd_backfill_routes(argparse.Namespace(username=username))


def test_backfill_draws_the_routes_the_log_already_holds(
    signed_in, ingest_token, db_session, monkeypatch
):
    payload = export(
        workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, route=line(60)),
        workout("Outdoor Walk", "2026-07-20T08:00:00+00:00", 2400, 2.1, route=line(80)),
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 2

    # The state an install upgrading into this feature is in: the lines were
    # never drawn, and the stored payload still carries its traces the way
    # every row written before the strip does. The endpoint strips them now, so
    # the pre-strip row has to be put back by hand for the backfill to have
    # anything to read.
    db_session.query(models.WorkoutRoute).delete()
    db_session.query(models.IngestLog).one().payload = payload
    db_session.commit()

    _backfill(db_session, monkeypatch)
    assert db_session.query(models.WorkoutRoute).count() == 2

    stored = {row.workout_id: row.points for row in db_session.query(models.WorkoutRoute)}
    _backfill(db_session, monkeypatch)
    assert db_session.query(models.WorkoutRoute).count() == 2
    assert {row.workout_id: row.points for row in db_session.query(models.WorkoutRoute)} == stored


def test_backfill_leaves_everything_else_alone(signed_in, ingest_token, db_session, monkeypatch):
    payload = export(
        workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 6.5, route=line(60))
    )
    post(signed_in, ingest_token, payload)
    db_session.query(models.WorkoutRoute).delete()
    # The pre-strip row again, so the backfill has a trace to draw and this
    # case is really watching a run that did something.
    db_session.query(models.IngestLog).one().payload = payload
    db_session.commit()

    before = db_session.query(models.UserProgress).one()
    badges = db_session.query(models.BadgeEarn).count()
    experience, level = before.xp, before.level

    _backfill(db_session, monkeypatch)

    after = db_session.query(models.UserProgress).one()
    assert (after.xp, after.level) == (experience, level)
    assert db_session.query(models.BadgeEarn).count() == badges
    assert db_session.query(models.Workout).count() == 1


def test_backfill_refuses_an_unknown_account(db_session, monkeypatch, member):
    with pytest.raises(SystemExit):
        _backfill(db_session, monkeypatch, username="nobody")
