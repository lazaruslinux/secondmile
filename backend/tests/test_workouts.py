"""Manual entry, the history page, and the weekly totals."""

import datetime as dt

from app import models
from app.activity import converted_miles


def manual(activity="run", start="2026-07-20T06:12:00+00:00", duration=1800, miles=3.0, **extra):
    body = {
        "activity": activity,
        "start_ts": start,
        "duration_s": duration,
        "distance_mi": miles,
    }
    body.update(extra)
    return body


def test_manual_entry_is_marked_manual(signed_in, db_session):
    response = signed_in.post("/api/workouts", json=manual(active_kcal=320, avg_hr=148))
    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "manual"
    assert body["activity"] == "run"
    assert body["distance_mi"] == 3.0
    assert body["active_kcal"] == 320.0
    assert body["flags"] == {}
    assert db_session.query(models.Workout).one().source == "manual"


def test_manual_entry_duplicate_is_a_conflict(signed_in, db_session):
    assert signed_in.post("/api/workouts", json=manual()).status_code == 201
    # Same start and duration, so the same workout by the dedupe key even
    # though the distance differs.
    second = signed_in.post("/api/workouts", json=manual(miles=3.5))
    assert second.status_code == 409
    assert db_session.query(models.Workout).count() == 1


def test_manual_entry_collides_with_a_synced_workout(signed_in, ingest_token, db_session):
    payload = {
        "data": {
            "workouts": [
                {
                    "name": "Outdoor Run",
                    "start": "2026-07-20T06:12:00+00:00",
                    "duration": 1800,
                    "distance": {"qty": 3.0, "units": "mi"},
                }
            ]
        }
    }
    signed_in.post(
        "/api/ingest", json=payload, headers={"Authorization": f"Bearer {ingest_token}"}
    )
    assert signed_in.post("/api/workouts", json=manual()).status_code == 409


def test_manual_entry_validates_its_input(signed_in):
    assert signed_in.post("/api/workouts", json=manual(activity="skateboard")).status_code == 400
    assert signed_in.post("/api/workouts", json=manual(duration=0)).status_code == 400
    assert signed_in.post("/api/workouts", json=manual(miles=-1)).status_code == 400


def raw_manual(client, **numbers):
    """Post a manual entry as text rather than through the JSON encoder.

    The encoder refuses to write a NaN, and Python's parser reads one back
    happily, which is exactly why the endpoint has to refuse them itself.
    """
    fields = {"duration_s": "1800", "distance_mi": "3.0"}
    fields.update(numbers)
    parts = ['"activity": "run"', '"start_ts": "2026-07-20T06:12:00+00:00"']
    parts += [f'"{key}": {value}' for key, value in fields.items()]
    return client.post(
        "/api/workouts",
        content=("{" + ", ".join(parts) + "}").encode(),
        headers={"Content-Type": "application/json"},
    )


def test_manual_entry_refuses_numbers_that_are_not_numbers(signed_in, db_session):
    """NaN and infinity are valid JSON literals and a float field takes both.

    A stored one is not a cosmetic problem: the progress pipeline reads every
    workout the account owns on every request, so one of them turns every later
    request for that account into a 500 that no retry clears.
    """
    for fields in (
        {"distance_mi": "NaN"},
        {"distance_mi": "Infinity"},
        {"active_kcal": "NaN"},
        {"avg_hr": "-Infinity"},
        {"duration_s": "NaN"},
        # A JSON number too large for a float parses to infinity on its own.
        {"distance_mi": "1e400"},
    ):
        response = raw_manual(signed_in, **fields)
        assert response.status_code == 400, response.text
        assert set(response.json()) == {"detail"}
    assert db_session.query(models.Workout).count() == 0
    # The account is still readable, which is the property all of this protects.
    assert signed_in.get("/api/profile").status_code == 200


