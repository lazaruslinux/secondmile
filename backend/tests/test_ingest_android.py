"""The Android sync: a Health Connect export through the same door as an Apple one.

The bridge app posts a flat envelope of arrays rather than a list of workouts,
so app.healthconnect turns one into the other before anything else reads it.
What these cases hold to is that the translation is the only difference: the
same endpoint, the same token, the same dedupe, the same refusals by name, and
the same per-minute detail on the other side.
"""

import datetime as dt

from app import healthconnect, models
from test_ingest import export, post, workout


def moment(when: str) -> str:
    return when


def session(kind, start, end, meters=None, seconds=None) -> dict:
    entry = {"type": kind, "start_time": start, "end_time": end}
    if seconds is not None:
        entry["duration_seconds"] = seconds
    if meters is not None:
        entry["distance_meters"] = meters
    return entry


def reading(field, value, when, until=None) -> dict:
    """One record out of one of the arrays beside the sessions."""
    if until is None:
        return {field: value, "time": when}
    return {field: value, "start_time": when, "end_time": until}


def android(**arrays) -> dict:
    """A payload in the shape the Health Connect bridge actually posts."""
    return {"timestamp": "2026-07-20T14:00:00Z", "app_version": "1.4.0", **arrays}


def minutes(start: str, count: int, step: int = 1) -> list[str]:
    first = dt.datetime.fromisoformat(start)
    return [(first + dt.timedelta(minutes=index * step)).isoformat() for index in range(count)]


def test_all_four_activities_import(signed_in, ingest_token, db_session):
    payload = android(
        exercise=[
            session("WALKING", "2026-07-20T06:12:00-07:00", "2026-07-20T06:52:00-07:00", 3379.6),
            session("RUNNING", "2026-07-20T07:30:00-07:00", "2026-07-20T08:00:00-07:00", 4828.0),
            session("BIKING", "2026-07-20T18:00:00-07:00", "2026-07-20T18:45:00-07:00", 15288.0),
            session(
                "SWIMMING_POOL", "2026-07-21T06:00:00-07:00", "2026-07-21T06:25:00-07:00", 965.6
            ),
        ]
    )
    response = post(signed_in, ingest_token, payload)
    assert response.status_code == 200
    assert response.json() == {"imported": 4, "skipped": 0, "flagged": 0, "ignored": 0}

    stored = {row.activity for row in db_session.query(models.Workout)}
    assert stored == {"walk", "run", "cycle", "swim"}


