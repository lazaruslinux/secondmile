"""The detail an export carries: per-minute samples, and the summaries beside them.

Every entry here is invented, in the shape a real Health Auto Export workout
arrives in: an array per minute of the session, and a handful of whole-session
summaries. What is being pinned is that none of it can ever cost a workout its
import, that a re-synced session is never described twice, that the climb
travels under the same permission a route line does, and that a deleted
workout's minutes are thrown away with the rest of it.

Nothing in this file earns anything, which is the point: no case here asserts a
mile, a medal, or a chest, because no reading in it touches one.
"""

import argparse
import datetime as dt

from conftest import make_user
from test_deletion import deleted_days_ago
from test_fellowship import befriend, hide, sign_in
from test_ingest import export, post
from test_steps import reading, sync

from app import config, history, models, samples, security

# The moment every entry below starts at: mid-morning on the frozen clock's own
# day, so a case about an array is never also a case about the backfill window.
START = "2026-04-15T09:00:00+00:00"


def at(minute: int) -> str:
    """The moment one per-minute sample says it covers."""
    return (dt.datetime.fromisoformat(START) + dt.timedelta(minutes=minute)).isoformat()


def point(qty, minute: int, units: str = "mi") -> dict:
    """One item of a per-minute array, in the four fields the export writes."""
    return {"qty": qty, "date": at(minute), "units": units, "source": "A watch"}


def beats(minute: int, low, avg, high, keys=("Min", "Avg", "Max")) -> dict:
    """One item of the heart rate array, whose keys arrive capitalised."""
    lowest, middle, highest = keys
    return {
        lowest: low,
        middle: avg,
        highest: high,
        "date": at(minute),
        "units": "count/min",
        "source": "A watch",
    }


def entry(minutes: int = 3, **extra) -> dict:
    """A workout entry carrying everything a real export sends with one.

    The arrays, the summaries, and the fields nothing reads are all here, so a
    case that passes against this one is passing against the shape a phone
    actually posts rather than against a fixture written to suit the parser.
    """
    built = {
        "name": "Outdoor Walk",
        "start": START,
        "end": at(minutes),
        "duration": 60.0 * minutes,
        "distance": {"qty": 0.15, "units": "mi"},
        "activeEnergyBurned": {"qty": 30.0, "units": "kcal"},
        "walkingAndRunningDistance": [point(0.05, index) for index in range(minutes)],
        "stepCount": [point(110 + index, index, "count") for index in range(minutes)],
        "activeEnergy": [point(10.0, index, "kcal") for index in range(minutes)],
        "basalEnergy": [point(1.4, index, "kcal") for index in range(minutes)],
        "heartRateData": [
            beats(index, 100 + index, 120 + index, 140 + index) for index in range(minutes)
        ],
        "elevationUp": {"qty": 142.0, "units": "ft"},
        "maxHeartRate": {"qty": 168.0, "units": "count/min"},
        "avgHeartRate": {"qty": 131.0, "units": "count/min"},
        "heartRate": {"avg": 131.0, "max": 168.0, "min": 96.0},
        "stepCadence": {"qty": 112.0, "units": "count/min"},
        "temperature": {"qty": 78.5, "units": "degF"},
        "humidity": {"qty": 44.0, "units": "%"},
        "flightsClimbed": {"qty": 4.0, "units": "count"},
        "isIndoor": False,
        "location": "Outdoor",
        "metadata": {},
    }
    built.update(extra)
    return built


def rows_for(db_session, workout_id: int) -> list[models.WorkoutSample]:
    db_session.expire_all()
    return (
        db_session.query(models.WorkoutSample)
        .filter(models.WorkoutSample.workout_id == workout_id)
        .order_by(models.WorkoutSample.minute)
        .all()
    )


def the_one_workout(db_session) -> models.Workout:
    db_session.expire_all()
    return db_session.query(models.Workout).one()


def backfill(db_session, monkeypatch) -> None:
    import manage

    monkeypatch.setattr(manage, "_session", lambda: db_session)
    manage.cmd_backfill_samples(argparse.Namespace())


