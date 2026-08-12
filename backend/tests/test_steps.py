"""Steps: what a pedometer sends, what of it earns, and what it never touches.

The law this file pins, in one sentence: walking and running distance earns
whatever the workouts of that day left over, once, and everything the game does
with a mile it does with that one too.

The clock is frozen at a Wednesday, so 2026-04-15 is today in the instance
timezone and 2026-04-13 is the Monday its week starts on. Every export here is
dated against those two on purpose: a case about a remainder must not also be a
case about which day a sample landed in.
"""

import datetime as dt

from conftest import let_a_moment_pass, log_workout
from test_ingest import post, workout as entry

from app import models, progress, security
from app.activity import parse_metrics
from app.config import daily_cap_mi

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


def ledger(db_session, user_id: int, day: dt.date = TODAY) -> list[models.StepCredit]:
    db_session.expire_all()
    return (
        db_session.query(models.StepCredit)
        .filter(models.StepCredit.user_id == user_id, models.StepCredit.day == day)
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
# The remainder
# --------------------------------------------------------------------------


def test_steps_beyond_the_days_walking_are_what_earns(signed_in, ingest_token, db_session, member):
    sync(
        signed_in,
        ingest_token,
        workouts=[entry("Outdoor Walk", f"{TODAY.isoformat()}T09:00:00+00:00", 3600, 2.0, 180)],
        metrics=reading(steps=12000, miles=5.0),
    )
    row = day_row(db_session, member.id)
    assert (row.steps, row.distance_mi) == (12000, 5.0)
    # Five miles walked, two of them logged as a workout: the workout earns
    # first and the steps fill the three miles it did not cover.
    assert round(row.credited_mi, 2) == 3.0
    assert row.capped is False


def test_a_workout_in_the_same_export_is_subtracted(signed_in, ingest_token, db_session, member):
    """The order inside one sync: the walk has to be stored before the
    remainder is worked out, or the same miles earn twice."""
    sync(
        signed_in,
        ingest_token,
        workouts=[entry("Outdoor Run", f"{TODAY.isoformat()}T07:00:00+00:00", 3600, 4.0, 400)],
        metrics=reading(miles=4.0),
    )
    assert day_row(db_session, member.id).credited_mi == 0.0
    assert ledger(db_session, member.id) == []


def test_cycling_that_day_subtracts_nothing(signed_in, ingest_token, db_session, member):
    sync(
        signed_in,
        ingest_token,
        workouts=[entry("Indoor Cycle", f"{TODAY.isoformat()}T07:00:00+00:00", 3600, 12.0, 400)],
        metrics=reading(miles=3.0),
    )
    assert day_row(db_session, member.id).credited_mi == 3.0


def test_each_day_is_settled_on_its_own(signed_in, ingest_token, db_session, member):
    sync(
        signed_in,
        ingest_token,
        workouts=[entry("Outdoor Walk", f"{TODAY.isoformat()}T09:00:00+00:00", 3600, 3.0, 200)],
        metrics=reading(TODAY, miles=4.0) + reading(YESTERDAY, miles=2.0),
    )
    assert day_row(db_session, member.id, TODAY).credited_mi == 1.0
    assert day_row(db_session, member.id, YESTERDAY).credited_mi == 2.0


def test_a_second_export_of_the_same_day_credits_only_the_increase(
    signed_in, ingest_token, db_session, member
):
    sync(signed_in, ingest_token, metrics=reading(steps=6000, miles=3.0))
    sync(signed_in, ingest_token, metrics=reading(steps=9000, miles=5.0))
    row = day_row(db_session, member.id)
    assert (row.steps, row.distance_mi, row.credited_mi) == (9000, 5.0, 5.0)
    assert [round(entry.delta_mi, 2) for entry in ledger(db_session, member.id)] == [3.0, 2.0]


def test_a_partial_export_never_takes_a_fuller_reading_back_down(
    signed_in, ingest_token, db_session, member
):
    sync(signed_in, ingest_token, metrics=reading(steps=9000, miles=5.0))
    # The window this export covers is half the day. It says less, and less is
    # not a correction.
    sync(signed_in, ingest_token, metrics=reading(steps=2000, miles=1.0))
    row = day_row(db_session, member.id)
    assert (row.steps, row.distance_mi, row.credited_mi) == (9000, 5.0, 5.0)
    assert len(ledger(db_session, member.id)) == 1


def test_a_walk_arriving_late_cannot_take_credit_back(
    signed_in, ingest_token, db_session, member
):
    sync(signed_in, ingest_token, metrics=reading(miles=5.0))
    sync(
        signed_in,
        ingest_token,
        workouts=[entry("Outdoor Walk", f"{TODAY.isoformat()}T09:00:00+00:00", 3600, 4.0, 300)],
        metrics=reading(miles=5.0),
    )
    # The remainder is one mile now, but five were already credited and spent.
    # Credit only ever rises, so nothing is withdrawn and nothing is added.
    assert day_row(db_session, member.id).credited_mi == 5.0
    assert len(ledger(db_session, member.id)) == 1


def test_the_day_is_clamped_to_the_walking_cap(signed_in, ingest_token, db_session, member):
    sync(signed_in, ingest_token, metrics=reading(miles=daily_cap_mi("walk") + 15.0))
    row = day_row(db_session, member.id)
    assert row.credited_mi == daily_cap_mi("walk")
    assert row.capped is True


def test_the_cap_counts_the_days_own_walking_first(
    signed_in, ingest_token, db_session, member
):
    sync(
        signed_in,
        ingest_token,
        workouts=[entry("Outdoor Walk", f"{TODAY.isoformat()}T09:00:00+00:00", 36000, 10.0, 900)],
        metrics=reading(miles=daily_cap_mi("walk") + 5.0),
    )
    row = day_row(db_session, member.id)
    # Ten logged plus thirty credited is the cap exactly.
    assert round(row.credited_mi, 2) == daily_cap_mi("walk") - 10.0
    assert row.capped is True


def test_the_ledger_adds_up_to_the_day(signed_in, ingest_token, db_session, member):
    for miles in (1.5, 2.25, 4.0, 4.0):
        sync(signed_in, ingest_token, metrics=reading(miles=miles))
    row = day_row(db_session, member.id)
    entries = ledger(db_session, member.id)
    assert round(sum(one.delta_mi for one in entries), 6) == round(row.credited_mi, 6)
    assert [round(one.delta_mi, 2) for one in entries] == [1.5, 0.75, 1.75]


# --------------------------------------------------------------------------
# What the credit is worth
# --------------------------------------------------------------------------


def test_step_miles_are_experience_chests_and_growth(
    signed_in, ingest_token, db_session, member
):
    from conftest import give_planting

    planted = give_planting(db_session, member.id)
    sync(signed_in, ingest_token, metrics=reading(miles=8.0))
    row = progress_of(db_session, member.id)
    # Walking converts one for one, so eight pedometer miles are eight XP.
    assert round(row.xp, 2) == 8.0
    # Level one is a 5K and level two is another 10K on top of it, so eight
    # miles stands one level up with the next in sight.
    assert row.level == 1
    # The ladder's first step, a 5K, has been paid for and dropped.
    assert db_session.query(models.Chest).filter_by(user_id=member.id).count() == 1
    db_session.expire_all()
    assert db_session.get(models.Planting, planted.id).growth_mi == 8.0


def test_a_ledger_row_is_credited_once(signed_in, ingest_token, db_session, member):
    sync(signed_in, ingest_token, metrics=reading(miles=4.0))
    progress.process_user(db_session, member.id)
    progress.process_user(db_session, member.id)
    assert round(progress_of(db_session, member.id).xp, 2) == 4.0
    assert (
        db_session.query(models.ProcessedStepCredit).count()
        == db_session.query(models.StepCredit).count()
    )


def test_steps_earn_no_race_medal_and_no_calories(
    signed_in, ingest_token, db_session, member
):
    sync(signed_in, ingest_token, metrics=reading(miles=30.0))
    # Thirty miles in a day, and not one of the five race medals: those are
    # sessions somebody ran, and this is a day of walking about.
    assert db_session.query(models.BadgeEarn).filter_by(user_id=member.id).count() == 0
    # No workout row either, so there is nothing to appear in a feed and no
    # energy to become manna.
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


def test_a_week_carried_over_the_line_by_steps_names_no_workout(
    signed_in, ingest_token, db_session, member
):
    log_workout(db_session, member.id, "run", 9.0)
    # The pedometer counted the run as well as the wandering about, so eleven
    # miles of walking and running distance leaves two of remainder.
    sync(signed_in, ingest_token, metrics=reading(miles=11.0))
    row = weekly_row(db_session, member.id)
    assert row.badge_id == "weekly_10"
    assert row.week_start == MONDAY
    # There is no session it happened in, so the row says so rather than
    # blaming the nine mile run that was already behind the line.
    assert row.workout_id is None
    assert row.earned_at == security.now_utc()


def test_a_week_the_workouts_carry_still_names_the_workout(
    signed_in, ingest_token, db_session, member
):
    sync(signed_in, ingest_token, metrics=reading(miles=2.0))
    crossing = log_workout(db_session, member.id, "run", 11.0)
    row = weekly_row(db_session, member.id)
    assert row.badge_id == "weekly_10"
    assert row.workout_id == crossing.id


def test_the_week_upgrades_in_place_over_the_same_total(
    signed_in, ingest_token, db_session, member
):
    log_workout(db_session, member.id, "run", 9.0)
    sync(signed_in, ingest_token, metrics=reading(miles=11.0))
    assert weekly_row(db_session, member.id).badge_id == "weekly_10"
    # More steps on the same week, over the same running total: one row still,
    # holding the better medal.
    sync(signed_in, ingest_token, metrics=reading(miles=19.0))
    row = weekly_row(db_session, member.id)
    assert row.badge_id == "weekly_15"
    assert row.workout_id is None


def test_steps_dated_last_week_land_on_last_weeks_medal(
    signed_in, ingest_token, db_session, member
):
    last_week = MONDAY - dt.timedelta(days=2)
    sync(signed_in, ingest_token, metrics=reading(last_week, miles=12.0))
    row = weekly_row(db_session, member.id)
    # Credited today, walked the week before: the medal belongs to the week
    # that covered the ground.
    assert row.week_start == last_week - dt.timedelta(days=last_week.weekday())
    assert row.badge_id == "weekly_10"


# --------------------------------------------------------------------------
# Deleting, restoring, rebuilding
# --------------------------------------------------------------------------


def test_deleting_a_walk_never_grows_the_step_credit(
    signed_in, ingest_token, db_session, member
):
    walk = log_workout(db_session, member.id, "walk", 4.0)
    sync(signed_in, ingest_token, metrics=reading(miles=6.0))
    assert day_row(db_session, member.id).credited_mi == 2.0

    assert signed_in.delete(f"/api/workouts/{walk.id}").status_code == 204
    sync(signed_in, ingest_token, metrics=reading(miles=6.0))
    # The walk is gone from every total on the screen and is still subtracted
    # here: otherwise deleting it and syncing again would earn it twice.
    assert day_row(db_session, member.id).credited_mi == 2.0
    assert len(ledger(db_session, member.id)) == 1

    assert signed_in.post(f"/api/workouts/{walk.id}/restore").status_code == 200
    sync(signed_in, ingest_token, metrics=reading(miles=6.0))
    assert day_row(db_session, member.id).credited_mi == 2.0


def test_a_rebuild_counts_the_ledger_as_fuel(signed_in, ingest_token, db_session, member):
    run = log_workout(db_session, member.id, "run", 5.0)
    # Eleven miles of pedometer distance over a five mile run: six of credit.
    sync(signed_in, ingest_token, metrics=reading(miles=11.0))
    assert round(progress_of(db_session, member.id).xp, 2) == 11.0

    assert signed_in.delete(f"/api/workouts/{run.id}").status_code == 204
    # The run's miles are gone and the step miles are still there, because
    # nothing about a deletion touches what the pedometer counted.
    assert round(progress_of(db_session, member.id).xp, 2) == 6.0
    assert len(ledger(db_session, member.id)) == 1


def test_a_rebuild_never_re_drops_a_chest_the_steps_paid_for(
    signed_in, ingest_token, db_session, member
):
    run = log_workout(db_session, member.id, "run", 4.0)
    sync(signed_in, ingest_token, metrics=reading(miles=24.0))
    before = db_session.query(models.Chest).filter_by(user_id=member.id).count()
    assert before > 0

    assert signed_in.delete(f"/api/workouts/{run.id}").status_code == 204
    assert db_session.query(models.Chest).filter_by(user_id=member.id).count() == before


def test_recompute_replays_the_ledger_and_nothing_twice(db_session, member, ingest_token, signed_in):
    sync(signed_in, ingest_token, metrics=reading(miles=7.0))
    progress.recompute(db_session, member.id)
    assert round(progress_of(db_session, member.id).xp, 2) == 7.0
    assert (
        db_session.query(models.ProcessedStepCredit).count()
        == db_session.query(models.StepCredit).count()
    )


# --------------------------------------------------------------------------
# What the screens say
# --------------------------------------------------------------------------


def test_the_letter_says_what_the_steps_covered(signed_in, ingest_token, db_session, member):
    sync(signed_in, ingest_token, metrics=reading(miles=3.42))
    letter = signed_in.get("/api/recap").json()
    assert letter["step_miles"] == 3.42
    # Outside the four rows and outside their total: the total under them has
    # to be the total of the rows a reader can see.
    assert letter["miles_total"] == 0.0
    # But inside the XP: step credit is experience at the walk's weight, and
    # the letter's XP row owns everything the window earned.
    assert letter["xp"] == 3.42

    assert signed_in.post("/api/recap/ack").status_code == 204
    let_a_moment_pass(db_session)
    assert signed_in.get("/api/recap").json()["step_miles"] == 0.0


def test_the_profile_carries_the_week_and_the_lifetime_step_miles(
    signed_in, ingest_token, db_session, member
):
    sync(
        signed_in,
        ingest_token,
        metrics=reading(TODAY, steps=11000, miles=4.0)
        + reading(MONDAY - dt.timedelta(days=7), miles=6.0),
    )
    profile = signed_in.get("/api/profile").json()
    assert profile["week_step_mi"] == 4.0
    assert profile["lifetime_step_mi"] == 10.0
    assert profile["week_steps"] == 11000
    # Not a sport: no tile, no chip, nothing in either table.
    assert profile["week"] == {}
    assert profile["lifetime"] == {}


def test_a_friend_reads_the_miles_and_never_the_steps(
    signed_in, ingest_token, db_session, member
):
    from test_fellowship import befriend, sign_in

    friend, mate = sign_in(db_session, "mate")
    befriend(db_session, member, friend)
    sync(signed_in, ingest_token, metrics=reading(steps=15000, miles=5.0))

    seen = mate.get(f"/api/profile/{member.id}").json()
    assert seen["miles"] == 5.0
    assert "week_steps" not in seen
    assert "week_step_mi" not in seen


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
    assert round(row.credited_mi, 4) == 0.9856


def test_an_export_of_metrics_alone_is_not_a_refusal(signed_in, ingest_token, db_session, member):
    """His pedometer automation posts metrics with no workouts key at all. It
    is a whole sync: nothing is ignored, the ledger is written, the credit is
    applied, and the log keeps the payload like any other."""
    assert post(signed_in, ingest_token, REAL_METRICS).json() == {
        "imported": 0,
        "skipped": 0,
        "flagged": 0,
        "ignored": 0,
    }
    logged = db_session.query(models.IngestLog).one()
    assert logged.result["ignored_detail"] == []
    assert logged.result["step_credits"] == 1
    assert logged.payload == REAL_METRICS
    assert len(ledger(db_session, member.id)) == 1
    assert round(progress_of(db_session, member.id).xp, 4) == 0.9856


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
