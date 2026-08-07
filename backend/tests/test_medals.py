"""The medals: the catalogue, the four families, and what earns each of them."""

import argparse
import datetime as dt
from zoneinfo import ZoneInfo

from app import medals, models, progress, security
from app.activity import SERVER_TZ

# A Monday well clear of the clock, so a case that means to test a Tuesday is
# never a case about the day the suite happened to run.
MONDAY = dt.date(2026, 6, 1)


def at(day_offset: int, hour: int, minute: int = 0) -> dt.datetime:
    """A moment inside the fixed week, in the instance timezone."""
    return dt.datetime.combine(
        MONDAY + dt.timedelta(days=day_offset), dt.time(hour, minute), tzinfo=SERVER_TZ
    )


def add_workout(
    db_session,
    user_id,
    start_ts,
    *,
    activity="run",
    miles=5.0,
    duration_s=3600,
    flags=None,
    created_at=None,
):
    row = models.Workout(
        user_id=user_id,
        activity=activity,
        start_ts=start_ts,
        duration_s=duration_s,
        distance_mi=miles,
        active_kcal=100.0,
        avg_hr=None,
        source="sync",
        flags=flags or {},
        created_at=created_at or security.now_utc(),
    )
    db_session.add(row)
    db_session.commit()
    return row


def workout_medals(db_session, user_id) -> list[str]:
    return [
        row.badge_id
        for row in db_session.query(models.BadgeEarn)
        .filter(models.BadgeEarn.user_id == user_id)
        .order_by(models.BadgeEarn.id)
    ]


def week_rows(db_session, user_id) -> list[tuple]:
    return [
        (row.week_start, row.family, row.badge_id, row.workout_id, row.earned_at)
        for row in db_session.query(models.WeeklyBadgeEarn)
        .filter(models.WeeklyBadgeEarn.user_id == user_id)
        .order_by(models.WeeklyBadgeEarn.week_start, models.WeeklyBadgeEarn.family)
    ]


def medals_after(db_session, user_id, start_ts, **kwargs) -> list[str]:
    """One workout, credited, and the per-workout medals it came away with."""
    add_workout(db_session, user_id, start_ts, **kwargs)
    progress.process_user(db_session, user_id)
    return workout_medals(db_session, user_id)


# --------------------------------------------------------------------------
# The catalogue
# --------------------------------------------------------------------------


def test_the_catalogue_is_twelve_medals_in_four_families():
    assert len(medals.CATALOG) == 12
    assert len(medals.BY_ID) == 12
    assert [row.family for row in medals.CATALOG] == (
        ["race"] * 5 + ["weekly"] * 4 + ["time"] * 2 + ["second_mile"]
    )
    for row in medals.CATALOG:
        assert row.name.strip()
    # Only the time family is earned without a distance of its own.
    assert [row.id for row in medals.CATALOG if row.distance_mi is None] == [
        "early_riser",
        "night_owl",
    ]


def test_the_achievement_ids_are_gone():
    for gone in ("week_10", "week_40", "collection_complete"):
        assert gone not in medals.BY_ID


# --------------------------------------------------------------------------
# The time family
# --------------------------------------------------------------------------


def test_the_early_riser_window_opens_at_four(signed_in, db_session, member):
    assert medals_after(db_session, member.id, at(0, 3, 59)) == ["race_5k", "night_owl"]
    assert medals_after(db_session, member.id, at(1, 4, 0)) == [
        "race_5k",
        "night_owl",
        "race_5k",
        "early_riser",
    ]


def test_the_early_riser_window_closes_at_six(signed_in, db_session, member):
    assert medals_after(db_session, member.id, at(0, 5, 59)) == ["race_5k", "early_riser"]
    # Six is a normal morning. The run still earns its distance and nothing else.
    assert medals_after(db_session, member.id, at(1, 6, 0)) == [
        "race_5k",
        "early_riser",
        "race_5k",
    ]


def test_the_night_owl_window_opens_at_eight_in_the_evening(signed_in, db_session, member):
    assert medals_after(db_session, member.id, at(0, 19, 59)) == ["race_5k"]
    assert medals_after(db_session, member.id, at(1, 20, 0)) == [
        "race_5k",
        "race_5k",
        "night_owl",
    ]


def test_the_night_owl_window_runs_through_midnight(signed_in, db_session, member):
    assert medals_after(db_session, member.id, at(0, 23, 30)) == ["race_5k", "night_owl"]
    assert medals_after(db_session, member.id, at(1, 0, 1)) == [
        "race_5k",
        "night_owl",
        "race_5k",
        "night_owl",
    ]


def test_a_time_medal_wants_a_5k_on_the_ground(signed_in, db_session, member):
    assert medals_after(db_session, member.id, at(0, 5, 0), miles=3.09) == []
    assert medals_after(db_session, member.id, at(1, 5, 0), miles=3.1) == [
        "race_5k",
        "early_riser",
    ]


