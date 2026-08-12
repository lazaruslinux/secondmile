"""Steps: what a pedometer sends, where it is stored, and that it earns nothing.

The law this file pins, in one sentence: steps are stored and shown, and miles
are the work put into a recorded activity, so a step is worth no experience, no
level, no chest, no growth, no medal and no place in any miles total.

The round before this one credited the day's remainder over its walks and runs.
That was reversed. What it left behind stays in the schema and is dormant:
step_credits, its processed markers, daily_steps.credited_mi, and the nullable
workout_id on a weekly earn. Cases below pin that nothing writes to any of them
and that a rebuild reads none of them.

The clock is frozen at a Wednesday, so 2026-04-15 is today in the instance
timezone and 2026-04-13 is the Monday its week starts on. Every export here is
dated against those on purpose: a case about a reading must not also be a case
about which day a sample landed in.
"""

import datetime as dt

from conftest import let_a_moment_pass, log_workout
from test_ingest import post, workout as entry

from app import models, progress, security
from app.activity import parse_metrics
from app.config import MAX_DAILY_STEP_MI, MAX_DAILY_STEPS

TODAY = dt.date(2026, 4, 15)
YESTERDAY = dt.date(2026, 4, 14)
MONDAY = dt.date(2026, 4, 13)


def sample(day: dt.date, qty, hour: int = 12) -> dict:
    return {"date": f"{day.isoformat()} {hour:02d}:00:00 +0000", "qty": qty}


def metric(name: str, units: str, *points) -> dict:
    return {"name": name, "units": units, "data": list(points)}


def reading(day: dt.date = TODAY, *, steps=None, miles=None, units="mi") -> list[dict]:
    """The two metrics a phone sends, for one day, in the export's own shape."""
    metrics = []
    if steps is not None:
        metrics.append(metric("step_count", "count", sample(day, steps)))
    if miles is not None:
        metrics.append(metric("walking_running_distance", units, sample(day, miles)))
    return metrics


def sync(client, token, *, metrics=(), workouts=()):
    return post(client, token, {"data": {"workouts": list(workouts), "metrics": list(metrics)}})


def day_row(db_session, user_id: int, day: dt.date = TODAY) -> models.DailySteps:
    db_session.expire_all()
    return (
        db_session.query(models.DailySteps)
        .filter(models.DailySteps.user_id == user_id, models.DailySteps.day == day)
        .one_or_none()
    )


def ledger(db_session, user_id: int) -> list[models.StepCredit]:
    """The dormant ledger. Every case that reads it expects it empty."""
    db_session.expire_all()
    return (
        db_session.query(models.StepCredit)
        .filter(models.StepCredit.user_id == user_id)
        .order_by(models.StepCredit.id)
        .all()
    )


def progress_of(db_session, user_id: int) -> models.UserProgress:
    db_session.expire_all()
    return db_session.get(models.UserProgress, user_id)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_the_two_metrics_are_read_and_the_rest_are_named():
    days, ignored = parse_metrics(
        {
            "data": {
                "metrics": [
                    metric("step_count", "count", sample(TODAY, 8000)),
                    metric("walking_running_distance", "mi", sample(TODAY, 3.5)),
                    metric("heart_rate", "count/min", sample(TODAY, 62)),
                ]
            }
        }
    )
    assert days[TODAY].steps == 8000
    assert days[TODAY].distance_mi == 3.5
    assert [row["reason"] for row in ignored] == ["unsupported metric"]
    assert ignored[0]["name"] == "heart_rate"


def test_metric_names_are_matched_however_they_are_spelled():
    days, ignored = parse_metrics(
        {
            "metrics": [
                metric("Walking + Running Distance", "mi", sample(TODAY, 2.0)),
                metric("Step Count", "count", sample(TODAY, 500)),
            ]
        }
    )
    assert ignored == []
    assert (days[TODAY].distance_mi, days[TODAY].steps) == (2.0, 500)


def test_metric_distance_honours_its_declared_units():
    days, _ignored = parse_metrics({"data": {"metrics": reading(miles=10.0, units="km")}})
    assert round(days[TODAY].distance_mi, 4) == 6.2137


def test_samples_finer_than_a_day_are_summed_into_it():
    days, _ignored = parse_metrics(
        {
            "data": {
                "metrics": [
                    metric(
                        "walking_running_distance",
                        "mi",
                        sample(TODAY, 0.5, hour=8),
                        sample(TODAY, 1.25, hour=13),
                        sample(YESTERDAY, 2.0, hour=20),
                    )
                ]
            }
        }
    )
    assert round(days[TODAY].distance_mi, 2) == 1.75
    assert days[YESTERDAY].distance_mi == 2.0