def forget_the_detail(db_session) -> None:
    """Put the history back the way it looked before 0034 existed.

    The sync path writes the detail now, so a case about the backfill has to
    take it away again to have anything to find. The workouts, the payloads,
    and everything else stay exactly as they are, which is what a database
    upgraded to 0034 with years of history in it actually looks like.
    """
    db_session.query(models.WorkoutSample).delete()
    for row in db_session.query(models.Workout):
        row.elevation_gain_ft = None
        row.max_hr = None
        row.temperature_f = None
        row.humidity_pct = None
    db_session.commit()


# --------------------------------------------------------------------------
# Reading one entry
# --------------------------------------------------------------------------


def test_the_arrays_and_the_summaries_are_read_off_a_whole_entry():
    detail = samples.parse(entry())

    assert [row.minute for row in detail.minutes] == [0, 1, 2]
    assert [row.distance_mi for row in detail.minutes] == [0.05, 0.05, 0.05]
    assert [row.steps for row in detail.minutes] == [110, 111, 112]
    assert [row.hr_min for row in detail.minutes] == [100, 101, 102]
    assert [row.hr_avg for row in detail.minutes] == [120, 121, 122]
    assert [row.hr_max for row in detail.minutes] == [140, 141, 142]
    assert [row.active_kcal for row in detail.minutes] == [10.0, 10.0, 10.0]

    assert detail.elevation_gain_ft == 142.0
    assert detail.max_hr == 168
    assert detail.temperature_f == 78.5
    assert detail.humidity_pct == 44.0


def test_the_heart_rate_keys_are_read_in_either_case():
    """The real export capitalises them and other writers do not, and a card
    drawn from one of the two spellings would be blank for half the world."""
    lowered = entry(
        minutes=2,
        heartRateData=[
            beats(index, 90, 110, 130, keys=("min", "avg", "max")) for index in range(2)
        ],
    )
    detail = samples.parse(lowered)
    assert [(row.hr_min, row.hr_avg, row.hr_max) for row in detail.minutes] == [
        (90, 110, 130),
        (90, 110, 130),
    ]


def test_a_metric_phone_is_converted_into_the_units_the_columns_hold():
    """Distances are stored in miles whatever the phone says, and the climb and
    the air are stored in feet and Fahrenheit for the same reason: the export
    follows its owner's locale and the screen converts on the way out."""
    detail = samples.parse(
        entry(
            elevationUp={"qty": 100.0, "units": "m"},
            temperature={"qty": 20.0, "units": "degC"},
            walkingAndRunningDistance=[point(0.1, 0, "km")],
        )
    )
    assert round(detail.elevation_gain_ft, 1) == 328.1
    assert round(detail.temperature_f, 1) == 68.0
    assert round(detail.minutes[0].distance_mi, 4) == 0.0621


def test_only_the_active_energy_array_is_read_and_never_the_basal_one():
    """An entry carries both. Basal is the body ticking over, which it would be
    doing on the sofa, and it is not what a session burned: the line the
    workout row's own calories are drawn on is the line drawn here."""
    detail = samples.parse(
        entry(
            minutes=2,
            activeEnergy=[point(9.5, index, "kcal") for index in range(2)],
            basalEnergy=[point(1.4, index, "kcal") for index in range(2)],
        )
    )
    assert [row.active_kcal for row in detail.minutes] == [9.5, 9.5]

    # And a phone that counts in kilojoules is converted on the way in, the way
    # a metric distance is.
    metric = samples.parse(entry(minutes=1, activeEnergy=[point(41.84, 0, "kJ")]))
    assert round(metric.minutes[0].active_kcal, 1) == 10.0


def test_an_export_that_writes_the_array_under_the_summary_name_is_still_read():
    """The two spellings are the same measurement. Some versions of the export
    send the minutes under the name the whole-session figure uses."""
    named = entry(minutes=2)
    del named["activeEnergy"]
    named["activeEnergyBurned"] = [point(7.0, index, "kcal") for index in range(2)]
    assert [row.active_kcal for row in samples.parse(named).minutes] == [7.0, 7.0]


def test_the_highest_beat_falls_back_to_the_duplicate_summary():
    """An entry says it twice, and an export that carries only the object still
    knows the answer."""
    without = entry()
    del without["maxHeartRate"]
    assert samples.parse(without).max_hr == 168

    neither = entry()
    del neither["maxHeartRate"]
    del neither["heartRate"]
    assert samples.parse(neither).max_hr is None