def test_a_time_medal_is_read_in_the_instance_timezone(
    signed_in, db_session, member, monkeypatch
):
    """Stored at 12:44 UTC, run at a quarter to six in the morning."""
    monkeypatch.setattr(medals, "SERVER_TZ", ZoneInfo("America/Phoenix"))
    stored = dt.datetime(2026, 6, 2, 12, 44, tzinfo=dt.timezone.utc)
    assert medals_after(db_session, member.id, stored) == ["race_5k", "early_riser"]


def test_only_a_run_earns_a_time_medal(signed_in, db_session, member):
    for offset, activity in enumerate(("walk", "cycle", "swim")):
        add_workout(
            db_session,
            member.id,
            at(offset, 5, 0),
            activity=activity,
            miles=10.0,
            duration_s=4 * 3600,
        )
    progress.process_user(db_session, member.id)
    assert workout_medals(db_session, member.id) == []


def test_an_impossible_pace_earns_neither_family(signed_in, db_session, member):
    assert (
        medals_after(
            db_session,
            member.id,
            at(0, 5, 0),
            miles=10.0,
            duration_s=20 * 60,
            flags={"impossible_pace": True},
        )
        == []
    )


def test_one_run_can_earn_a_race_medal_and_a_time_medal(signed_in, db_session, member):
    """The two families share a workout, which is what the pair key is for."""
    assert medals_after(db_session, member.id, at(0, 5, 30), miles=3.2) == [
        "race_5k",
        "early_riser",
    ]


# --------------------------------------------------------------------------
# The weekly family and the Second Mile
# --------------------------------------------------------------------------


def test_a_week_earns_one_medal_and_upgrades_it_in_place(signed_in, db_session, member):
    add_workout(db_session, member.id, at(0, 9), miles=6.0)
    crossing = add_workout(db_session, member.id, at(1, 9), miles=6.0)
    progress.process_user(db_session, member.id)
    assert week_rows(db_session, member.id) == [
        (MONDAY, "weekly", "weekly_10", crossing.id, crossing.start_ts)
    ]

    # Fifteen miles is the next tier, and it is the same row that holds it.
    upgraded = add_workout(db_session, member.id, at(2, 9), miles=4.0)
    progress.process_user(db_session, member.id)
    assert week_rows(db_session, member.id) == [
        (MONDAY, "weekly", "weekly_15", upgraded.id, upgraded.start_ts)
    ]


def test_a_week_totals_every_activity_at_its_raw_distance(signed_in, db_session, member):
    """Raw miles, not converted Miles: twelve miles on a bike is twelve miles."""
    add_workout(db_session, member.id, at(0, 9), activity="cycle", miles=12.0)
    add_workout(db_session, member.id, at(1, 9), activity="walk", miles=8.0)
    add_workout(db_session, member.id, at(2, 9), activity="swim", miles=1.0)
    add_workout(db_session, member.id, at(3, 9), activity="run", miles=5.0)
    progress.process_user(db_session, member.id)
    held = {row[1]: row[2] for row in week_rows(db_session, member.id)}
    assert held == {"weekly": "weekly_25", "second_mile": "second_mile"}


def test_a_flagged_workout_still_counts_toward_the_week(signed_in, db_session, member):
    """A flag blocks the medal on the workout it is on, never the week's total."""
    add_workout(
        db_session,
        member.id,
        at(0, 9),
        miles=11.0,
        duration_s=30 * 60,
        flags={"impossible_pace": True},
    )
    progress.process_user(db_session, member.id)
    assert workout_medals(db_session, member.id) == []
    assert [row[2] for row in week_rows(db_session, member.id)] == ["weekly_10"]


def test_the_second_mile_arrives_once_a_week_at_twenty_miles(signed_in, db_session, member):
    add_workout(db_session, member.id, at(0, 9), miles=9.9)
    add_workout(db_session, member.id, at(1, 9), miles=9.9)
    progress.process_user(db_session, member.id)
    assert [row[1] for row in week_rows(db_session, member.id)] == ["weekly"]

    crossing = add_workout(db_session, member.id, at(2, 9), miles=0.2)
    progress.process_user(db_session, member.id)
    rows = {row[1]: row for row in week_rows(db_session, member.id)}
    assert rows["second_mile"][2] == "second_mile"
    assert rows["second_mile"][3] == crossing.id
    assert rows["second_mile"][4] == crossing.start_ts

    # Another twenty miles in the same week is not another Second Mile.
    add_workout(db_session, member.id, at(3, 9), miles=25.0)
    progress.process_user(db_session, member.id)
    rows = {row[1]: row for row in week_rows(db_session, member.id)}
    assert rows["second_mile"][3] == crossing.id
    assert rows["weekly"][2] == "weekly_40"