def test_an_unreadable_sample_is_dropped_and_the_day_survives():
    days, ignored = parse_metrics(
        {
            "data": {
                "metrics": [
                    metric(
                        "step_count",
                        "count",
                        {"date": "not a date", "qty": 900},
                        {"date": f"{TODAY.isoformat()} 09:00:00 +0000", "qty": "bad"},
                        sample(TODAY, 1200),
                    )
                ]
            }
        }
    )
    assert days[TODAY].steps == 1200
    assert {row["reason"] for row in ignored} == {"unreadable date", "value is not a number"}


def test_an_export_with_no_metrics_at_all_says_nothing():
    assert parse_metrics({"data": {"workouts": []}}) == ({}, [])


def test_the_refusals_ride_into_the_ingest_log(signed_in, ingest_token, db_session):
    assert sync(
        signed_in,
        ingest_token,
        metrics=[metric("blood_oxygen", "%", sample(TODAY, 98))],
    ).json() == {"imported": 0, "skipped": 0, "flagged": 0, "ignored": 1}
    logged = db_session.query(models.IngestLog).one()
    assert logged.result["ignored_detail"][0]["name"] == "blood_oxygen"


def test_an_export_carrying_too_many_samples_is_refused(signed_in, ingest_token, monkeypatch):
    from app.routers import ingest as ingest_router

    monkeypatch.setattr(ingest_router, "MAX_INGEST_METRIC_POINTS", 2)
    crowd = metric("step_count", "count", *[sample(TODAY, 1, hour=hour) for hour in range(3)])
    assert sync(signed_in, ingest_token, metrics=[crowd]).status_code == 400


# --------------------------------------------------------------------------
# Storing a day
# --------------------------------------------------------------------------


def test_a_days_reading_is_stored_as_it_arrived(signed_in, ingest_token, db_session, member):
    sync(signed_in, ingest_token, metrics=reading(steps=12000, miles=5.0))
    row = day_row(db_session, member.id)
    assert (row.steps, row.distance_mi) == (12000, 5.0)
    assert row.capped is False
    # The dormant half of the row, and the dormant table beside it. Nothing
    # writes to either any more, so a fresh day is credited with nothing.
    assert row.credited_mi == 0.0
    assert ledger(db_session, member.id) == []


def test_a_walk_the_same_day_changes_nothing(signed_in, ingest_token, db_session, member):
    """The old law subtracted the day's walks and ran the remainder. There is
    no remainder now: the reading is stored as the pedometer sent it, and the
    walk is a workout, which is the only thing that earns."""
    sync(
        signed_in,
        ingest_token,
        workouts=[entry("Outdoor Walk", f"{TODAY.isoformat()}T09:00:00+00:00", 3600, 4.0, 300)],
        metrics=reading(miles=5.0),
    )
    row = day_row(db_session, member.id)
    assert row.distance_mi == 5.0
    assert row.credited_mi == 0.0
    # Four miles walked and four miles of experience: the workout's, and only
    # the workout's.
    assert round(progress_of(db_session, member.id).xp, 2) == 4.0


def test_each_day_is_stored_on_its_own(signed_in, ingest_token, db_session, member):
    sync(signed_in, ingest_token, metrics=reading(TODAY, miles=4.0) + reading(YESTERDAY, miles=2.0))
    assert day_row(db_session, member.id, TODAY).distance_mi == 4.0
    assert day_row(db_session, member.id, YESTERDAY).distance_mi == 2.0


def test_a_second_export_of_the_same_day_keeps_the_higher_reading(
    signed_in, ingest_token, db_session, member
):
    sync(signed_in, ingest_token, metrics=reading(steps=6000, miles=3.0))
    sync(signed_in, ingest_token, metrics=reading(steps=9000, miles=5.0))
    row = day_row(db_session, member.id)
    assert (row.steps, row.distance_mi) == (9000, 5.0)


def test_a_partial_export_never_takes_a_fuller_reading_back_down(
    signed_in, ingest_token, db_session, member
):
    sync(signed_in, ingest_token, metrics=reading(steps=9000, miles=5.0))
    # The window this export covers is half the day. It says less, and less is
    # not a correction.
    sync(signed_in, ingest_token, metrics=reading(steps=2000, miles=1.0))
    row = day_row(db_session, member.id)
    assert (row.steps, row.distance_mi) == (9000, 5.0)


