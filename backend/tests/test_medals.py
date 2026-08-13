"""The medals: the catalogue, the three families, and what earns each of them."""

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


def test_the_catalogue_is_twenty_four_medals_in_six_families():
    assert len(medals.CATALOG) == 24
    assert len(medals.BY_ID) == 24
    assert [row.family for row in medals.CATALOG] == (
        ["race"] * 7 + ["weekly"] * 4 + ["time"] * 2 + ["cycle"] * 4 + ["swim"] * 3
        + ["lifetime"] * 4
    )
    for row in medals.CATALOG:
        assert row.name.strip()
    # Only the time family is earned without a distance of its own.
    assert [row.id for row in medals.CATALOG if row.distance_mi is None] == [
        "early_riser",
        "night_owl",
    ]


def test_every_family_with_thresholds_ascends():
    """Which is what makes "the highest one this qualifies for" a single pass,
    in every family that has a ladder."""
    for family in (
        medals.RACE_MEDALS,
        medals.WEEKLY_MEDALS,
        medals.CYCLE_MEDALS,
        medals.SWIM_MEDALS,
        medals.LIFETIME_MEDALS,
    ):
        distances = [row.distance_mi for row in family]
        assert distances == sorted(distances)
        assert len(set(distances)) == len(distances)


def test_the_two_new_race_medals_are_named_exactly_as_he_named_them():
    """These two names are the owner's own and are never to change."""
    assert medals.BY_ID["race_1mi"].name == "First Mile"
    assert medals.BY_ID["race_2mi"].name == "Second Mile"
    assert (medals.BY_ID["race_1mi"].distance_mi, medals.BY_ID["race_2mi"].distance_mi) == (
        1.0,
        2.0,
    )


def test_the_time_medals_follow_the_smallest_race_medal_down_to_a_mile():
    assert medals.MIN_TIME_MEDAL_MI == 1.0
    assert medals.MIN_TIME_MEDAL_MI == medals.RACE_MEDALS[0].distance_mi


def test_the_achievement_ids_are_gone():
    for gone in ("week_10", "week_40", "collection_complete"):
        assert gone not in medals.BY_ID


def test_the_second_mile_family_is_gone_from_the_catalogue():
    """It was a weekly rung at twenty miles wearing a special name, so it went
    and took its family with it. The name has since come back where it belongs,
    on race_2mi, and the retired id and family stay retired."""
    assert medals.BY_ID["race_2mi"].name == "Second Mile"
    assert "second_mile" not in medals.BY_ID
    assert "second_mile" not in {row.family for row in medals.CATALOG}
    assert "second_mile" not in medals.WEEK_FAMILIES
    assert not hasattr(medals, "SECOND_MILE")


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


def test_a_time_medal_wants_the_smallest_race_distance_on_the_ground(
    signed_in, db_session, member
):
    """The line follows the race family down: it was a 5K when the 5K was the
    smallest medal there was, and it is a mile now."""
    assert medals_after(db_session, member.id, at(0, 5, 0), miles=0.9) == []
    assert medals_after(db_session, member.id, at(1, 5, 0), miles=1.0) == [
        "race_1mi",
        "early_riser",
    ]


def test_a_time_medal_is_read_in_the_instance_timezone(
    signed_in, db_session, member, monkeypatch
):
    """Stored at 12:44 UTC, run at a quarter to six in the morning."""
    monkeypatch.setattr(medals, "SERVER_TZ", ZoneInfo("America/Phoenix"))
    stored = dt.datetime(2026, 6, 2, 12, 44, tzinfo=dt.timezone.utc)
    assert medals_after(db_session, member.id, stored) == ["race_5k", "early_riser"]


def test_a_walk_earns_a_time_medal_and_a_ride_and_a_swim_never_do(
    signed_in, db_session, member
):
    """Feet are feet: being out before six is what the medal marks, and the
    hour is the same hour whether it was walked or run. A ride and a swim at
    the same hour earn their own family's medal and nothing from this one."""
    add_workout(db_session, member.id, at(0, 5, 0), activity="walk", miles=4.0, duration_s=4800)
    add_workout(
        db_session, member.id, at(1, 5, 0), activity="cycle", miles=12.0, duration_s=3600
    )
    add_workout(db_session, member.id, at(2, 5, 0), activity="swim", miles=1.0, duration_s=3600)
    progress.process_user(db_session, member.id)
    assert workout_medals(db_session, member.id) == [
        "race_5k",
        "early_riser",
        "cycle_10",
        "swim_1",
    ]


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
# Feet are feet: the race family, walked
# --------------------------------------------------------------------------

# Every rung of the race family, smallest first, and what it is called.
RUNGS = (
    (1.0, "race_1mi"),
    (2.0, "race_2mi"),
    (3.1, "race_5k"),
    (6.2, "race_10k"),
    (13.1, "race_half"),
    (26.2, "race_marathon"),
    (31.1, "race_ultra"),
)