def test_arrays_that_begin_apart_and_skip_minutes_still_line_up():
    """The three arrays are independent of each other: they start when their own
    sensor did, stop when it did, and skip whatever it missed. Every sample is
    placed by the moment it says it covers rather than by where it sits in its
    own list, or a strap picked up halfway would shift the whole walk."""
    detail = samples.parse(
        entry(
            walkingAndRunningDistance=[point(0.05, minute) for minute in (0, 1, 2, 3, 4)],
            stepCount=[point(90, minute, "count") for minute in (0, 2, 4)],
            heartRateData=[beats(minute, 100, 120, 140) for minute in (2, 4)],
        )
    )
    assert [row.minute for row in detail.minutes] == [0, 1, 2, 3, 4]
    assert [row.steps for row in detail.minutes] == [90, None, 90, None, 90]
    assert [row.hr_avg for row in detail.minutes] == [None, None, 120, None, 120]
    # The distance array covered every one of them, so nothing was lost by the
    # other two being sparse.
    assert all(row.distance_mi == 0.05 for row in detail.minutes)


def test_samples_with_no_readable_dates_keep_the_order_they_arrived_in():
    """The best a malformed export can be asked for, and it still says something
    true about the shape of the session."""
    detail = samples.parse(
        entry(
            walkingAndRunningDistance=[
                {"qty": 0.02, "date": "not a timestamp", "units": "mi"},
                {"qty": 0.03, "units": "mi"},
            ],
            stepCount=[],
            activeEnergy=[],
            heartRateData=[],
        )
    )
    assert [(row.minute, row.distance_mi) for row in detail.minutes] == [(0, 0.02), (1, 0.03)]


def test_a_reading_no_body_produced_is_dropped_on_its_own():
    """Dropped to nothing field by field, never taking the minute or the
    workout with it: the rest of what the session said still happened."""
    detail = samples.parse(
        entry(
            minutes=1,
            walkingAndRunningDistance=[point(40.0, 0)],
            stepCount=[point(-12, 0, "count")],
            activeEnergy=[point(4000.0, 0, "kcal")],
            heartRateData=[beats(0, 900, 1000, 1100)],
            elevationUp={"qty": -30.0, "units": "ft"},
            maxHeartRate={"qty": 4000.0, "units": "count/min"},
            heartRate={"avg": 131.0, "max": 4000.0, "min": 96.0},
            temperature={"qty": 5000.0, "units": "degF"},
            humidity={"qty": 400.0, "units": "%"},
        )
    )
    only = detail.minutes[0]
    assert (only.distance_mi, only.steps, only.active_kcal) == (None, None, None)
    assert (only.hr_min, only.hr_avg, only.hr_max) == (None, None, None)
    assert detail.elevation_gain_ft is None
    assert detail.max_hr is None
    assert detail.temperature_f is None
    assert detail.humidity_pct is None


def test_an_entry_that_says_nothing_extra_reads_as_no_detail_at_all():
    """What an older export, or another phone, or a third-party app sends. It is
    a workout with less to say rather than a workout that failed."""
    detail = samples.parse({"name": "Outdoor Run", "start": START, "duration": 1800})
    assert detail.minutes == []
    assert detail.elevation_gain_ft is None
    assert detail.max_hr is None
    assert samples.parse(None).minutes == []


def test_only_the_first_day_of_minutes_is_kept():
    """The cap is on the count and it is defensive: an export whose arrays repeat
    themselves costs one slice rather than a table nobody will ever draw."""
    over = config.MAX_WORKOUT_SAMPLES + 60
    detail = samples.parse(
        entry(
            walkingAndRunningDistance=[point(0.01, minute) for minute in range(over)],
            stepCount=[],
            heartRateData=[],
        )
    )
    assert len(detail.minutes) == config.MAX_WORKOUT_SAMPLES
    assert detail.minutes[-1].minute == config.MAX_WORKOUT_SAMPLES - 1


# --------------------------------------------------------------------------
# What the sync path does with it
# --------------------------------------------------------------------------