def test_manual_entry_refuses_absurd_numbers(signed_in, db_session):
    over_bounds = (
        manual(miles=5000.0),
        manual(duration=400000),
        manual(active_kcal=900000.0),
        manual(avg_hr=9000.0),
        manual(avg_hr=2.0),
    )
    for body in over_bounds:
        response = signed_in.post("/api/workouts", json=body)
        assert response.status_code == 400, response.text
        # A plain sentence, not a field dump: the person typed something wrong
        # and has to be told what the rule is.
        assert response.json()["detail"][-1] == "."
    assert db_session.query(models.Workout).count() == 0


def test_manual_entry_takes_the_numbers_just_inside_the_bounds(signed_in):
    accepted = signed_in.post(
        "/api/workouts",
        json=manual(duration=48 * 3600, miles=1000.0, active_kcal=50000.0, avg_hr=300.0),
    )
    assert accepted.status_code == 201, accepted.text


def test_manual_entry_is_rate_limited(signed_in):
    codes = []
    for minute in range(31):
        codes.append(
            signed_in.post(
                "/api/workouts",
                json=manual(start=f"2026-07-20T06:{minute:02d}:00+00:00"),
            ).status_code
        )
    assert codes.count(201) == 30
    assert codes[-1] == 429


def test_manual_entry_flags_an_impossible_pace(signed_in):
    response = signed_in.post("/api/workouts", json=manual(duration=600, miles=4.0))
    assert response.status_code == 201
    assert response.json()["flags"] == {"impossible_pace": True}


def test_manual_entry_flags_the_daily_cap(signed_in):
    signed_in.post(
        "/api/workouts",
        json=manual(activity="walk", start="2026-07-20T06:00:00+00:00", duration=8 * 3600,
                    miles=30.0),
    )
    over = signed_in.post(
        "/api/workouts",
        json=manual(activity="walk", start="2026-07-20T16:00:00+00:00", duration=5 * 3600,
                    miles=15.0),
    )
    assert over.json()["flags"] == {"daily_cap": True}


def test_manual_entry_needs_a_session(client):
    assert client.post("/api/workouts", json=manual()).status_code == 401


def test_history_is_newest_first_and_pages(signed_in):
    for day in range(1, 6):
        signed_in.post("/api/workouts", json=manual(start=f"2026-07-0{day}T06:00:00+00:00"))

    page = signed_in.get("/api/workouts", params={"limit": 2}).json()
    assert isinstance(page, list)
    assert [row["start_ts"][:10] for row in page] == ["2026-07-05", "2026-07-04"]

    older = signed_in.get(
        "/api/workouts", params={"limit": 2, "before": page[-1]["start_ts"]}
    ).json()
    assert [row["start_ts"][:10] for row in older] == ["2026-07-03", "2026-07-02"]


def test_paging_survives_an_unencoded_offset(signed_in):
    """A client that drops the timestamp into the query string without encoding
    it gets the offset back as a space; the second page still has to work."""
    for day in range(1, 4):
        signed_in.post("/api/workouts", json=manual(start=f"2026-07-0{day}T06:00:00+00:00"))
    older = signed_in.get("/api/workouts?limit=2&before=2026-07-03T06:00:00+00:00").json()
    assert [row["start_ts"][:10] for row in older] == ["2026-07-02", "2026-07-01"]


def test_history_rejects_a_bad_cursor(signed_in):
    assert signed_in.get("/api/workouts?before=yesterday").status_code == 400


def test_history_is_per_user(signed_in, client, db_session, admin):
    from conftest import ADMIN

    signed_in.post("/api/workouts", json=manual())
    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    assert signed_in.get("/api/workouts").json() == []