def test_a_reading_past_the_bounds_is_clamped_and_marked(
    signed_in, ingest_token, db_session, member
):
    """A confused sensor is free to send anything, and the count is an integer
    column. The day is stored at the ceiling and marked; nothing is refused."""
    sync(
        signed_in,
        ingest_token,
        metrics=reading(steps=MAX_DAILY_STEPS + 50_000, miles=MAX_DAILY_STEP_MI + 40.0),
    )
    row = day_row(db_session, member.id)
    assert row.steps == MAX_DAILY_STEPS
    assert row.distance_mi == MAX_DAILY_STEP_MI
    assert row.capped is True


def test_a_sync_says_how_many_days_it_wrote(signed_in, ingest_token, db_session, member):
    sync(signed_in, ingest_token, metrics=reading(TODAY, steps=800) + reading(YESTERDAY, steps=900))
    logged = db_session.query(models.IngestLog).one()
    assert logged.result["step_days"] == 2


# --------------------------------------------------------------------------
# What steps are worth: nothing
# --------------------------------------------------------------------------


def test_steps_earn_no_experience_no_chest_and_no_growth(
    signed_in, ingest_token, db_session, member
):
    from conftest import give_planting

    planted = give_planting(db_session, member.id)
    sync(signed_in, ingest_token, metrics=reading(steps=40000, miles=18.0))
    row = progress_of(db_session, member.id)
    assert row.xp == 0.0
    assert row.level == 0
    assert row.chest_progress_mi == 0.0
    assert db_session.query(models.Chest).filter_by(user_id=member.id).count() == 0
    db_session.expire_all()
    assert db_session.get(models.Planting, planted.id).growth_mi == 0.0


def test_steps_write_no_ledger_row_and_claim_no_marker(
    signed_in, ingest_token, db_session, member
):
    sync(signed_in, ingest_token, metrics=reading(miles=9.0))
    progress.process_user(db_session, member.id)
    assert ledger(db_session, member.id) == []
    assert db_session.query(models.ProcessedStepCredit).count() == 0


def test_steps_earn_no_medal_and_make_no_workout(signed_in, ingest_token, db_session, member):
    sync(signed_in, ingest_token, metrics=reading(miles=30.0))
    # Thirty miles of walking about is no race medal and no weekly one either.
    assert db_session.query(models.BadgeEarn).filter_by(user_id=member.id).count() == 0
    assert db_session.query(models.WeeklyBadgeEarn).filter_by(user_id=member.id).count() == 0
    # No workout row, so there is nothing to appear in a feed and no energy to
    # become manna.
    assert db_session.query(models.Workout).filter_by(user_id=member.id).count() == 0


def test_the_streak_and_the_diamonds_ignore_steps(signed_in, ingest_token, db_session, member):
    sync(signed_in, ingest_token, metrics=reading(steps=20000, miles=9.0))
    assert progress.streak_weeks(db_session, member.id) == 0
    assert progress.week_days(db_session, member.id) == [False] * 7


# --------------------------------------------------------------------------
# The week
# --------------------------------------------------------------------------


def weekly_row(db_session, user_id: int) -> models.WeeklyBadgeEarn:
    db_session.expire_all()
    return (
        db_session.query(models.WeeklyBadgeEarn)
        .filter(models.WeeklyBadgeEarn.user_id == user_id)
        .one_or_none()
    )


def test_a_week_of_steps_alone_earns_nothing(signed_in, ingest_token, db_session, member):
    sync(signed_in, ingest_token, metrics=reading(miles=26.0))
    assert weekly_row(db_session, member.id) is None


def test_steps_never_carry_a_week_over_the_line(signed_in, ingest_token, db_session, member):
    log_workout(db_session, member.id, "run", 9.0)
    # Eleven miles of pedometer distance on a nine mile week. The week is nine
    # miles: a pedometer reading is not a week's miles.
    sync(signed_in, ingest_token, metrics=reading(miles=11.0))
    assert weekly_row(db_session, member.id) is None


def test_a_week_the_workouts_carry_names_the_workout(
    signed_in, ingest_token, db_session, member
):
    sync(signed_in, ingest_token, metrics=reading(miles=2.0))
    crossing = log_workout(db_session, member.id, "run", 11.0)
    row = weekly_row(db_session, member.id)
    assert row.badge_id == "weekly_10"
    assert row.week_start == MONDAY
    assert row.workout_id == crossing.id
    assert row.earned_at == crossing.start_ts


def test_a_weekly_row_with_no_workout_still_reads_back(signed_in, db_session, member):
    """workout_id stays nullable and nothing writes a null there any more. The
    rows the credited round left behind are still read: the letter dates them
    by their own stamp rather than by a workout they never had."""
    db_session.add(
        models.WeeklyBadgeEarn(
            user_id=member.id,
            week_start=MONDAY,
            family="weekly",
            badge_id="weekly_10",
            workout_id=None,
            earned_at=security.now_utc(),
        )
    )
    db_session.commit()
    letter = signed_in.get("/api/recap").json()
    assert [row["id"] for row in letter["medals"]] == ["weekly_10"]