def test_the_detail_is_written_for_a_workout_that_was_just_born(
    signed_in, ingest_token, db_session
):
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1

    workout = the_one_workout(db_session)
    assert workout.elevation_gain_ft == 142.0
    assert workout.max_hr == 168
    assert workout.temperature_f == 78.5
    assert workout.humidity_pct == 44.0
    assert [row.minute for row in rows_for(db_session, workout.id)] == [0, 1, 2]
    assert [row.active_kcal for row in rows_for(db_session, workout.id)] == [10.0, 10.0, 10.0]
    logged = db_session.query(models.IngestLog).one()
    assert logged.result["samples_stored"] == 3


def test_a_re_synced_session_is_not_described_a_second_time(
    signed_in, ingest_token, db_session
):
    """Overlapping export windows arrive forever, so the same session is posted
    again and again. The duplicate is skipped before the detail is reached."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    again = post(signed_in, ingest_token, export(entry()))
    assert again.json() == {"imported": 0, "skipped": 1, "flagged": 0, "ignored": 0}

    workout = the_one_workout(db_session)
    assert len(rows_for(db_session, workout.id)) == 3
    latest = db_session.query(models.IngestLog).order_by(models.IngestLog.id.desc()).first()
    assert latest.result["samples_stored"] == 0


def test_a_metrics_export_writes_no_detail_at_all(signed_in, ingest_token, db_session):
    """The pedometer's own automation is a whole sync of its own and carries no
    workout, so there is nothing here for any of this to read."""
    assert sync(signed_in, ingest_token, metrics=reading(steps=6000, miles=2.5)).status_code == 200
    assert db_session.query(models.WorkoutSample).count() == 0
    assert db_session.query(models.Workout).count() == 0


def test_the_workout_still_imports_when_the_detail_cannot_be_read(
    signed_in, ingest_token, db_session, monkeypatch
):
    """The rule the whole module is written under: the detail is decoration, and
    a session that happened must never fail to import because of it."""

    def refuse(_entry):
        raise ValueError("no")

    monkeypatch.setattr(samples, "parse", refuse)
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1

    workout = the_one_workout(db_session)
    assert workout.distance_mi == 0.15
    assert workout.elevation_gain_ft is None
    assert rows_for(db_session, workout.id) == []


# --------------------------------------------------------------------------
# The backfill command
# --------------------------------------------------------------------------


def test_the_backfill_matches_a_stored_sync_to_the_workout_it_made(
    signed_in, ingest_token, db_session, monkeypatch, capsys
):
    """Matched on the dedupe key the sync itself writes, which is the unique
    constraint on workouts, so a match is exact rather than approximate."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    forget_the_detail(db_session)

    backfill(db_session, monkeypatch)

    out = capsys.readouterr().out
    assert "workouts matched: 1" in out
    assert "samples written: 3" in out
    assert "workouts skipped as already detailed: 0" in out

    workout = the_one_workout(db_session)
    assert workout.elevation_gain_ft == 142.0
    assert workout.max_hr == 168
    assert workout.temperature_f == 78.5
    assert workout.humidity_pct == 44.0
    assert [row.steps for row in rows_for(db_session, workout.id)] == [110, 111, 112]


def test_the_backfill_run_twice_writes_nothing_the_second_time(
    signed_in, ingest_token, db_session, monkeypatch, capsys
):
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    forget_the_detail(db_session)

    backfill(db_session, monkeypatch)
    capsys.readouterr()
    backfill(db_session, monkeypatch)

    second = capsys.readouterr().out
    assert "workouts matched: 1" in second
    assert "samples written: 0" in second
    assert "workouts skipped as already detailed: 1" in second
    assert len(rows_for(db_session, the_one_workout(db_session).id)) == 3


