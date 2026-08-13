"""The sync endpoint: parsing, units, idempotency, flags, and its auth."""

import argparse
import datetime as dt

from app import config, models, security
from app.activity import classify, is_indoor, parse_start, to_kcal, to_miles, without_routes
from conftest import make_user
# The same synthetic trace the route cases are built from, rather than a second
# generator here that could drift from it.
from test_routemaps import line


def export(*workouts) -> dict:
    """A payload in the shape the phone's export tool actually posts."""
    return {"data": {"workouts": list(workouts)}}


def workout(name, start, duration, miles=None, kcal=None, hr=None) -> dict:
    entry = {"name": name, "start": start, "duration": duration}
    if miles is not None:
        entry["distance"] = {"qty": miles, "units": "mi"}
    if kcal is not None:
        entry["activeEnergyBurned"] = {"qty": kcal, "units": "kcal"}
    if hr is not None:
        entry["avgHeartRate"] = {"qty": hr, "units": "count/min"}
    return entry


def post(client, token, payload):
    return client.post("/api/ingest", json=payload, headers={"Authorization": f"Bearer {token}"})


def test_all_four_activities_import(signed_in, ingest_token, db_session):
    payload = export(
        workout("Outdoor Walk", "2026-07-20T06:12:00-07:00", 2400.0, 2.1, 190, 104),
        workout("Running", "2026-07-20 07:30:00 -0700", 1800.5, 3.0, 350, 155),
        workout("Indoor Cycle", "2026-07-20T18:00:00-07:00", 2700, 9.5, 400, 128),
        workout("Pool Swim", "2026-07-21T06:00:00-07:00", 1500, 0.6, 240, 130),
    )
    response = post(signed_in, ingest_token, payload)
    assert response.status_code == 200
    assert response.json() == {"imported": 4, "skipped": 0, "flagged": 0, "ignored": 0}

    stored = {row.activity for row in db_session.query(models.Workout)}
    assert stored == {"walk", "run", "cycle", "swim"}


def test_unsupported_types_are_ignored_but_logged(signed_in, ingest_token, db_session):
    payload = export(
        workout("Outdoor Walk", "2026-07-20T06:12:00-07:00", 2400, 2.1, 190),
        workout("Traditional Strength Training", "2026-07-20T09:00:00-07:00", 1800, None, 220),
        workout("Outdoor Walk", "not a timestamp at all", 2400, 2.1, 190),
    )
    response = post(signed_in, ingest_token, payload)
    assert response.json() == {"imported": 1, "skipped": 0, "flagged": 0, "ignored": 2}

    logged = db_session.query(models.IngestLog).one()
    reasons = {item["reason"] for item in logged.result["ignored_detail"]}
    assert reasons == {"unsupported activity", "unreadable start time"}
    # The raw payload is kept exactly as it arrived, so a parsing fix can be
    # replayed over history rather than losing it.
    assert logged.payload == payload


