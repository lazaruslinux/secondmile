"""Stored best efforts: written where the minutes are, read where the bests are.

The computation itself is covered where it has always been covered, by the
insights cases in test_workouts. What is held to here is the storage: that a
sync writes the rows, that a later backfill corrects them, that a workout the
minutes cannot answer for stores nothing rather than a wrong number, and that
the reader's answer is unchanged by any of it.

Nothing here asserts that deleting a workout takes its bests with it. The
foreign key says so and Postgres honours it, but the suite runs on SQLite with
foreign keys off, so a case for it would be asserting the engine rather than the
code. What this app actually does to a workout is set deleted_at on it, and that
the reader skips one is a case below.
"""

import datetime as dt

from app import bests, models
from test_ingest import export, post, workout


def minutes_of(distances: list[float]) -> list[tuple[int, float | None]]:
    return list(enumerate(distances))


def test_a_line_that_never_reaches_the_distance_stores_nothing(db_session, member):
    """Absence is the reader's signal to fall back, so it has to stay absent."""
    row = models.Workout(
        user_id=member.id,
        activity="run",
        start_ts=dt.datetime(2026, 4, 10, 6, tzinfo=dt.timezone.utc),
        duration_s=600,
        distance_mi=1.0,
        active_kcal=0.0,
        avg_hr=None,
        source="sync",
        flags={},
    )
    db_session.add(row)
    db_session.flush()

    assert bests.store(db_session, row.id, minutes_of([0.1] * 10)) == 0
    assert db_session.query(models.WorkoutBestEffort).count() == 0


def test_only_the_tiers_the_minutes_reach_are_stored(db_session, member):
    row = models.Workout(
        user_id=member.id,
        activity="run",
        start_ts=dt.datetime(2026, 4, 10, 6, tzinfo=dt.timezone.utc),
        duration_s=4800,
        distance_mi=8.0,
        active_kcal=0.0,
        avg_hr=None,
        source="sync",
        flags={},
    )
    db_session.add(row)
    db_session.flush()

    # Eighty minutes at a tenth of a mile each: eight miles, so a 5K and a 10K
    # fit inside it and a half marathon does not.
    bests.store(db_session, row.id, minutes_of([0.1] * 80))
    tiers = {r.tier for r in db_session.query(models.WorkoutBestEffort)}
    assert tiers == {"5k", "10k"}


def test_storing_again_replaces_what_was_there(db_session, member):
    """A workout whose detail is filled in later must not keep the thinner answer."""
    row = models.Workout(
        user_id=member.id,
        activity="run",
        start_ts=dt.datetime(2026, 4, 10, 6, tzinfo=dt.timezone.utc),
        duration_s=3000,
        distance_mi=5.0,
        active_kcal=0.0,
        avg_hr=None,
        source="sync",
        flags={},
    )
    db_session.add(row)
    db_session.flush()

    bests.store(db_session, row.id, minutes_of([0.1] * 50))
    slow = db_session.query(models.WorkoutBestEffort).one().seconds

    # The same ground covered in half the minutes.
    bests.store(db_session, row.id, minutes_of([0.2] * 25))
    rows = db_session.query(models.WorkoutBestEffort).all()
    assert len(rows) == 1
    assert rows[0].seconds < slow


def test_a_sync_writes_the_bests_with_the_minutes(signed_in, ingest_token, db_session):
    """The one funnel: minutes reaching the database is what writes these."""
    entry = workout("Outdoor Run", "2026-07-20T06:00:00+00:00", 3000, 5.0, 500, 150)
    entry["heartRateData"] = [
        {"date": f"2026-07-20T06:{m:02d}:00+00:00", "Avg": 150} for m in range(50)
    ]
    entry["walkingAndRunningDistance"] = [
        {"date": f"2026-07-20T06:{m:02d}:00+00:00", "qty": 0.1, "units": "mi"}
        for m in range(50)
    ]
    assert post(signed_in, ingest_token, export(entry)).json()["imported"] == 1

    stored = db_session.query(models.WorkoutBestEffort).all()
    assert {row.tier for row in stored} == {"5k"}
    assert stored[0].seconds > 0


def test_the_reader_leaves_out_another_account_and_a_deleted_session(
    db_session, member, admin
):
    """for_user answers for one account's living workouts and nothing else."""
    rows = []
    for owner, deleted in ((member, None), (member, dt.datetime.now(dt.timezone.utc)), (admin, None)):
        row = models.Workout(
            user_id=owner.id,
            activity="run",
            start_ts=dt.datetime(2026, 4, 10 + len(rows), 6, tzinfo=dt.timezone.utc),
            duration_s=3000,
            distance_mi=5.0,
            active_kcal=0.0,
            avg_hr=None,
            source="sync",
            flags={},
            deleted_at=deleted,
        )
        db_session.add(row)
        db_session.flush()
        bests.store(db_session, row.id, minutes_of([0.1] * 50))
        rows.append(row)
    db_session.commit()

    mine = bests.for_user(db_session, member.id)
    assert list(mine) == [(rows[0].id, "5k")]


def test_a_workout_keeps_its_bests_after_its_minutes_are_gone(db_session, member):
    """The answer was true when it was computed, and pruning must not slow a history."""
    row = models.Workout(
        user_id=member.id,
        activity="run",
        start_ts=dt.datetime(2026, 4, 10, 6, tzinfo=dt.timezone.utc),
        duration_s=3000,
        distance_mi=5.0,
        active_kcal=0.0,
        avg_hr=None,
        source="sync",
        flags={},
    )
    db_session.add(row)
    db_session.flush()
    db_session.add_all(
        [models.WorkoutSample(workout_id=row.id, minute=m, distance_mi=0.1) for m in range(50)]
    )
    bests.store(db_session, row.id, minutes_of([0.1] * 50))
    db_session.commit()

    db_session.query(models.WorkoutSample).filter_by(workout_id=row.id).delete()
    db_session.commit()

    assert db_session.query(models.WorkoutSample).count() == 0
    assert bests.for_user(db_session, member.id)[(row.id, "5k")] > 0