def test_history_rows_carry_what_each_workout_was_worth(signed_in):
    """The row's xp is the converted distance the pipeline credited."""
    signed_in.post("/api/workouts", json=manual(duration=1800, miles=3.0))
    # Nine cycled miles are three Miles, so the same credit for a longer ride.
    signed_in.post(
        "/api/workouts",
        json=manual(activity="cycle", start="2026-07-21T06:12:00+00:00", duration=1800, miles=9.0),
    )
    rows = signed_in.get("/api/workouts").json()
    assert [row["xp"] for row in rows] == [3.0, 3.0]
    for row in rows:
        assert row["xp"] == converted_miles(row["activity"], row["distance_mi"])


def test_history_rows_name_the_race_badge_a_run_earned(signed_in):
    signed_in.post("/api/workouts", json=manual(duration=3300, miles=6.4))
    signed_in.post(
        "/api/workouts",
        json=manual(start="2026-07-21T06:12:00+00:00", duration=1800, miles=2.0),
    )
    rows = {row["distance_mi"]: row["race_badge"] for row in signed_in.get("/api/workouts").json()}
    assert rows[6.4] == "race_10k"
    assert rows[2.0] is None


def test_a_new_entry_reports_its_own_worth(signed_in):
    created = signed_in.post("/api/workouts", json=manual(duration=1800, miles=3.0))
    assert created.json()["xp"] == 3.0
    assert created.json()["race_badge"] is None


def test_history_needs_a_session(client):
    assert client.get("/api/workouts").status_code == 401


def _monday_of_this_week() -> dt.date:
    today = dt.datetime.now(dt.timezone.utc).date()
    return today - dt.timedelta(days=today.weekday())


def test_weekly_totals(signed_in):
    monday = _monday_of_this_week()
    signed_in.post(
        "/api/workouts",
        json=manual(
            activity="run",
            start=f"{monday.isoformat()}T06:00:00+00:00",
            duration=1800,
            miles=3.0,
            active_kcal=300,
        ),
    )
    signed_in.post(
        "/api/workouts",
        json=manual(
            activity="run",
            start=f"{(monday + dt.timedelta(days=1)).isoformat()}T06:00:00+00:00",
            duration=2400,
            miles=4.0,
            active_kcal=400,
        ),
    )
    signed_in.post(
        "/api/workouts",
        json=manual(
            activity="walk",
            start=f"{(monday + dt.timedelta(days=2)).isoformat()}T06:00:00+00:00",
            duration=2400,
            miles=2.0,
            active_kcal=150,
        ),
    )

    weeks = signed_in.get("/api/workouts/weeks?count=4").json()
    assert len(weeks) == 4
    assert weeks[0]["week_start"] == monday.isoformat()
    # Newest first.
    assert weeks[1]["week_start"] == (monday - dt.timedelta(weeks=1)).isoformat()

    current = weeks[0]["activities"]
    assert current["run"] == {"distance_mi": 7.0, "active_kcal": 700.0, "workouts": 2}
    assert current["walk"] == {"distance_mi": 2.0, "active_kcal": 150.0, "workouts": 1}
    # Activities with nothing in them are absent, not zero-filled.
    assert "cycle" not in current
    assert "swim" not in current
    assert weeks[0]["total_active_kcal"] == 850.0
    # A week with no movement is still listed, so rest is visible rather than
    # missing from the Almanac.
    assert weeks[1]["activities"] == {}
    assert weeks[1]["total_active_kcal"] == 0.0


def test_weekly_totals_ignore_older_weeks(signed_in):
    monday = _monday_of_this_week()
    long_ago = monday - dt.timedelta(weeks=6)
    signed_in.post(
        "/api/workouts",
        json=manual(start=f"{long_ago.isoformat()}T06:00:00+00:00", active_kcal=999),
    )
    weeks = signed_in.get("/api/workouts/weeks?count=2").json()
    assert len(weeks) == 2
    assert all(week["activities"] == {} for week in weeks)


def test_weekly_totals_reject_a_silly_count(signed_in):
    assert signed_in.get("/api/workouts/weeks?count=0").status_code == 400
    assert signed_in.get("/api/workouts/weeks?count=500").status_code == 400