def test_a_walk_earns_at_every_rung_the_race_family_has(signed_in, db_session, member):
    """One walk per rung, one medal each, in the order they were walked."""
    for offset, (miles, _) in enumerate(RUNGS):
        add_workout(db_session, member.id, at(offset, 9), activity="walk", miles=miles)
    progress.process_user(db_session, member.id)
    assert workout_medals(db_session, member.id) == [medal for _, medal in RUNGS]


def test_a_run_earns_at_every_rung_exactly_as_it_always_did(signed_in, db_session, member):
    """The other half of the same law: nothing about a run changed."""
    for offset, (miles, _) in enumerate(RUNGS):
        add_workout(db_session, member.id, at(offset, 9), miles=miles)
    progress.process_user(db_session, member.id)
    assert workout_medals(db_session, member.id) == [medal for _, medal in RUNGS]


def test_a_two_mile_walk_earns_the_second_mile_and_nothing_under_it(
    signed_in, db_session, member
):
    """Highest-only stands whoever is on their feet: two miles is the Second
    Mile, not also the First."""
    assert medals_after(db_session, member.id, at(0, 9), activity="walk", miles=2.05) == [
        "race_2mi"
    ]


def test_an_impossible_pace_blocks_a_walk_the_way_it_blocks_a_run(
    signed_in, db_session, member
):
    assert (
        medals_after(
            db_session,
            member.id,
            at(0, 5, 0),
            activity="walk",
            miles=10.0,
            duration_s=20 * 60,
            flags={"impossible_pace": True},
        )
        == []
    )


# --------------------------------------------------------------------------
# The cycling and swimming families
# --------------------------------------------------------------------------


def test_a_ride_earns_the_highest_cycling_rung_it_reaches(signed_in, db_session, member):
    assert medals_after(
        db_session, member.id, at(0, 9), activity="cycle", miles=12.0, duration_s=3600
    ) == ["cycle_10"]


def test_a_ride_never_earns_a_race_medal_however_far_it_goes(
    signed_in, db_session, member
):
    """A hundred miles on a bike is a Century, and it is not a 50K."""
    earned = medals_after(
        db_session, member.id, at(0, 9), activity="cycle", miles=100.0, duration_s=6 * 3600
    )
    assert earned == ["cycle_100"]


def test_a_swim_earns_only_from_its_own_family(signed_in, db_session, member):
    """Swimming distances are their own scale entirely: half a mile in water is
    a medal, and it reaches neither the cycling family nor the race one."""
    assert medals_after(
        db_session, member.id, at(0, 9), activity="swim", miles=0.6, duration_s=1800
    ) == ["swim_half"]
    assert medals_after(
        db_session, member.id, at(1, 9), activity="swim", miles=12.0, duration_s=6 * 3600
    ) == ["swim_half", "swim_2"]


def test_a_walk_and_a_run_earn_nothing_from_the_cycling_or_swimming_families(
    signed_in, db_session, member
):
    add_workout(db_session, member.id, at(0, 9), activity="walk", miles=12.0)
    add_workout(db_session, member.id, at(1, 9), miles=12.0)
    progress.process_user(db_session, member.id)
    assert workout_medals(db_session, member.id) == ["race_10k", "race_10k"]


# --------------------------------------------------------------------------
# The lifetime odometer
# --------------------------------------------------------------------------


def odometer_rows(db_session, user_id) -> list[tuple]:
    """The odometer earns only, in the order they were written."""
    return [
        (row.badge_id, row.workout_id, row.earned_at)
        for row in db_session.query(models.BadgeEarn)
        .filter(models.BadgeEarn.user_id == user_id)
        .order_by(models.BadgeEarn.id)
        if row.badge_id.startswith("lifetime_")
    ]


def test_the_odometer_hangs_on_the_workout_whose_credit_crossed_the_line(
    signed_in, db_session, member
):
    add_workout(db_session, member.id, at(0, 9), miles=60.0)
    crossing = add_workout(db_session, member.id, at(1, 9), miles=60.0)
    add_workout(db_session, member.id, at(2, 9), miles=60.0)
    progress.process_user(db_session, member.id)
    assert odometer_rows(db_session, member.id) == [
        ("lifetime_100", crossing.id, crossing.start_ts)
    ]


def test_the_odometer_reads_converted_miles_rather_than_ground(
    signed_in, db_session, member
):
    """Twenty-five miles swum is a hundred Miles, which is the number the game
    is scored in and the only family here that is not measured on the ground."""
    crossing = add_workout(
        db_session, member.id, at(0, 9), activity="swim", miles=25.0, duration_s=10 * 3600
    )
    progress.process_user(db_session, member.id)
    assert [row[0] for row in odometer_rows(db_session, member.id)] == ["lifetime_100"]
    assert odometer_rows(db_session, member.id)[0][1] == crossing.id


