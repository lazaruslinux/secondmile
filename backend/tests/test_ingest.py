"""The sync endpoint: parsing, units, idempotency, flags, and its auth."""

import datetime as dt

from app import config, models
from app.activity import classify, parse_start, to_kcal, to_miles


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