def test_distance_and_duration_come_through_in_house_units(signed_in, ingest_token, db_session):
    payload = android(
        exercise=[
            session("RUNNING", "2026-07-20T07:30:00-07:00", "2026-07-20T08:00:00-07:00", 5000.0)
        ]
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1

    row = db_session.query(models.Workout).one()
    # 5000 metres is 3.107 miles, and the session ran half an hour.
    assert round(row.distance_mi, 3) == 3.107
    assert row.duration_s == 1800


def test_duration_falls_back_to_the_window_when_it_is_not_stated(
    signed_in, ingest_token, db_session
):
    payload = android(
        exercise=[
            session("WALKING", "2026-07-20T06:00:00-07:00", "2026-07-20T06:40:00-07:00", 3200.0)
        ]
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1
    assert db_session.query(models.Workout).one().duration_s == 2400


def test_a_stated_duration_is_preferred_over_the_window(signed_in, ingest_token, db_session):
    """A paused session runs shorter than the wall clock between its ends."""
    payload = android(
        exercise=[
            session(
                "RUNNING",
                "2026-07-20T07:00:00-07:00",
                "2026-07-20T08:00:00-07:00",
                5000.0,
                seconds=2400,
            )
        ]
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1
    assert db_session.query(models.Workout).one().duration_s == 2400


def test_the_same_export_twice_imports_nothing_the_second_time(signed_in, ingest_token, db_session):
    """The bridge re-sends inside its rolling window, so this is the common case."""
    payload = android(
        exercise=[
            session("RUNNING", "2026-07-20T07:30:00-07:00", "2026-07-20T08:00:00-07:00", 4828.0),
            session("WALKING", "2026-07-20T06:12:00-07:00", "2026-07-20T06:52:00-07:00", 3379.6),
        ]
    )
    first = post(signed_in, ingest_token, payload).json()
    second = post(signed_in, ingest_token, payload).json()

    assert first == {"imported": 2, "skipped": 0, "flagged": 0, "ignored": 0}
    assert second == {"imported": 0, "skipped": 2, "flagged": 0, "ignored": 0}
    assert db_session.query(models.Workout).count() == 2


def test_an_unmapped_exercise_type_is_ignored_and_named(signed_in, ingest_token, db_session):
    payload = android(
        exercise=[
            session("WALKING", "2026-07-20T06:12:00-07:00", "2026-07-20T06:52:00-07:00", 3379.6),
            session("STRENGTH_TRAINING", "2026-07-20T09:00:00-07:00", "2026-07-20T09:30:00-07:00"),
        ]
    )
    assert post(signed_in, ingest_token, payload).json() == {
        "imported": 1,
        "skipped": 0,
        "flagged": 0,
        "ignored": 1,
    }

    logged = db_session.query(models.IngestLog).one()
    refusals = logged.result["ignored_detail"]
    assert [item["reason"] for item in refusals] == ["unsupported activity"]
    assert refusals[0]["name"] == "Strength Training"


def test_a_session_with_no_readable_end_is_refused_by_name(signed_in, ingest_token, db_session):
    payload = android(
        exercise=[{"type": "RUNNING", "start_time": "not a timestamp", "end_time": "nor this"}]
    )
    assert post(signed_in, ingest_token, payload).json()["ignored"] == 1

    logged = db_session.query(models.IngestLog).one()
    assert logged.result["ignored_detail"][0]["reason"] == "unreadable start time"


def test_a_session_with_only_a_window_still_imports(signed_in, ingest_token, db_session):
    """No distance, no calories, no heart rate: a pool swim nobody measured."""
    payload = android(
        exercise=[session("SWIMMING_POOL", "2026-07-22T06:00:00Z", "2026-07-22T06:30:00Z")]
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1

    row = db_session.query(models.Workout).one()
    assert row.distance_mi == 0.0
    assert row.active_kcal == 0.0
    assert row.avg_hr is None


def test_an_indoor_type_is_marked_indoor(signed_in, ingest_token, db_session):
    payload = android(
        exercise=[
            session(
                "RUNNING_TREADMILL", "2026-07-20T07:00:00-07:00", "2026-07-20T07:30:00-07:00", 4000.0
            ),
            session("BIKING", "2026-07-20T18:00:00-07:00", "2026-07-20T18:30:00-07:00", 12000.0),
        ]
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 2

    marked = {row.activity: row.indoor for row in db_session.query(models.Workout)}
    assert marked == {"run": True, "cycle": False}


def test_calories_inside_the_window_become_the_workouts_own(signed_in, ingest_token, db_session):
    """The number manna is drawn from, summed out of the array beside the session."""
    stamps = minutes("2026-07-20T07:30:00-07:00", 4)
    payload = android(
        exercise=[
            session("RUNNING", "2026-07-20T07:30:00-07:00", "2026-07-20T08:00:00-07:00", 4828.0)
        ],
        active_calories=[reading("calories", 60.0, when) for when in stamps]
        # An hour later, so it belongs to no session and must not be counted.
        + [reading("calories", 500.0, "2026-07-20T09:30:00-07:00")],
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1
    assert db_session.query(models.Workout).one().active_kcal == 240.0


def test_heart_rate_becomes_the_average_and_the_high(signed_in, ingest_token, db_session):
    stamps = minutes("2026-07-20T07:30:00-07:00", 3)
    payload = android(
        exercise=[
            session("RUNNING", "2026-07-20T07:30:00-07:00", "2026-07-20T08:00:00-07:00", 4828.0)
        ],
        heart_rate=[
            reading("bpm", 150, stamps[0]),
            reading("bpm", 160, stamps[1]),
            reading("bpm", 170, stamps[2]),
        ],
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1

    row = db_session.query(models.Workout).one()
    assert row.avg_hr == 160.0
    assert row.max_hr == 170


def test_the_arrays_become_per_minute_detail(signed_in, ingest_token, db_session):
    stamps = minutes("2026-07-20T07:30:00-07:00", 3)
    payload = android(
        exercise=[
            session("RUNNING", "2026-07-20T07:30:00-07:00", "2026-07-20T08:00:00-07:00", 4828.0)
        ],
        heart_rate=[reading("bpm", 150 + index * 10, when) for index, when in enumerate(stamps)],
        active_calories=[reading("calories", 12.0, when) for when in stamps],
        steps=[reading("count", 170, when, when) for when in stamps],
        distance=[reading("meters", 160.9, when, when) for when in stamps],
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1

    rows = (
        db_session.query(models.WorkoutSample).order_by(models.WorkoutSample.minute).all()
    )
    assert [row.minute for row in rows] == [0, 1, 2]
    assert [row.hr_avg for row in rows] == [150, 160, 170]
    assert [row.steps for row in rows] == [170, 170, 170]
    assert all(row.active_kcal == 12.0 for row in rows)
    assert all(round(row.distance_mi, 3) == 0.1 for row in rows)


def test_several_readings_in_one_minute_are_folded_not_dropped(
    signed_in, ingest_token, db_session
):
    """A phone reporting every fifteen seconds keeps all four of them.

    app.samples takes the first reading it sees for a minute and ignores the
    rest, so the folding has to happen before it: without it three quarters of
    this session's steps and calories would go missing.
    """
    quarters = [
        "2026-07-20T07:30:00-07:00",
        "2026-07-20T07:30:15-07:00",
        "2026-07-20T07:30:30-07:00",
        "2026-07-20T07:30:45-07:00",
    ]
    payload = android(
        exercise=[
            session("WALKING", "2026-07-20T07:30:00-07:00", "2026-07-20T07:31:00-07:00", 100.0)
        ],
        steps=[reading("count", 25, when, when) for when in quarters],
        active_calories=[reading("calories", 2.0, when) for when in quarters],
        heart_rate=[
            reading("bpm", bpm, when) for bpm, when in zip((100, 110, 120, 130), quarters)
        ],
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1

    row = db_session.query(models.WorkoutSample).one()
    assert row.minute == 0
    assert row.steps == 100
    assert row.active_kcal == 8.0
    # The real low, mean and high of the minute rather than whichever arrived first.
    assert (row.hr_min, row.hr_avg, row.hr_max) == (100, 115, 130)


def test_the_pedometer_arrays_become_days_of_steps(signed_in, ingest_token, db_session):
    payload = android(
        # Middays, so the day each reading belongs to is the same one whatever
        # timezone the instance is set to.
        steps=[
            reading("count", 900, "2026-07-20T12:00:00Z", "2026-07-20T12:10:00Z"),
            reading("count", 1100, "2026-07-20T14:00:00Z", "2026-07-20T14:10:00Z"),
            reading("count", 400, "2026-07-21T12:00:00Z", "2026-07-21T12:10:00Z"),
        ]
    )
    assert post(signed_in, ingest_token, payload).json() == {
        "imported": 0,
        "skipped": 0,
        "flagged": 0,
        "ignored": 0,
    }

    days = {row.day: row.steps for row in db_session.query(models.DailySteps)}
    assert days == {dt.date(2026, 7, 20): 2000, dt.date(2026, 7, 21): 400}


def test_the_log_keeps_the_export_as_the_bridge_sent_it(signed_in, ingest_token, db_session):
    """What is worth having when a mapping turns out to be wrong."""
    payload = android(
        exercise=[
            session("RUNNING", "2026-07-20T07:30:00-07:00", "2026-07-20T08:00:00-07:00", 4828.0)
        ],
        heart_rate=[reading("bpm", 155, "2026-07-20T07:31:00-07:00")],
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1
    assert db_session.query(models.IngestLog).one().payload == payload


def test_an_android_workout_has_no_route(signed_in, ingest_token, db_session):
    """Health Connect has an exercise route API and the bridge does not export it."""
    payload = android(
        exercise=[
            session("RUNNING", "2026-07-20T07:30:00-07:00", "2026-07-20T08:00:00-07:00", 4828.0)
        ]
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1
    assert db_session.query(models.WorkoutRoute).count() == 0


def test_an_apple_export_is_never_translated():
    """The one thing the shape test must never get wrong."""
    apple = export(workout("Outdoor Walk", "2026-07-20T06:12:00-07:00", 2400.0, 2.1, 190, 104))
    assert healthconnect.looks_like(apple) is False
    assert healthconnect.looks_like({"workouts": [], "exercise": []}) is False
    assert healthconnect.looks_like({"data": {"metrics": []}, "exercise": []}) is False


def test_the_shape_test_wants_an_array_it_knows():
    assert healthconnect.looks_like({"timestamp": "2026-07-20T14:00:00Z"}) is False
    assert healthconnect.looks_like({"sleep": []}) is False
    assert healthconnect.looks_like(android(exercise=[])) is True
    assert healthconnect.looks_like("not an object") is False


def test_both_phones_can_sync_into_one_account(signed_in, ingest_token, db_session):
    """Nothing about a workout remembers which door it came through."""
    apple = export(workout("Outdoor Walk", "2026-07-20T06:12:00-07:00", 2400.0, 2.1, 190, 104))
    droid = android(
        exercise=[
            session("RUNNING", "2026-07-20T07:30:00-07:00", "2026-07-20T08:00:00-07:00", 4828.0)
        ]
    )
    assert post(signed_in, ingest_token, apple).json()["imported"] == 1
    assert post(signed_in, ingest_token, droid).json()["imported"] == 1

    stored = {row.activity: row.source for row in db_session.query(models.Workout)}
    assert stored == {"walk": "sync", "run": "sync"}
