"""The achievements engine: awarding, gilding, week boundaries, and no revoking."""

import datetime as dt

from conftest import log_workout

from app import achievements, models, progress, security
from app.activity import SERVER_TZ, week_start


def add_workout(db_session, user_id, activity, start_ts, *, miles=1.0, duration_s=1800):
    row = models.Workout(
        user_id=user_id,
        activity=activity,
        start_ts=start_ts,
        duration_s=duration_s,
        distance_mi=miles,
        active_kcal=100.0,
        avg_hr=None,
        source="sync",
        flags={},
        created_at=security.now_utc(),
    )
    db_session.add(row)
    db_session.commit()
    return row


def earned(client) -> dict[str, dict]:
    rows = client.get("/api/achievements").json()
    return {row["id"]: row for row in rows if row["earned"]}


def test_the_catalogue_is_well_formed():
    assert len(achievements.CATALOG) == len(achievements.BY_ID)
    assert {row.kind for row in achievements.CATALOG} == set(achievements.KINDS)
    for row in achievements.CATALOG:
        assert row.name.strip() and row.detail.strip()
        # Only the weekly ones gild: gilding is for doubling a target inside a
        # window, and nothing else here has a window.
        assert (row.gilded_target is not None) == (row.kind == "week-distance")


def test_the_whole_catalogue_is_listed_earned_or_not(signed_in):
    rows = signed_in.get("/api/achievements").json()
    assert len(rows) == len(achievements.CATALOG)
    assert all(row["earned"] is False for row in rows)
    assert set(rows[0]) == {
        "id",
        "kind",
        "name",
        "detail",
        "gildable",
        "earned",
        "gilded",
        "earned_at",
    }


def test_the_dropped_kinds_are_gone_from_the_catalogue(signed_in):
    """Single-workout duration, lifetime distance, and the firsts are replaced
    by the race badges; only the weekly and collection families remain."""
    ids = {row.id for row in achievements.CATALOG}
    for gone in ("duration_30", "lifetime_50", "first_run"):
        assert gone not in ids
    assert {row["id"] for row in signed_in.get("/api/achievements").json()} == ids


def test_a_weekly_badge_gilds_when_the_same_week_doubles_it(signed_in, db_session, member):
    monday = week_start(security.now_utc())
    start = dt.datetime.combine(monday, dt.time(7, 0), tzinfo=SERVER_TZ)
    for day in range(2):
        add_workout(
            db_session, member.id, "run", start + dt.timedelta(days=day, hours=day), miles=6.0
        )
    held = earned(signed_in)
    assert held["week_10"]["gilded"] is False
    assert held["week_10"]["gildable"] is True

    # Twenty Miles in the same week is the second mile, and gilds the ten.
    for day in range(2, 4):
        add_workout(
            db_session, member.id, "run", start + dt.timedelta(days=day, hours=day), miles=4.0
        )
    held = earned(signed_in)
    assert held["week_10"]["gilded"] is True
    assert held["week_15"]["gilded"] is False
    assert db_session.get(models.UserAchievement, (member.id, "week_10")).gilded is True


def test_a_week_is_a_server_timezone_monday_week(signed_in, db_session, member):
    """Miles either side of a Monday belong to different weeks and do not add up."""
    monday = week_start(security.now_utc())
    this_week = dt.datetime.combine(monday, dt.time(9, 0), tzinfo=SERVER_TZ)
    last_week = this_week - dt.timedelta(days=1)  # the Sunday before

    add_workout(db_session, member.id, "run", last_week, miles=8.0)
    add_workout(db_session, member.id, "run", this_week, miles=8.0)
    # Sixteen Miles in total, but never more than eight inside one week.
    assert "week_10" not in earned(signed_in)

    add_workout(db_session, member.id, "run", this_week + dt.timedelta(hours=6), miles=3.0)
    assert "week_10" in earned(signed_in)


def test_a_badge_is_never_revoked_and_never_reissued(signed_in, db_session, member):
    monday = week_start(security.now_utc())
    add_workout(
        db_session,
        member.id,
        "run",
        dt.datetime.combine(monday, dt.time(7, 0), tzinfo=SERVER_TZ),
        miles=11.0,
    )
    assert "week_10" in earned(signed_in)
    row = db_session.get(models.UserAchievement, (member.id, "week_10"))
    first_earned = row.earned_at

    # The history goes away entirely. The badge does not.
    db_session.query(models.Workout).filter(models.Workout.user_id == member.id).delete()
    db_session.commit()
    assert "week_10" in earned(signed_in)
    assert db_session.get(models.UserAchievement, (member.id, "week_10")).earned_at == first_earned


def test_collection_badges_arrive_with_the_card(signed_in, db_session, member):
    from app import world

    assert "collection_first_card" not in earned(signed_in)
    first_light = world.CARDS_BY_SET["first_light"]
    chest = models.Chest(
        user_id=member.id,
        card_id=first_light[0].id,
        dropped_at=security.now_utc(),
        opened_at=None,
    )
    db_session.add(chest)
    db_session.commit()
    signed_in.post(f"/api/chests/{chest.id}/open")
    held = earned(signed_in)
    assert "collection_first_card" in held
    assert "collection_set_first_light" not in held

    for card in first_light[1:]:
        db_session.add(
            models.UserCard(
                user_id=member.id,
                card_id=card.id,
                count=1,
                first_found_at=security.now_utc(),
            )
        )
    db_session.commit()
    held = earned(signed_in)
    assert "collection_set_first_light" in held
    assert "collection_complete" not in held


def test_evaluating_twice_writes_nothing_the_second_time(signed_in, db_session, member):
    log_workout(signed_in, "run", 11.0, pace_min=9)
    progress.process_user(db_session, member.id)
    before = (
        db_session.query(models.UserAchievement)
        .filter(models.UserAchievement.user_id == member.id)
        .count()
    )
    assert before > 0
    assert achievements.evaluate(db_session, member.id) == 0
    after = (
        db_session.query(models.UserAchievement)
        .filter(models.UserAchievement.user_id == member.id)
        .count()
    )
    assert after == before


def test_history_that_predates_the_release_is_picked_up_on_the_first_read(
    signed_in, db_session, member
):
    """What the migration relies on instead of backfilling badges by hand."""
    add_workout(
        db_session,
        member.id,
        "walk",
        security.now_utc() - dt.timedelta(days=200),
        miles=60.0,
        duration_s=20 * 3600,
    )
    # Marked credited, exactly as migration 0004 leaves an existing history.
    db_session.add(
        models.ProcessedWorkout(
            workout_id=db_session.query(models.Workout.id)
            .filter(models.Workout.user_id == member.id)
            .scalar()
        )
    )
    db_session.commit()
    assert "week_40" in earned(signed_in)