def test_the_odometer_lands_exactly_on_its_threshold(signed_in, db_session, member):
    add_workout(db_session, member.id, at(0, 9), miles=40.0)
    add_workout(db_session, member.id, at(1, 9), miles=59.9)
    progress.process_user(db_session, member.id)
    assert odometer_rows(db_session, member.id) == []

    add_workout(db_session, member.id, at(2, 9), miles=0.1)
    progress.process_user(db_session, member.id)
    assert [row[0] for row in odometer_rows(db_session, member.id)] == ["lifetime_100"]


def test_one_credit_may_cross_two_lifetime_lines_at_once(signed_in, db_session, member):
    crossing = add_workout(db_session, member.id, at(0, 9), activity="cycle", miles=780.0)
    progress.process_user(db_session, member.id)
    # Two hundred and sixty converted Miles out of one very long ride.
    assert odometer_rows(db_session, member.id) == [
        ("lifetime_100", crossing.id, crossing.start_ts),
        ("lifetime_250", crossing.id, crossing.start_ts),
    ]


def test_the_odometer_is_earned_once_and_never_again(signed_in, db_session, member):
    """The one family here that is ticked off rather than counted."""
    for offset in range(4):
        add_workout(db_session, member.id, at(offset, 9), miles=60.0)
        progress.process_user(db_session, member.id)
    assert [row[0] for row in odometer_rows(db_session, member.id)] == ["lifetime_100"]

    # And a sweep that finds nothing new writes nothing new.
    progress.process_user(db_session, member.id)
    assert [row[0] for row in odometer_rows(db_session, member.id)] == ["lifetime_100"]


def test_a_rebuild_earns_the_odometer_on_the_same_workout(signed_in, db_session, member):
    add_workout(db_session, member.id, at(0, 9), miles=60.0)
    add_workout(db_session, member.id, at(1, 9), miles=60.0)
    add_workout(db_session, member.id, at(2, 9), activity="swim", miles=40.0, duration_s=9 * 3600)
    progress.process_user(db_session, member.id)
    before = odometer_rows(db_session, member.id)
    assert [row[0] for row in before] == ["lifetime_100", "lifetime_250"]

    progress.recompute(db_session, member.id)
    assert odometer_rows(db_session, member.id) == before


# --------------------------------------------------------------------------
# The weekly family
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
    assert held == {"weekly": "weekly_25"}


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


def test_twenty_miles_in_a_week_earns_the_weekly_medal_and_nothing_beside_it(
    signed_in, db_session, member
):
    """Twenty was the Second Mile's line, and the week that crosses it comes
    away with the one weekly row it was always going to have."""
    add_workout(db_session, member.id, at(0, 9), miles=9.9)
    add_workout(db_session, member.id, at(1, 9), miles=9.9)
    progress.process_user(db_session, member.id)
    assert [row[1] for row in week_rows(db_session, member.id)] == ["weekly"]

    add_workout(db_session, member.id, at(2, 9), miles=0.2)
    progress.process_user(db_session, member.id)
    assert [(row[1], row[2]) for row in week_rows(db_session, member.id)] == [
        ("weekly", "weekly_15")
    ]

    # And past twenty-five it is still that row, upgraded in place.
    add_workout(db_session, member.id, at(3, 9), miles=25.0)
    progress.process_user(db_session, member.id)
    assert [(row[1], row[2]) for row in week_rows(db_session, member.id)] == [
        ("weekly", "weekly_40")
    ]


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
    assert [row[2] for row in forwards] == ["weekly_25"]


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
    assert [row[2] for row in awarded[1]] == ["weekly_15"]

    _backfill(db_session, monkeypatch)
    assert (workout_medals(db_session, member.id), week_rows(db_session, member.id)) == awarded


def test_backfill_replays_the_new_families_and_writes_nothing_the_second_time(
    signed_in, db_session, member, monkeypatch
):
    """What the deploy runs: an account whose history predates the walk-based
    race medals, the sport families and the odometer, and none of which was
    ever written for it.

    The odometer is the one worth watching here, because it is the one earned
    once: a second run of the command has to find it already held rather than
    hand out a second hundredth Mile.
    """
    add_workout(db_session, member.id, at(0, 9), activity="walk", miles=8.0)
    add_workout(db_session, member.id, at(1, 9), activity="cycle", miles=30.0)
    crossing = add_workout(db_session, member.id, at(2, 9), activity="swim", miles=25.0)
    progress.process_user(db_session, member.id)
    medals.clear_earns(db_session, member.id)
    db_session.commit()

    _backfill(db_session, monkeypatch)
    awarded = workout_medals(db_session, member.id)
    assert awarded == ["race_10k", "cycle_25", "swim_2", "lifetime_100"]
    # Earned at the crossing's own start, which is what keeps the letter quiet
    # about a medal dated in June.
    assert odometer_rows(db_session, member.id) == [
        ("lifetime_100", crossing.id, crossing.start_ts)
    ]

    _backfill(db_session, monkeypatch)
    assert workout_medals(db_session, member.id) == awarded


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