# --------------------------------------------------------------------------
# Deleting, restoring, rebuilding
# --------------------------------------------------------------------------


def test_deleting_a_walk_leaves_the_step_rows_alone(
    signed_in, ingest_token, db_session, member
):
    walk = log_workout(db_session, member.id, "walk", 4.0)
    sync(signed_in, ingest_token, metrics=reading(steps=9000, miles=6.0))
    assert signed_in.delete(f"/api/workouts/{walk.id}").status_code == 204

    row = day_row(db_session, member.id)
    assert (row.steps, row.distance_mi) == (9000, 6.0)
    # The walk's miles are gone and the day's reading is untouched, because the
    # two have nothing to do with each other any more.
    assert progress_of(db_session, member.id).xp == 0.0


def stale_credit(db_session, user_id: int, miles: float) -> models.StepCredit:
    """A ledger row from before the retreat, written straight in. Nothing in
    the app writes one any more, and a rebuild has to ignore what it finds."""
    row = models.StepCredit(
        user_id=user_id, day=TODAY, delta_mi=miles, credited_at=security.now_utc()
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_a_rebuild_takes_no_fuel_from_the_dormant_ledger(
    signed_in, ingest_token, db_session, member
):
    run = log_workout(db_session, member.id, "run", 5.0)
    log_workout(db_session, member.id, "run", 3.0, offset_min=120)
    stale_credit(db_session, member.id, 16.0)

    assert signed_in.delete(f"/api/workouts/{run.id}").status_code == 204
    # The surviving run and nothing else. This is the line that unwinds an
    # account credited under the old law.
    assert round(progress_of(db_session, member.id).xp, 2) == 3.0
    assert db_session.query(models.ProcessedStepCredit).count() == 0


def test_recompute_ignores_the_dormant_ledger(db_session, member, ingest_token, signed_in):
    log_workout(db_session, member.id, "run", 4.0)
    sync(signed_in, ingest_token, metrics=reading(miles=7.0))
    stale_credit(db_session, member.id, 7.0)

    progress.recompute(db_session, member.id)
    assert round(progress_of(db_session, member.id).xp, 2) == 4.0
    assert db_session.query(models.ProcessedStepCredit).count() == 0
    # Untouched by the rebuild either way: the day rows are a record of what a
    # pedometer saw, not a derivation of anything.
    assert day_row(db_session, member.id).distance_mi == 7.0


# --------------------------------------------------------------------------
# What the screens say
# --------------------------------------------------------------------------


def test_the_letter_counts_whole_days_and_never_today(
    signed_in, ingest_token, db_session, member
):
    sync(
        signed_in,
        ingest_token,
        metrics=reading(YESTERDAY, steps=9000) + reading(TODAY, steps=4000),
    )
    letter = signed_in.get("/api/recap").json()
    # Yesterday is over and today is half lived. Counting today would print a
    # number that grows while the same letter is being read.
    assert letter["steps"] == 9000
    # In no total and in no experience: a count of steps earns nothing.
    assert letter["miles_total"] == 0.0
    assert letter["xp"] == 0.0


def test_the_letter_leaves_out_the_day_it_was_last_read(
    signed_in, ingest_token, db_session, member
):
    sync(signed_in, ingest_token, metrics=reading(YESTERDAY, steps=9000))
    assert signed_in.get("/api/recap").json()["steps"] == 9000

    assert signed_in.post("/api/recap/ack").status_code == 204
    let_a_moment_pass(db_session)
    # The acknowledgement landed today, so today and everything before it is
    # already read. Whole days only, so the day of the ack goes whole.
    assert signed_in.get("/api/recap").json()["steps"] == 0


def test_the_letter_says_nothing_about_a_day_with_no_steps(signed_in, ingest_token):
    assert signed_in.get("/api/recap").json()["steps"] == 0


def test_the_profile_carries_the_week_steps_and_no_step_miles(
    signed_in, ingest_token, db_session, member
):
    sync(
        signed_in,
        ingest_token,
        metrics=reading(TODAY, steps=11000, miles=4.0)
        + reading(MONDAY - dt.timedelta(days=7), steps=8000, miles=6.0),
    )
    profile = signed_in.get("/api/profile").json()
    # This week's count, and the week before is not in it.
    assert profile["week_steps"] == 11000
    # Not a sport, not a mile: no tile, no chip, and no figure of their own.
    assert profile["week"] == {}
    assert profile["lifetime"] == {}
    assert "week_step_mi" not in profile
    assert "lifetime_step_mi" not in profile


def test_a_friend_reads_the_miles_and_never_the_steps(
    signed_in, ingest_token, db_session, member
):
    from test_fellowship import befriend, sign_in

    friend, mate = sign_in(db_session, "mate")
    befriend(db_session, member, friend)
    log_workout(db_session, member.id, "run", 3.0)
    sync(signed_in, ingest_token, metrics=reading(steps=15000, miles=5.0))

    seen = mate.get(f"/api/profile/{member.id}").json()
    # The run and nothing else. Five miles of pedometer distance are not miles.
    assert seen["miles"] == 3.0
    assert "week_steps" not in seen


def test_the_public_counter_carries_the_steps(client, signed_in, ingest_token):
    from app.routers import stats

    sync(signed_in, ingest_token, metrics=reading(steps=7500, miles=2.0))
    stats.reset_cache()
    assert client.get("/api/stats").json() == {"miles": 0, "activities": 0, "steps": 7500}


# --------------------------------------------------------------------------
# The export as the phone really sends it
# --------------------------------------------------------------------------

# One automation's actual shape, down to the field nothing reads. The samples
# are buckets a few minutes apart rather than a figure for the day, they carry
# the device that recorded them, and the date is the space-and-offset form the
# workout parser already knows.
REAL_METRICS = {
    "data": {
        "metrics": [
            {
                "name": "step_count",
                "units": "count",
                "data": [
                    {"qty": 1040.13, "date": "2026-04-15 04:15:00 -0700", "source": "Justin's Apple Watch"},
                    {"qty": 1040.13, "date": "2026-04-15 04:20:00 -0700", "source": "Justin's Apple Watch|iPhone"},
                ],
            },
            {
                "name": "walking_running_distance",
                "units": "mi",
                "data": [
                    {"qty": 0.4928, "date": "2026-04-15 04:15:00 -0700", "source": "Justin's Apple Watch"},
                    {"qty": 0.4928, "date": "2026-04-15 04:20:00 -0700", "source": "Justin's Apple Watch|iPhone"},
                ],
            },
        ]
    }
}


def test_the_real_export_reads_as_one_day(signed_in, ingest_token, db_session, member):
    """The device a sample came from is never read. Health Auto Export has
    already settled which device owns a bucket, so the samples are summed as
    they arrive: two of them from two named sources are one day of walking, not
    two days and not half of one."""
    assert post(signed_in, ingest_token, REAL_METRICS).status_code == 200
    row = day_row(db_session, member.id)
    # 2080.26 steps, rounded once at the end rather than truncated per sample.
    assert row.steps == 2080
    assert round(row.distance_mi, 4) == 0.9856


def test_an_export_of_metrics_alone_is_not_a_refusal(signed_in, ingest_token, db_session, member):
    """His pedometer automation posts metrics with no workouts key at all. It
    is a whole sync: nothing is ignored, the day is written, the log keeps the
    payload like any other, and not one of those steps earns anything."""
    assert post(signed_in, ingest_token, REAL_METRICS).json() == {
        "imported": 0,
        "skipped": 0,
        "flagged": 0,
        "ignored": 0,
    }
    logged = db_session.query(models.IngestLog).one()
    assert logged.result["ignored_detail"] == []
    assert logged.result["step_days"] == 1
    assert logged.payload == REAL_METRICS
    assert ledger(db_session, member.id) == []
    assert progress_of(db_session, member.id).xp == 0.0


def test_a_payload_with_neither_list_is_still_logged_as_a_refusal(
    signed_in, ingest_token, db_session
):
    assert post(signed_in, ingest_token, {"data": {}}).json()["ignored"] == 1
    logged = db_session.query(models.IngestLog).one()
    assert logged.result["ignored_detail"][0]["reason"] == "no workouts list in payload"


def test_hundreds_of_samples_are_one_days_reading(signed_in, ingest_token, db_session, member):
    """A day arrives as buckets a few minutes apart, which is the resolution
    the sum has to survive."""
    points = [
        {"qty": 0.01, "date": f"2026-04-15 {hour:02d}:{minute:02d}:00 +0000", "source": "Watch"}
        for hour in range(6, 18)
        for minute in (0, 15, 30, 45)
    ]
    sync(signed_in, ingest_token, metrics=[metric("walking_running_distance", "mi", *points)])
    assert round(day_row(db_session, member.id).distance_mi, 4) == round(0.01 * len(points), 4)