def test_a_week_is_a_server_timezone_monday_week(signed_in, db_session, member):
    """Miles either side of a Monday belong to different weeks and do not add up."""
    add_workout(db_session, member.id, at(-1, 9), miles=8.0)  # the Sunday before
    add_workout(db_session, member.id, at(0, 9), miles=8.0)
    progress.process_user(db_session, member.id)
    assert week_rows(db_session, member.id) == []

    add_workout(db_session, member.id, at(1, 9), miles=3.0)
    progress.process_user(db_session, member.id)
    assert [(row[0], row[2]) for row in week_rows(db_session, member.id)] == [
        (MONDAY, "weekly_10")
    ]


def test_the_same_week_lands_the_same_rows_whatever_order_it_arrives_in(
    signed_in, db_session, admin, member
):
    """His January history, backfilled: the week converges either way."""
    week = [(0, 6.0), (2, 9.0), (4, 7.0), (5, 4.0)]
    for day, miles in week:
        add_workout(db_session, member.id, at(day, 9), miles=miles)
        progress.process_user(db_session, member.id)
    forwards = week_rows(db_session, member.id)

    for day, miles in reversed(week):
        add_workout(db_session, admin.id, at(day, 9), miles=miles)
        progress.process_user(db_session, admin.id)
    backwards = week_rows(db_session, admin.id)

    # Same medals, same week, same crossing moment. The workout ids differ
    # because they are different accounts' rows.
    assert [row[:3] for row in forwards] == [row[:3] for row in backwards]
    assert [row[4] for row in forwards] == [row[4] for row in backwards]
    assert [row[2] for row in forwards] == ["second_mile", "weekly_25"]


def test_a_rebuild_earns_exactly_the_same_medals(signed_in, db_session, member):
    add_workout(db_session, member.id, at(0, 5, 30), miles=13.2)
    add_workout(db_session, member.id, at(2, 21, 0), miles=8.0)
    progress.process_user(db_session, member.id)
    before = (workout_medals(db_session, member.id), week_rows(db_session, member.id))

    progress.process_user(db_session, member.id)
    assert (workout_medals(db_session, member.id), week_rows(db_session, member.id)) == before

    progress.recompute(db_session, member.id)
    assert (workout_medals(db_session, member.id), week_rows(db_session, member.id)) == before


# --------------------------------------------------------------------------
# The backfill
# --------------------------------------------------------------------------


def _backfill(db_session, monkeypatch, username="runner"):
    import manage

    monkeypatch.setattr(manage, "_session", lambda: db_session)
    manage.cmd_backfill_badges(argparse.Namespace(username=username))


def test_backfill_awards_every_family_and_runs_twice_the_same(
    signed_in, db_session, member, monkeypatch
):
    """The state an install upgrading into the new families is in: the history
    is credited already, and no medal was ever written for it."""
    add_workout(db_session, member.id, at(0, 5, 30), miles=13.2)
    add_workout(db_session, member.id, at(2, 21, 0), miles=8.0)
    progress.process_user(db_session, member.id)
    medals.clear_earns(db_session, member.id)
    db_session.commit()
    assert workout_medals(db_session, member.id) == []

    _backfill(db_session, monkeypatch)
    awarded = (workout_medals(db_session, member.id), week_rows(db_session, member.id))
    assert awarded[0] == ["race_half", "early_riser", "race_10k", "night_owl"]
    assert [row[2] for row in awarded[1]] == ["second_mile", "weekly_15"]

    _backfill(db_session, monkeypatch)
    assert (workout_medals(db_session, member.id), week_rows(db_session, member.id)) == awarded


def test_backfill_corrects_a_weekly_row_left_holding_a_lower_medal(
    signed_in, db_session, member, monkeypatch
):
    add_workout(db_session, member.id, at(0, 9), miles=11.0)
    crossing = add_workout(db_session, member.id, at(1, 9), miles=20.0)
    progress.process_user(db_session, member.id)

    # A row from a partial history: the right week, the wrong medal.
    row = db_session.query(models.WeeklyBadgeEarn).filter_by(family="weekly").one()
    row.badge_id = "weekly_10"
    db_session.commit()

    _backfill(db_session, monkeypatch)
    row = db_session.query(models.WeeklyBadgeEarn).filter_by(family="weekly").one()
    assert (row.badge_id, row.workout_id, row.earned_at) == (
        "weekly_25",
        crossing.id,
        crossing.start_ts,
    )


def test_backfill_touches_nothing_but_medals(signed_in, db_session, member, monkeypatch):
    add_workout(db_session, member.id, at(0, 9), miles=11.0)
    progress.process_user(db_session, member.id)
    before = db_session.query(models.UserProgress).one()
    experience, level = before.xp, before.level
    chests = db_session.query(models.Chest).count()

    _backfill(db_session, monkeypatch)

    after = db_session.query(models.UserProgress).one()
    assert (after.xp, after.level) == (experience, level)
    assert db_session.query(models.Chest).count() == chests
    assert db_session.query(models.Workout).count() == 1
