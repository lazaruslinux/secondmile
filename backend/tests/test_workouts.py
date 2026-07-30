"""Manual entry, the history page, and the weekly totals."""

import datetime as dt

from app import models


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