def test_the_backfill_leaves_a_summary_that_is_already_answered_alone(
    signed_in, ingest_token, db_session, monkeypatch
):
    """Only what is missing is filled, so a number already on a row is never
    written over by a replay of the payload it came from."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    forget_the_detail(db_session)
    workout = the_one_workout(db_session)
    workout.elevation_gain_ft = 9.0
    db_session.commit()

    backfill(db_session, monkeypatch)

    workout = the_one_workout(db_session)
    assert workout.elevation_gain_ft == 9.0
    assert workout.max_hr == 168


def test_the_backfill_reads_every_account_and_matches_nobody_elses_workout(
    signed_in, ingest_token, db_session, member, monkeypatch, capsys
):
    """Run by hand over the whole instance, so the account is part of the key:
    two people out at the same moment for the same length of time is a
    coincidence, not one workout."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    stranger = make_user(db_session, "stranger", "stranger-password-1")
    db_session.add(
        models.Workout(
            user_id=stranger.id,
            activity="walk",
            start_ts=dt.datetime.fromisoformat(START),
            duration_s=180,
            distance_mi=0.15,
            active_kcal=30.0,
            source="sync",
            flags={},
            created_at=security.now_utc(),
        )
    )
    db_session.commit()
    forget_the_detail(db_session)

    backfill(db_session, monkeypatch)

    assert "workouts matched: 1" in capsys.readouterr().out
    theirs = (
        db_session.query(models.Workout).filter(models.Workout.user_id == stranger.id).one()
    )
    assert theirs.elevation_gain_ft is None
    assert rows_for(db_session, theirs.id) == []


# --------------------------------------------------------------------------
# Who gets to see the climb
# --------------------------------------------------------------------------


def test_a_friend_who_hides_their_route_hides_the_climb_with_it(
    signed_in, ingest_token, db_session, member
):
    """The frozen rule: how much a session climbed is read off the ground it
    crossed, so it travels under the permission the line itself travels under.
    Read as text, because a field dropped from the row but still carried under
    another name would pass a check of the keys."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)

    seen = other_client.get("/api/feed")
    assert seen.json()[0]["elevation_gain_ft"] == 142.0

    hide(signed_in, "route")
    kept_back = other_client.get("/api/feed")
    assert "elevation_gain_ft" not in kept_back.json()[0]
    assert "142.0" not in kept_back.text


def test_your_own_row_carries_the_climb_whatever_you_have_hidden(
    signed_in, ingest_token, db_session
):
    """Hiding something from your friends is not hiding it from yourself."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    hide(signed_in, "avg_hr", "route")

    assert signed_in.get("/api/feed").json()[0]["elevation_gain_ft"] == 142.0
    assert signed_in.get("/api/workouts").json()[0]["elevation_gain_ft"] == 142.0


def test_a_row_whose_export_never_mentioned_climbing_carries_null(
    signed_in, ingest_token, db_session
):
    """Null rather than absent, which is the same distinction the heart rate
    makes: nothing was recorded is a different thing from being asked not to
    look, and the card draws no chip either way."""
    plain = {"name": "Indoor Walk", "start": START, "duration": 1800}
    assert post(signed_in, ingest_token, export(plain)).json()["imported"] == 1

    row = signed_in.get("/api/feed").json()[0]
    assert row["indoor"] is True
    assert row["elevation_gain_ft"] is None


# --------------------------------------------------------------------------
# What a deletion takes with it
# --------------------------------------------------------------------------


def test_the_purge_takes_the_minutes_off_a_long_deleted_workout(
    signed_in, ingest_token, db_session, member
):
    """A delete is a run taken back, and these rows are the largest thing the
    session leaves behind, so they go with the pictures and the words at the end
    of the window. This workout was never titled or photographed, which means
    the minutes are the whole of what it has left: the sweep's own guard has to
    count them or a synced walk that nobody wrote on is passed over forever."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    workout = the_one_workout(db_session)
    assert len(rows_for(db_session, workout.id)) == 3

    assert signed_in.delete(f"/api/workouts/{workout.id}").status_code == 204
    deleted_days_ago(db_session, workout, config.DELETED_WORKOUT_RETENTION_DAYS + 1)

    # Selected at all, which is the guard: nothing but the minutes is on it.
    assert history.purge_expired(db_session, member.id) == 1
    db_session.commit()

    assert rows_for(db_session, workout.id) == []
    assert db_session.query(models.WorkoutSample).count() == 0
    # The tombstone is still there holding its dedupe key, and a second sweep
    # finds nothing left to take off it.
    db_session.expire_all()
    assert db_session.get(models.Workout, workout.id) is not None
    assert history.purge_expired(db_session, member.id) == 0