def test_missing_distance_or_energy_still_imports(signed_in, ingest_token, db_session):
    payload = export(
        {"name": "Pool Swim", "start": "2026-07-22T06:00:00+00:00", "duration": 1800},
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1
    row = db_session.query(models.Workout).one()
    assert row.distance_mi == 0.0
    assert row.active_kcal == 0.0
    assert row.avg_hr is None


def test_units_are_normalised(signed_in, ingest_token, db_session):
    payload = export(
        {
            "name": "Outdoor Run",
            "start": "2026-07-22T06:00:00+00:00",
            "duration": 3600,
            "distance": {"qty": 10.0, "units": "km"},
            "activeEnergyBurned": {"qty": 2092.0, "units": "kJ"},
        }
    )
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1
    row = db_session.query(models.Workout).one()
    assert round(row.distance_mi, 3) == 6.214
    assert round(row.active_kcal, 1) == 500.0


def test_conversion_helpers():
    assert to_miles({"qty": 1.0, "units": "mi"}) == 1.0
    assert round(to_miles({"qty": 5.0, "units": "km"}), 4) == 3.1069
    assert round(to_miles({"qty": 1600.0, "units": "m"}), 3) == 0.994
    assert to_miles(None) == 0.0
    assert to_miles({"qty": -3.0, "units": "mi"}) == 0.0
    assert to_kcal({"qty": 100.0, "units": "kcal"}) == 100.0
    assert round(to_kcal({"qty": 418.4, "units": "kJ"}), 1) == 100.0
    # A bare number with no units keeps the unit the rest of the app assumes.
    assert to_kcal(220) == 220.0


def test_activity_name_matching_is_contains_based():
    assert classify("Outdoor Walk") == "walk"
    assert classify("INDOOR WALK") == "walk"
    assert classify("Trail Running") == "run"
    assert classify("Indoor Cycle") == "cycle"
    assert classify("Cycling") == "cycle"
    assert classify("Pool Swim") == "swim"
    assert classify("Open Water Swimming") == "swim"
    assert classify("Traditional Strength Training") is None
    assert classify(None) is None


def test_the_indoor_reading_is_the_name_and_nothing_else():
    assert is_indoor("Indoor Run") is True
    assert is_indoor("INDOOR WALK") is True
    assert is_indoor("indoor treadmill run") is True
    assert is_indoor("Outdoor Walk") is False
    assert is_indoor("Running") is False
    # Nothing is inferred from anywhere else, so an unnamed session is outdoors.
    assert is_indoor(None) is False
    assert is_indoor("") is False


def test_an_indoor_name_is_stored_on_the_workout(signed_in, ingest_token, db_session):
    """Both halves of the name are read at once: the activity from its keyword
    and the indoor mark from its own, so an indoor walk is a walk that was
    indoors rather than a fifth activity."""
    payload = export(
        workout("Indoor Run", "2026-07-20T06:12:00-07:00", 1800, 3.0, 300),
        workout("Outdoor Walk", "2026-07-20T09:00:00-07:00", 2400, 2.1, 190),
    )
    assert post(signed_in, ingest_token, payload).status_code == 200
    stored = {
        row.activity: row.indoor
        for row in db_session.query(models.Workout).order_by(models.Workout.id)
    }
    assert stored == {"run": True, "walk": False}


def test_start_time_dialects():
    spaced = parse_start("2026-07-29 06:12:00 -0700")
    iso = parse_start("2026-07-29T06:12:00-07:00")
    assert spaced == iso
    # No offset at all means local time, not UTC.
    naive = parse_start("2026-07-29 06:12:00")
    assert naive is not None and naive.tzinfo is not None
    assert parse_start("last tuesday") is None
    assert parse_start(None) is None


def test_the_same_export_twice_imports_nothing_new(signed_in, ingest_token, db_session):
    payload = export(
        workout("Outdoor Walk", "2026-07-20T06:12:00-07:00", 2400, 2.1, 190),
        workout("Running", "2026-07-20T07:30:00-07:00", 1800, 3.0, 350),
    )
    first = post(signed_in, ingest_token, payload)
    assert first.json()["imported"] == 2

    second = post(signed_in, ingest_token, payload)
    assert second.json() == {"imported": 0, "skipped": 2, "flagged": 0, "ignored": 0}
    assert db_session.query(models.Workout).count() == 2


def test_overlapping_windows_credit_only_what_is_new(signed_in, ingest_token, db_session):
    monday = workout("Outdoor Walk", "2026-07-20T06:12:00-07:00", 2400, 2.1, 190)
    tuesday = workout("Outdoor Walk", "2026-07-21T06:12:00-07:00", 2500, 2.2, 195)
    wednesday = workout("Outdoor Walk", "2026-07-22T06:12:00-07:00", 2600, 2.3, 200)

    assert post(signed_in, ingest_token, export(monday, tuesday)).json()["imported"] == 2
    # The next export covers Tuesday again, which is what a daily automation
    # with a two-day window really does.
    second = post(signed_in, ingest_token, export(tuesday, wednesday))
    assert second.json() == {"imported": 1, "skipped": 1, "flagged": 0, "ignored": 0}
    assert db_session.query(models.Workout).count() == 3


def test_same_start_different_duration_is_a_different_workout(signed_in, ingest_token, db_session):
    start = "2026-07-20T06:12:00-07:00"
    post(signed_in, ingest_token, export(workout("Outdoor Walk", start, 2400, 2.1, 190)))
    second = post(signed_in, ingest_token, export(workout("Outdoor Walk", start, 2401, 2.1, 190)))
    assert second.json()["imported"] == 1
    assert db_session.query(models.Workout).count() == 2


def test_impossible_pace_is_flagged_not_rejected(signed_in, ingest_token, db_session):
    # Four miles in eleven minutes.
    payload = export(workout("Outdoor Run", "2026-07-20T06:12:00-07:00", 660, 4.0, 400))
    response = post(signed_in, ingest_token, payload)
    assert response.json() == {"imported": 1, "skipped": 0, "flagged": 1, "ignored": 0}
    assert db_session.query(models.Workout).one().flags == {"impossible_pace": True}


def test_plausible_pace_is_not_flagged(signed_in, ingest_token, db_session):
    payload = export(
        workout("Outdoor Run", "2026-07-20T06:12:00-07:00", 1800, 3.0, 350),
        workout("Indoor Cycle", "2026-07-20T09:00:00-07:00", 3600, 18.0, 500),
        workout("Pool Swim", "2026-07-20T12:00:00-07:00", 3600, 1.5, 400),
    )
    assert post(signed_in, ingest_token, payload).json()["flagged"] == 0


def test_cycling_speed_threshold(signed_in, ingest_token, db_session):
    # Forty miles in an hour is past the thirty mile an hour ceiling.
    payload = export(workout("Outdoor Cycle", "2026-07-20T06:12:00-07:00", 3600, 40.0, 900))
    assert post(signed_in, ingest_token, payload).json()["flagged"] == 1
    assert db_session.query(models.Workout).one().flags == {"impossible_pace": True}


def test_daily_cap_flag(signed_in, ingest_token, db_session):
    # Three walks on one local day, adding to more than the forty mile cap.
    payload = export(
        workout("Outdoor Walk", "2026-07-20T06:00:00+00:00", 6 * 3600, 18.0, 1800),
        workout("Outdoor Walk", "2026-07-20T14:00:00+00:00", 6 * 3600, 18.0, 1800),
        workout("Outdoor Walk", "2026-07-20T21:00:00+00:00", 2 * 3600, 6.0, 600),
    )
    response = post(signed_in, ingest_token, payload)
    assert response.json()["imported"] == 3
    # Only the workout that crossed the line carries the flag.
    flagged = [row for row in db_session.query(models.Workout) if row.flags.get("daily_cap")]
    assert len(flagged) == 1
    assert flagged[0].distance_mi == 6.0


def test_daily_cap_does_not_leak_across_days(signed_in, ingest_token, db_session):
    payload = export(
        workout("Outdoor Walk", "2026-07-20T06:00:00+00:00", 8 * 3600, 25.0, 2500),
        workout("Outdoor Walk", "2026-07-21T06:00:00+00:00", 8 * 3600, 25.0, 2500),
    )
    assert post(signed_in, ingest_token, payload).json()["flagged"] == 0


def test_daily_cap_does_not_leak_across_users(client, db_session, admin, ingest_token, signed_in):
    """One user's mileage must never flag another user's workout."""
    from conftest import ADMIN

    payload = export(workout("Outdoor Walk", "2026-07-20T06:00:00+00:00", 12 * 3600, 39.0, 3000))
    assert post(signed_in, ingest_token, payload).json()["flagged"] == 0

    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    admin_token = signed_in.post("/api/settings/ingest-token/rotate").json()["token"]
    second = post(signed_in, admin_token, payload)
    assert second.json() == {"imported": 1, "skipped": 0, "flagged": 0, "ignored": 0}


def test_ingest_rejects_missing_and_bad_tokens(client, ingest_token):
    payload = export(workout("Outdoor Walk", "2026-07-20T06:12:00-07:00", 2400, 2.1, 190))
    assert client.post("/api/ingest", json=payload).status_code == 401
    assert (
        client.post(
            "/api/ingest", json=payload, headers={"Authorization": "Bearer wrong-token"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/ingest", json=payload, headers={"Authorization": ingest_token}
        ).status_code
        == 401
    )


def test_a_session_cookie_is_not_an_ingest_token(signed_in):
    payload = export(workout("Outdoor Walk", "2026-07-20T06:12:00-07:00", 2400, 2.1, 190))
    assert signed_in.post("/api/ingest", json=payload).status_code == 401


def test_rotating_the_token_revokes_the_old_one(signed_in, ingest_token):
    payload = export(workout("Outdoor Walk", "2026-07-20T06:12:00-07:00", 2400, 2.1, 190))
    fresh = signed_in.post("/api/settings/ingest-token/rotate").json()["token"]
    assert fresh != ingest_token
    assert post(signed_in, ingest_token, payload).status_code == 401
    assert post(signed_in, fresh, payload).status_code == 200


def test_body_must_be_json(signed_in, ingest_token):
    response = signed_in.post(
        "/api/ingest",
        content=b"not json",
        headers={"Authorization": f"Bearer {ingest_token}", "Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_payload_without_a_workouts_list_is_logged(signed_in, ingest_token, db_session):
    response = post(signed_in, ingest_token, {"data": {}})
    assert response.json() == {"imported": 0, "skipped": 0, "flagged": 0, "ignored": 1}
    assert db_session.query(models.IngestLog).count() == 1


def test_ingest_burst_is_rate_limited(signed_in, ingest_token):
    payload = export()
    codes = []
    for _ in range(61):
        codes.append(post(signed_in, ingest_token, payload).status_code)
    assert codes.count(200) == 60
    assert codes[-1] == 429


def test_a_value_that_is_not_a_number_is_ignored_not_stored(
    signed_in, ingest_token, db_session
):
    """One broken entry must not become a row, and must not cost the rest.

    A stored NaN or infinity is not a cosmetic problem: the progress pipeline
    reads every workout an account owns on every request, so one of them turns
    every later request for that account into a 500 that no retry clears.
    """
    # Sent as text: the JSON encoder refuses to write a number this large, and
    # the parser reads it back as infinity without complaint.
    body = (
        '{"data": {"workouts": ['
        '{"name": "Outdoor Walk", "start": "2026-07-20T06:00:00+00:00", "duration": 2400,'
        ' "distance": {"qty": 2.1, "units": "mi"}},'
        # A string the export tool wrote for a reading it did not have.
        '{"name": "Outdoor Run", "start": "2026-07-20T07:00:00+00:00", "duration": 1800,'
        ' "distance": {"qty": "NaN", "units": "mi"}},'
        # A JSON number too large for a float, which parses to infinity.
        '{"name": "Indoor Cycle", "start": "2026-07-20T08:00:00+00:00", "duration": 1800,'
        ' "activeEnergyBurned": {"qty": 1e400, "units": "kcal"}}'
        "]}}"
    )
    response = signed_in.post(
        "/api/ingest",
        content=body.encode(),
        headers={
            "Authorization": f"Bearer {ingest_token}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    # The good entry still lands: one bad number never poisons the batch.
    assert response.json() == {"imported": 1, "skipped": 0, "flagged": 0, "ignored": 2}
    assert db_session.query(models.Workout).count() == 1

    logged = db_session.query(models.IngestLog).one()
    assert [item["reason"] for item in logged.result["ignored_detail"]] == [
        "value is not a number",
        "value is not a number",
    ]


def test_absurd_numbers_are_ignored_with_a_reason(signed_in, ingest_token, db_session):
    payload = export(
        workout("Outdoor Walk", "2026-07-20T06:00:00+00:00", 2400, 2.1, 190),
        workout("Outdoor Run", "2026-07-20T07:00:00+00:00", 1800, 5000.0, 300),
        workout("Indoor Cycle", "2026-07-20T08:00:00+00:00", 400000, 10.0, 300),
        workout("Pool Swim", "2026-07-20T09:00:00+00:00", 1800, 0.5, 900000),
    )
    response = post(signed_in, ingest_token, payload)
    assert response.json() == {"imported": 1, "skipped": 0, "flagged": 0, "ignored": 3}
    assert db_session.query(models.Workout).count() == 1

    logged = db_session.query(models.IngestLog).one()
    reasons = {item["reason"] for item in logged.result["ignored_detail"]}
    assert reasons == {"numbers out of range"}


def test_an_impossible_heart_rate_is_dropped_but_the_workout_stays(
    signed_in, ingest_token, db_session
):
    payload = export(workout("Outdoor Walk", "2026-07-20T06:00:00+00:00", 2400, 2.1, 190, 9000))
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1
    # Nothing is scored from a heart rate, so a reading no heart produces goes
    # on its own rather than taking a real session with it.
    assert db_session.query(models.Workout).one().avg_hr is None


def test_a_literal_nan_in_the_body_is_a_bad_request(signed_in, ingest_token, db_session):
    """Python's JSON parser accepts NaN as a bare literal; this endpoint does not.

    Refused at the door rather than at the database, where it would arrive as a
    500 from the payload column the log writes it to.
    """
    body = (
        b'{"data": {"workouts": [{"name": "Outdoor Walk", '
        b'"start": "2026-07-20T06:00:00+00:00", "duration": NaN}]}}'
    )
    response = signed_in.post(
        "/api/ingest",
        content=body,
        headers={
            "Authorization": f"Bearer {ingest_token}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Body must be JSON."}
    assert db_session.query(models.Workout).count() == 0


def test_a_literal_infinity_in_the_body_is_a_bad_request(signed_in, ingest_token):
    body = (
        b'{"data": {"workouts": [{"name": "Outdoor Walk", '
        b'"start": "2026-07-20T06:00:00+00:00", "duration": 1800, '
        b'"distance": {"qty": -Infinity, "units": "mi"}}]}}'
    )
    response = signed_in.post(
        "/api/ingest",
        content=body,
        headers={
            "Authorization": f"Bearer {ingest_token}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400


def test_an_export_with_too_many_entries_is_refused(signed_in, ingest_token, db_session):
    entry = workout("Outdoor Walk", "2026-07-20T06:00:00+00:00", 2400, 2.1, 190)
    payload = export(*[dict(entry) for _ in range(config.MAX_INGEST_WORKOUTS + 1)])
    response = post(signed_in, ingest_token, payload)
    assert response.status_code == 400
    assert response.json() == {"detail": "Too many workouts in one export."}
    # Refused before any row work, so nothing was written and nothing logged.
    assert db_session.query(models.Workout).count() == 0
    assert db_session.query(models.IngestLog).count() == 0


def test_an_export_well_under_the_entry_limit_is_untouched(signed_in, ingest_token):
    entries = [
        workout("Outdoor Walk", f"2026-07-20T06:00:{second:02d}+00:00", 2400, 2.1, 190)
        for second in range(10)
    ]
    payload = export(*entries)
    assert post(signed_in, ingest_token, payload).json()["imported"] == 10


def test_workout_stored_in_utc(signed_in, ingest_token, db_session):
    payload = export(workout("Outdoor Walk", "2026-07-20 06:12:00 -0700", 2400, 2.1, 190))
    post(signed_in, ingest_token, payload)
    row = db_session.query(models.Workout).one()
    assert row.start_ts == dt.datetime(2026, 7, 20, 13, 12, tzinfo=dt.timezone.utc)


# --------------------------------------------------------------------------
# What the log keeps, and for how long
# --------------------------------------------------------------------------


def stored_log(db_session, user_id: int, *, days_ago: int, route=None) -> models.IngestLog:
    """One stored sync, dated by hand and optionally carrying a trace.

    The suite's clock is frozen, so a row that has to be old says how old it is
    rather than waiting to become it. The route argument is how a payload from
    before the strip existed is written, which is the only kind the cleanup
    command has anything to do.
    """
    entry = workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, 300, 150)
    if route is not None:
        entry["route"] = route
    row = models.IngestLog(
        user_id=user_id,
        received_at=security.now_utc() - dt.timedelta(days=days_ago),
        payload=export(entry),
        result={"imported": 1, "skipped": 0, "flagged": 0, "ignored": 0},
    )
    db_session.add(row)
    db_session.commit()
    return row


def entries_of(log: models.IngestLog) -> list[dict]:
    return log.payload["data"]["workouts"]


def test_the_stored_payload_keeps_no_gps_trace(signed_in, ingest_token, db_session):
    """The route is read, drawn, counted, and then not kept in the log.

    The trace is the one part of an export that says where its owner lives, and
    the stored line has both its ends trimmed off; keeping the raw one in a
    table nothing reads would give that away for nothing.
    """
    entry = workout("Outdoor Run", "2026-07-20T06:12:00+00:00", 1800, 3.0, 300, 150)
    entry["route"] = line(60)
    assert post(signed_in, ingest_token, export(entry)).json()["imported"] == 1

    logged = db_session.query(models.IngestLog).one()
    stored_entry = entries_of(logged)[0]
    assert "route" not in stored_entry
    # Everything else the entry arrived with is still there to replay.
    assert stored_entry == {
        "name": "Outdoor Run",
        "start": "2026-07-20T06:12:00+00:00",
        "duration": 1800,
        "distance": {"qty": 3.0, "units": "mi"},
        "activeEnergyBurned": {"qty": 300, "units": "kcal"},
        "avgHeartRate": {"qty": 150, "units": "count/min"},
    }
    # The line itself survives where it belongs, and the log counted it.
    assert len(db_session.query(models.WorkoutRoute).one().points) >= 10
    assert logged.result["routes_stored"] == 1


def test_the_strip_finds_the_list_wherever_the_export_put_it():
    """Both shapes workout_entries accepts, since the list has to go back where
    it was found or the next reader sees the untouched copy."""
    entry = {"name": "Outdoor Run", "route": line(4), "duration": 60}
    nested = without_routes({"data": {"workouts": [entry]}, "metrics": []})
    assert nested == {"data": {"workouts": [{"name": "Outdoor Run", "duration": 60}]}, "metrics": []}

    flat = without_routes({"workouts": [entry]})
    assert flat == {"workouts": [{"name": "Outdoor Run", "duration": 60}]}

    # A payload with nothing to take out comes back as itself, which is what
    # makes a second pass over an already-stripped row free.
    already = {"data": {"workouts": [{"name": "Outdoor Run"}]}}
    assert without_routes(already) is already
    assert without_routes({"nothing": "here"}) == {"nothing": "here"}


def test_a_payload_that_carried_no_trace_is_stored_untouched(signed_in, ingest_token, db_session):
    payload = export(workout("Outdoor Walk", "2026-07-20T06:12:00+00:00", 2400, 2.1, 190))
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1
    assert db_session.query(models.IngestLog).one().payload == payload


def test_a_sync_drops_this_account_s_expired_log_rows(signed_in, ingest_token, db_session, member):
    """Bounded by the syncs themselves, so nothing has to be scheduled."""
    stored_log(db_session, member.id, days_ago=config.INGEST_LOG_RETENTION_DAYS + 1)
    recent = stored_log(db_session, member.id, days_ago=config.INGEST_LOG_RETENTION_DAYS - 1)

    payload = export(workout("Outdoor Walk", "2026-07-21T06:12:00+00:00", 2400, 2.1, 190))
    assert post(signed_in, ingest_token, payload).status_code == 200

    # Read by arrival rather than by id: sqlite hands a deleted row's rowid to
    # the next insert, so an id proves nothing about which row this is.
    stamps = {row.received_at for row in db_session.query(models.IngestLog)}
    # The one just past the line is gone, the one just inside it stayed, and
    # the sync that did the pruning is in the log itself.
    assert stamps == {recent.received_at, security.now_utc()}


def test_the_prune_leaves_other_accounts_alone(signed_in, ingest_token, db_session, member):
    """Per user, so an account that never syncs again does not have its history
    cleaned out by somebody else's phone, and never waits on one either."""
    stranger = make_user(db_session, "stranger", "stranger-password-1")
    theirs = stored_log(db_session, stranger.id, days_ago=config.INGEST_LOG_RETENTION_DAYS + 30)
    stored_log(db_session, member.id, days_ago=config.INGEST_LOG_RETENTION_DAYS + 30)

    payload = export(workout("Outdoor Walk", "2026-07-21T06:12:00+00:00", 2400, 2.1, 190))
    assert post(signed_in, ingest_token, payload).status_code == 200

    def stamps(user_id):
        rows = db_session.query(models.IngestLog).filter(models.IngestLog.user_id == user_id)
        return {row.received_at for row in rows}

    # The stranger's row is as old as the one that just went and is untouched.
    assert stamps(stranger.id) == {theirs.received_at}
    assert stamps(member.id) == {security.now_utc()}


def test_the_letter_still_says_when_the_phone_last_synced_after_a_prune(
    signed_in, ingest_token, db_session, member
):
    """The log's only reader is that line, so the prune has to leave it right."""
    stored_log(db_session, member.id, days_ago=config.INGEST_LOG_RETENTION_DAYS + 5)

    payload = export(workout("Outdoor Walk", "2026-07-21T06:12:00+00:00", 2400, 2.1, 190))
    assert post(signed_in, ingest_token, payload).status_code == 200

    newest = db_session.query(models.IngestLog).one()
    assert signed_in.get("/api/recap").json()["last_sync_at"] == newest.received_at.isoformat()


def strip_ingest_log(db_session, monkeypatch) -> None:
    import manage

    monkeypatch.setattr(manage, "_session", lambda: db_session)
    manage.cmd_strip_ingest_log(argparse.Namespace())


def test_the_cleanup_command_strips_traces_and_prunes(db_session, member, monkeypatch, capsys):
    """The one-time pass over rows written before the endpoint did either."""
    stranger = make_user(db_session, "stranger", "stranger-password-1")
    stored_log(
        db_session, member.id, days_ago=config.INGEST_LOG_RETENTION_DAYS + 1, route=line(60)
    )
    mine = stored_log(db_session, member.id, days_ago=3, route=line(60))
    # Every account, unlike the at-ingest prune: this is run once by hand.
    theirs = stored_log(db_session, stranger.id, days_ago=2, route=line(60))

    strip_ingest_log(db_session, monkeypatch)

    out = capsys.readouterr().out
    assert "rows stripped of routes: 2" in out
    assert f"rows deleted as older than {config.INGEST_LOG_RETENTION_DAYS} days: 1" in out
    assert "rows kept: 2" in out

    # Nothing is inserted here, so ids still name the rows they were given.
    kept = {row.id: row for row in db_session.query(models.IngestLog)}
    assert set(kept) == {mine.id, theirs.id}
    for row in kept.values():
        assert "route" not in entries_of(row)[0]
        # The rest of the entry is untouched, so it can still be replayed.
        assert entries_of(row)[0]["distance"] == {"qty": 3.0, "units": "mi"}


def test_the_cleanup_command_run_twice_reports_zeros(db_session, member, monkeypatch, capsys):
    stored_log(db_session, member.id, days_ago=config.INGEST_LOG_RETENTION_DAYS + 1, route=line(60))
    stored_log(db_session, member.id, days_ago=3, route=line(60))

    strip_ingest_log(db_session, monkeypatch)
    first = capsys.readouterr().out
    assert "rows stripped of routes: 1" in first

    strip_ingest_log(db_session, monkeypatch)
    second = capsys.readouterr().out
    assert "rows stripped of routes: 0" in second
    assert f"rows deleted as older than {config.INGEST_LOG_RETENTION_DAYS} days: 0" in second
    assert "rows kept: 1" in second


# --------------------------------------------------------------------------
# The backfill window
# --------------------------------------------------------------------------


def stamped(days_before_signup: int) -> str:
    """A start that many days before the account in the fixtures was created."""
    return (
        security.now_utc() - dt.timedelta(days=days_before_signup)
    ).isoformat().replace("+00:00", "Z")


def test_a_workout_from_inside_the_window_imports_and_an_older_one_does_not(
    signed_in, ingest_token, db_session, member
):
    """Fourteen days before the account existed is the line. A day inside it is
    a workout; a day outside it is refused and counted, because an export
    reaching back years is what a first sync looks like and not an error."""
    payload = export(
        workout("Outdoor Run", stamped(13), 1800, 3.0, 300),
        workout("Outdoor Run", stamped(15), 1800, 4.0, 400),
    )
    response = post(signed_in, ingest_token, payload)
    assert response.status_code == 200
    assert response.json() == {"imported": 1, "skipped": 0, "flagged": 0, "ignored": 1}

    assert [row.distance_mi for row in db_session.query(models.Workout)] == [3.0]
    logged = db_session.query(models.IngestLog).one()
    assert [item["reason"] for item in logged.result["ignored_detail"]] == [
        "before this account's backfill window"
    ]


def test_the_window_is_anchored_to_the_account_and_never_to_today(
    signed_in, ingest_token, db_session, member
):
    """Anchored to the signup, so an account that has been here a while syncs
    its whole history and a gap after joining loses nothing. A rolling fortnight
    would refuse this one."""
    member.created_at = security.now_utc() - dt.timedelta(days=100)
    db_session.commit()

    payload = export(workout("Outdoor Run", stamped(90), 1800, 5.0, 500))
    assert post(signed_in, ingest_token, payload).json()["imported"] == 1


def test_a_day_of_steps_older_than_the_window_is_refused_too(
    signed_in, ingest_token, db_session, member
):
    """The same rule one metric across, and counted the same way: the day is
    dropped and nothing is stored for it."""
    from test_steps import reading, sync

    old_day = (security.now_utc() - dt.timedelta(days=15)).date()
    response = sync(signed_in, ingest_token, metrics=reading(old_day, steps=9000, miles=4.0))
    assert response.status_code == 200
    # One refusal, because the metrics are read into one reading per day and the
    # day is what is refused.
    assert response.json()["ignored"] == 1
    assert db_session.query(models.DailySteps).count() == 0


def test_the_window_reconsiders_nothing_already_stored(
    signed_in, ingest_token, db_session, member
):
    """It decides what an export may offer, never what the history holds: a row
    written before the rule existed stays exactly where it is."""
    old = models.Workout(
        user_id=member.id,
        activity="run",
        start_ts=security.now_utc() - dt.timedelta(days=400),
        duration_s=1800,
        distance_mi=6.0,
        active_kcal=600.0,
        avg_hr=None,
        source="sync",
        flags={},
        created_at=security.now_utc() - dt.timedelta(days=400),
    )
    db_session.add(old)
    db_session.commit()

    post(signed_in, ingest_token, export(workout("Outdoor Run", stamped(1), 1800, 3.0, 300)))
    db_session.expire_all()
    assert db_session.get(models.Workout, old.id).distance_mi == 6.0
